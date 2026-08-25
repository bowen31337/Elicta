"""SQLite settings storage.

Two claims carry this module and both are tested against the file on disk
rather than through the store's own API: that settings survive a restart, and
that a credential is not sitting in the database in the clear. The second is
checked by reading the raw bytes, because a store that encrypts on the way out
but not on the way in would pass every round-trip test.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from .models import (
    AuthMode,
    ConnectorSettings,
    InferenceSettings,
    SecretKey,
    SpeechVendor,
)
from .sqlite_store import KEY_ENV_VAR, SqliteSettingsStore

REAL_KEY = "sk-ant-api03-DISKSECRET-abcd"


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "settings.db"


def _store(db: Path) -> SqliteSettingsStore:
    return SqliteSettingsStore(db, read_environment=False)


# --------------------------------------------------------------------------
# Persistence — the reason for moving off the in-memory store.
# --------------------------------------------------------------------------


def test_settings_survive_a_restart(db: Path) -> None:
    store = _store(db)
    store.write_inference(InferenceSettings(model="claude-sonnet-5"))
    store.set_secret(SecretKey.ANTHROPIC_API_KEY, REAL_KEY)

    reopened = _store(db)

    assert reopened.read().inference.model == "claude-sonnet-5"
    assert reopened.get_secret(SecretKey.ANTHROPIC_API_KEY).reveal() == REAL_KEY


def test_the_store_reports_itself_durable(db: Path) -> None:
    """The admin screen drops its "these will be lost" warning off this."""

    assert _store(db).durable is True
    assert _store(db).read().durable is True


def test_connector_choices_persist(db: Path) -> None:
    store = _store(db)
    store.write_connectors(
        ConnectorSettings(
            record_vendors=[SpeechVendor.ASSEMBLYAI, SpeechVendor.DEEPGRAM],
            region="eu",
        )
    )

    connectors = _store(db).read().connectors

    assert connectors.record_vendors == [SpeechVendor.ASSEMBLYAI, SpeechVendor.DEEPGRAM]
    assert connectors.region == "eu"


def test_the_auth_mode_persists_with_the_rest_of_the_inference_settings(db: Path) -> None:
    store = _store(db)
    store.write_inference(InferenceSettings(auth_mode=AuthMode.OAUTH_TOKEN))

    assert _store(db).read().inference.auth_mode is AuthMode.OAUTH_TOKEN


# --------------------------------------------------------------------------
# Encryption at rest (NFR-2.5).
# --------------------------------------------------------------------------


def test_a_credential_is_not_written_to_the_database_in_the_clear(db: Path) -> None:
    """Read the raw file, not the store's API.

    A store that encrypted on read but not on write would round-trip
    perfectly and still leak every credential to anyone with the file.
    """

    _store(db).set_secret(SecretKey.ANTHROPIC_API_KEY, REAL_KEY)

    raw = db.read_bytes()

    assert REAL_KEY.encode() not in raw
    assert b"DISKSECRET" not in raw


def test_the_stored_row_is_ciphertext(db: Path) -> None:
    _store(db).set_secret(SecretKey.ANTHROPIC_API_KEY, REAL_KEY)

    with sqlite3.connect(db) as connection:
        row = connection.execute(
            "SELECT ciphertext FROM secrets WHERE key = ?",
            (SecretKey.ANTHROPIC_API_KEY.value,),
        ).fetchone()

    assert REAL_KEY.encode() not in row[0]
    assert row[0].startswith(b"gAAAAA")  # a Fernet token


def test_the_key_file_is_not_world_readable(db: Path) -> None:
    """The key beside the ciphertext is the thing worth protecting."""

    _store(db)

    mode = os.stat(db.with_suffix(".key")).st_mode & 0o777

    assert mode == 0o600


def test_the_key_is_not_kept_in_the_database_it_protects(db: Path) -> None:
    _store(db).set_secret(SecretKey.ANTHROPIC_API_KEY, REAL_KEY)

    key_material = db.with_suffix(".key").read_bytes()

    assert key_material not in db.read_bytes()


def test_a_configured_key_is_used_instead_of_a_generated_one(
    db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pointing this at a KMS or a mounted secret is the deployment path."""

    monkeypatch.setenv(KEY_ENV_VAR, Fernet.generate_key().decode())

    store = SqliteSettingsStore(db, read_environment=False)
    store.set_secret(SecretKey.ANTHROPIC_API_KEY, REAL_KEY)

    assert not db.with_suffix(".key").exists(), "no key file when one is supplied"
    assert store.get_secret(SecretKey.ANTHROPIC_API_KEY).reveal() == REAL_KEY


