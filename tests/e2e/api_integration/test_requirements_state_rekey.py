"""The re-keying migration, on data shaped like the one that went wrong.

A write-up that resolved its engagement through an in-memory map after a
restart filed the requirements state under the meeting id. The resolution is
fixed; rows already written are not reachable by a code change, so they are
moved here.

What the migration must not do is as important as what it must. An engagement
that already has a state has it from a run that resolved correctly, and this
row's provenance is the worse of the two — so a collision leaves both alone
rather than picking a winner.
"""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa

from app.persistence.models import metadata
from migrations.versions.requirements_state_rekey import rekey_misfiled_state


def _database(path: Path) -> sa.Engine:
    """The tables as the ORM declares them, which is what the service runs on."""

    engine = sa.create_engine(f"sqlite:///{path}")
    metadata.create_all(engine)
    return engine


def _row(table: sa.Table, **given: object) -> dict[str, object]:
    """A minimal legal row: what was asked for, plus a filler per NOT NULL.

    Derived from the table rather than written out, so a new required column
    does not turn this test into a list of constraint errors discovered one at
    a time. What the row *says* does not matter here; that it exists does.
    """

    row = dict(given)
    for column in table.columns:
        if column.name in row or column.nullable or column.default is not None:
            continue
        row[column.name] = 0 if isinstance(column.type, (sa.Integer, sa.Float)) else "x"
    return row


def _seed(engine: sa.Engine, rows: list[tuple[str, str]], states: list[str]) -> None:
    engagements = metadata.tables["engagements"]
    meetings = metadata.tables["meetings"]
    with engine.begin() as conn:
        for meeting_id, engagement_id in rows:
            existing = conn.execute(
                sa.select(engagements.c.id).where(engagements.c.id == engagement_id)
            ).first()
            if existing is None:
                conn.execute(sa.insert(engagements).values(**_row(engagements, id=engagement_id)))
            conn.execute(
                sa.insert(meetings).values(
                    **_row(meetings, id=meeting_id, engagement_id=engagement_id)
                )
            )
        for key in states:
            conn.execute(
                sa.text(
                    "INSERT INTO requirements_state "
                    "(engagement_id, confirmed_requirements, contradictions, decisions, updated_at) "
                    "VALUES (:k, '[]', '[]', :d, '2026-08-26')"
                ),
                {"k": key, "d": f'["from {key}"]'},
            )


def _keys(engine: sa.Engine) -> dict[str, str]:
    with engine.begin() as conn:
        return {
            row.engagement_id: row.decisions
            for row in conn.execute(
                sa.text("SELECT engagement_id, decisions FROM requirements_state")
            )
        }


def test_a_state_filed_under_a_meeting_moves_to_its_engagement(tmp_path):
    engine = _database(tmp_path / "state.db")
    _seed(engine, [("meeting-3", "eng-6")], ["meeting-3"])

    with engine.begin() as conn:
        assert rekey_misfiled_state(conn) == 1

    assert set(_keys(engine)) == {"eng-6"}
    assert _keys(engine)["eng-6"] == '["from meeting-3"]'


def test_an_engagement_that_already_has_a_state_is_left_alone(tmp_path):
    """Its row came from a run that resolved correctly. Nothing here beats it."""

    engine = _database(tmp_path / "state.db")
    _seed(engine, [("meeting-3", "eng-6")], ["meeting-3", "eng-6"])

    with engine.begin() as conn:
        assert rekey_misfiled_state(conn) == 0, "a collision moves nothing"

    keys = _keys(engine)
    assert set(keys) == {"eng-6", "meeting-3"}, "a collision must not clobber"
    assert keys["eng-6"] == '["from eng-6"]', "the correctly-filed row survives"


def test_running_it_twice_changes_nothing_the_second_time(tmp_path):
    engine = _database(tmp_path / "state.db")
    _seed(engine, [("meeting-3", "eng-6")], ["meeting-3"])

    with engine.begin() as conn:
        rekey_misfiled_state(conn)
    once = _keys(engine)
    with engine.begin() as conn:
        assert rekey_misfiled_state(conn) == 0, "the second run has nothing to do"

    assert _keys(engine) == once
