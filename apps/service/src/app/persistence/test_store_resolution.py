"""Unit tests for the parts of `store` that no HTTP round-trip reaches.

`test_store.py` proves durability the honest way — write over the API, throw the
application away, read back from a second one. That leaves the module's edges
uncovered: how a database URL is chosen and redacted, what the collections do
when the row they expect is not there, and which values refuse to serialise.
Those are the branches an operator meets on a misconfigured deployment, so they
are tested here directly rather than left to be discovered in production.
"""

from __future__ import annotations

import threading
from enum import Enum
from pathlib import Path

import pytest
import sqlalchemy as sa

from app.persistence.models import metadata
from app.persistence.store import (
    DurableMapping,
    StateStore,
    _add_missing_columns,
    _json_default,
    default_database_url,
    dump,
    redact_database_url,
    resolve_database_url,
)


class _Vendor(Enum):
    DEEPGRAM = "deepgram"


@pytest.fixture
def store(tmp_path: Path) -> StateStore:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'state.db'}")
    metadata.create_all(engine)
    return StateStore(engine)


# --- choosing a database ---------------------------------------------------


def test_default_database_url_prefers_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://elicta@db.internal/elicta")

    assert default_database_url() == "postgresql://elicta@db.internal/elicta"


def test_default_database_url_strips_the_async_driver_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The migration chain is written for asyncpg; these collections are
    # synchronous, so a URL copied from the migration config must still open.
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://elicta@db.internal/elicta")

    assert default_database_url() == "postgresql://elicta@db.internal/elicta"


def test_default_database_url_falls_back_to_a_file_under_the_state_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("ELICTA_STATE_DIR", str(tmp_path / "state"))

    url = default_database_url()

    assert url == f"sqlite:///{tmp_path / 'state' / 'state.db'}"
    # The directory is made, not merely named — the desktop product ships to
    # people who have not created it.
    assert (tmp_path / "state").is_dir()


def test_a_configured_url_beats_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://from-env/elicta")

    assert resolve_database_url("postgresql://from-settings/elicta") == (
        "postgresql://from-settings/elicta"
    )


# --- showing a database URL back -------------------------------------------


def test_redacting_nothing_is_nothing() -> None:
    assert redact_database_url("") == ""


def test_an_unparseable_url_is_described_rather_than_echoed() -> None:
    # An unbracketed IPv6 host makes urlsplit raise. The string may still carry
    # a password, so nothing of it is returned.
    unreadable = "postgresql://elicta:hunter2@[::1/elicta"

    assert redact_database_url(unreadable) == "(unreadable)"


# --- collections over rows that are not there ------------------------------


def test_adding_missing_columns_skips_tables_that_do_not_exist() -> None:
    # A brand-new engine has none of them. The catch-up pass is additive only,
    # so it must leave an empty database empty rather than creating anything.
    engine = sa.create_engine("sqlite://")

    _add_missing_columns(engine)

    assert sa.inspect(engine).get_table_names() == []


def test_deleting_a_row_that_is_not_there_is_not_an_error(store: StateStore) -> None:
    store._delete(metadata.tables["engagements"], "id", "no-such-engagement")

    assert store._rows(metadata.tables["engagements"]) == []


def test_document_text_arriving_before_the_document_creates_its_row(store: StateStore) -> None:
    # The composition root may write the extracted text before the document is
    # listed. The text must survive that ordering, not be dropped for having
    # no row to update.
    texts = store.document_texts()

    texts["doc-1"] = "Inbound pallets are cross-docked within four hours."

    reopened = StateStore(store.engine).document_texts()
    assert reopened["doc-1"] == "Inbound pallets are cross-docked within four hours."


def test_the_engine_is_reachable_for_a_second_store(store: StateStore) -> None:
    assert StateStore(store.engine).engine is store.engine


def test_a_durable_mapping_shows_its_contents(store: StateStore) -> None:
    mapping: DurableMapping[str, str] = DurableMapping(
        loaded={"a": "1"},
        persist=lambda key, value: None,
        forget=lambda key: None,
        lock=threading.Lock(),
    )

    assert repr(mapping) == "DurableMapping({'a': '1'})"


# --- serialising what the models carry -------------------------------------


def test_an_enum_serialises_as_its_value() -> None:
    assert _json_default(_Vendor.DEEPGRAM) == "deepgram"


def test_a_value_with_no_representation_refuses_rather_than_inventing_one() -> None:
    with pytest.raises(TypeError, match="cannot serialise object"):
        _json_default(object())


def test_dumping_a_plain_value_does_not_require_a_model() -> None:
    assert dump({"vendor": _Vendor.DEEPGRAM}) == {"vendor": "deepgram"}