def test_a_secret_encrypted_with_a_different_key_reads_as_unconfigured(
    db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rotated or lost key must degrade, not crash the service.

    "Re-enter your credential" is recoverable; a service that will not start
    because of an old ciphertext is not.
    """

    monkeypatch.setenv(KEY_ENV_VAR, Fernet.generate_key().decode())
    SqliteSettingsStore(db, read_environment=False).set_secret(
        SecretKey.ANTHROPIC_API_KEY, REAL_KEY
    )

    monkeypatch.setenv(KEY_ENV_VAR, Fernet.generate_key().decode())
    rotated = SqliteSettingsStore(db, read_environment=False)

    assert rotated.get_secret(SecretKey.ANTHROPIC_API_KEY) is None
    assert rotated.read().secrets[0].configured is False


def test_a_tampered_ciphertext_is_rejected_rather_than_decoded(db: Path) -> None:
    """Fernet authenticates, so an edited row fails instead of yielding garbage."""

    store = _store(db)
    store.set_secret(SecretKey.ANTHROPIC_API_KEY, REAL_KEY)

    with sqlite3.connect(db) as connection:
        connection.execute(
            "UPDATE secrets SET ciphertext = ? WHERE key = ?",
            (b"gAAAAAtampered", SecretKey.ANTHROPIC_API_KEY.value),
        )

    assert store.get_secret(SecretKey.ANTHROPIC_API_KEY) is None


def test_clearing_a_secret_removes_the_row_rather_than_blanking_it(db: Path) -> None:
    store = _store(db)
    store.set_secret(SecretKey.ANTHROPIC_API_KEY, REAL_KEY)

    store.set_secret(SecretKey.ANTHROPIC_API_KEY, "")

    with sqlite3.connect(db) as connection:
        rows = connection.execute("SELECT COUNT(*) FROM secrets").fetchone()[0]
    assert rows == 0


def test_the_environment_still_serves_as_a_fallback(
    db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", REAL_KEY)

    store = SqliteSettingsStore(db)

    assert store.get_secret(SecretKey.ANTHROPIC_API_KEY) is not None


def test_a_stored_value_wins_over_the_environment(
    db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-from-environment")
    store = SqliteSettingsStore(db)

    store.set_secret(SecretKey.ANTHROPIC_API_KEY, REAL_KEY)

    assert store.get_secret(SecretKey.ANTHROPIC_API_KEY).reveal() == REAL_KEY


def test_the_document_source_survives_a_restart(tmp_path):
    """The whole point of the durable store: a connector configured once stays
    configured. A section the SQLite store forgets to persist looks identical
    to one nobody filled in."""
    from app.modules.settings.models import DocumentSourceSettings, SecretKey
    from app.modules.settings.sqlite_store import SqliteSettingsStore

    path = tmp_path / "settings.db"
    first = SqliteSettingsStore(path, read_environment=False)
    first.write_documents(DocumentSourceSettings(tenant_id="t-1", client_id="c-1"))
    first.set_secret(SecretKey.MICROSOFT_GRAPH_CLIENT_SECRET, "shhh")

    reopened = SqliteSettingsStore(path, read_environment=False)

    assert reopened.read().documents.tenant_id == "t-1"
    assert reopened.read().documents.client_id == "c-1"
    secret = reopened.get_secret(SecretKey.MICROSOFT_GRAPH_CLIENT_SECRET)
    assert secret is not None
    assert secret.reveal() == "shhh"


def test_the_consent_model_survives_a_restart(db: Path) -> None:
    """A setting that governs whether anyone is asked has to be durable.

    Held only in memory it would revert to the default on every restart, and
    an operator who deliberately turned per-meeting asking back on would find
    it silently off again — the failure being that nobody is asked, which
    nothing on screen would report.
    """

    from .models import ConsentModelSetting, ConsentSettings

    _store(db).write_consent(ConsentSettings(model=ConsentModelSetting.PER_MEETING))

    assert _store(db).read().consent.model is ConsentModelSetting.PER_MEETING


def test_consent_reads_as_standing_before_anyone_saves_one(db: Path) -> None:
    from .models import ConsentModelSetting

    assert _store(db).read().consent.model is ConsentModelSetting.ENGAGEMENT_LEVEL
