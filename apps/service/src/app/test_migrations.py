"""The migration chain must stay runnable.

For a long time these revisions could not run at all: there was no
`alembic.ini`, no `env.py`, and `alembic` was not a declared dependency, so
nothing ever executed an `upgrade()` body. A schema that only exists as
unexecuted Python is not a schema.

These run the whole chain in offline mode, which executes every revision's
`upgrade()` and renders SQL without needing a live database — cheap enough
for every test run, and enough to catch a broken revision, a broken link in
the chain, or a second head appearing from a parallel merge.
"""

from __future__ import annotations

import io
from contextlib import redirect_stdout
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

REPO_ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture
def alembic_config() -> Config:
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    return config


def test_the_chain_has_exactly_one_head(alembic_config: Config) -> None:
    """Two heads mean two parallel branches nothing has merged."""

    heads = ScriptDirectory.from_config(alembic_config).get_heads()

    assert len(heads) == 1, f"expected a single head, found {heads}"


def test_every_revision_runs_from_base_to_head(alembic_config: Config) -> None:
    """Executes all 20 `upgrade()` bodies and renders the resulting SQL."""

    rendered = io.StringIO()
    with redirect_stdout(rendered):
        command.upgrade(alembic_config, "head", sql=True)

    sql = rendered.getvalue()

    assert "CREATE TABLE alembic_version" in sql
    created = sql.count("CREATE TABLE ")
    assert created >= 20, f"expected the full schema, saw {created} CREATE TABLE statements"


def test_the_schema_the_routers_depend_on_is_actually_created(
    alembic_config: Config,
) -> None:
    """Spot-check the tables the mounted API surface reads and writes."""

    rendered = io.StringIO()
    with redirect_stdout(rendered):
        command.upgrade(alembic_config, "head", sql=True)

    sql = rendered.getvalue()

    for table in (
        "engagements",
        "meetings",
        "attendees",
        "candidates",
        "nudges",
        "artifacts",
        "citations",
        "coverage_slots",
        "egress_log",
        "reference_documents",
        "vocabulary_terms",
    ):
        assert f"CREATE TABLE {table}" in sql, f"{table} is never created"
