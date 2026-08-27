"""re-key requirements_state rows filed under a meeting id

Revision ID: requirements_state_rekey
Revises: debrief_outcomes
Create Date: 2026-08-27

The Engagement arc reads `/api/engagements/{id}/state`, and on a real
engagement it answered `requirements_state: null` after a write-up that had
plainly succeeded. The state existed; it was filed under the meeting.

`_run_debrief_when_record_path_completes` resolved the engagement through two
in-memory maps and then fell back to the session id. After a restart neither
map knows anything about a meeting the previous process created, so the
fallback fired — and the button that reruns a write-up exists precisely for a
run that did not happen when the recording finished, which is to say after a
restart. The failure was reachable only on the path the feature was built for.

That is fixed in the resolution itself. This moves the rows already written,
which no code change can reach: a row keyed by a meeting id is re-keyed to
that meeting's engagement.

Two things it will not do. It never overwrites an engagement that already has
a state — that row is the product of a real run and this one's provenance is
worse, so a collision leaves both alone rather than picking a winner. And it
touches nothing whose key is not a meeting id, so running it twice does
nothing the second time.
"""

from alembic import op
import sqlalchemy as sa

revision = "requirements_state_rekey"
down_revision = "debrief_outcomes"
branch_labels = None
depends_on = None


def rekey_misfiled_state(bind: sa.engine.Connection) -> int:
    """Move every state keyed by a meeting onto that meeting's engagement.

    A plain function over a connection rather than logic inside `upgrade`, so
    the three things it must and must not do can be asserted without an
    alembic runner. Returns how many rows moved, which is what makes "running
    it twice does nothing" checkable.
    """

    moved = 0

    # Only rows whose key is a meeting, and only where the engagement that
    # meeting belongs to has no state of its own yet.
    misfiled = bind.execute(
        sa.text(
            """
            SELECT rs.engagement_id AS wrong_key, m.engagement_id AS right_key
            FROM requirements_state AS rs
            JOIN meetings AS m ON m.id = rs.engagement_id
            """
        )
    ).fetchall()

    for wrong_key, right_key in misfiled:
        if right_key is None or right_key == wrong_key:
            continue
        taken = bind.execute(
            sa.text("SELECT 1 FROM requirements_state WHERE engagement_id = :key"),
            {"key": right_key},
        ).first()
        if taken is not None:
            # The engagement already has a state from a run that resolved
            # correctly. Leaving both is the honest outcome: this row's
            # provenance is the worse of the two and nothing here can merge
            # them.
            continue
        bind.execute(
            sa.text(
                "UPDATE requirements_state SET engagement_id = :right "
                "WHERE engagement_id = :wrong"
            ),
            {"right": right_key, "wrong": wrong_key},
        )
        moved += 1

    return moved


def upgrade() -> None:
    if op.get_context().as_sql:
        # Offline mode renders SQL without a database, and every revision in
        # this chain is executed that way by `test_migrations` — cheaply, and
        # without needing one. A schema change renders fine; this one cannot,
        # because which rows to move is a question only the data answers.
        #
        # Standing aside is the honest outcome rather than a gap in coverage:
        # `rekey_misfiled_state` is a plain function over a connection for
        # exactly this reason, and what it must and must not do is asserted
        # directly against a real database instead.
        return
    rekey_misfiled_state(op.get_bind())


def downgrade() -> None:
    """Deliberately a no-op.

    The reverse is "put the state back under a meeting id", which is the bug.
    Recording that this cannot be undone is more useful than an operation
    nobody would want performed.
    """
