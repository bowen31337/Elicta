"""create nudges table

Revision ID: nudges
Revises: trigger_events
Create Date: 2026-08-18

Persists every nudge actually surfaced to the operator during a live call
(PRD FR-5.11: "every surfaced nudge must carry its trigger reason"; FR-7.4:
the debrief thread opens already knowing "which nudges fired, which were
taken, and which were parked"). Without a durable row per surfacing, the
live path's trigger-to-nudge decision is only ever visible transiently in
the live UI, and `debrief/session/service.py`'s `load_nudge_signal` (see
`NudgeDispositionRecord` in `debrief/session/models.py`) would have nothing
engagement-durable to read once the call has ended.

`candidate_id` identifies the nudge candidate that was surfaced — the
live-mode nudge generation path's own identifier for it (mirrors
`NudgeDispositionRecord.nudge_id`) — and is a plain opaque string rather
than a foreign key, because nudge candidates themselves are generated and
scored in the live path and have no table of their own to key off, the same
reasoning `citations.session_id` already established for referencing an
identifier that lives outside this schema. `trigger_event_id` is a real
foreign key to `trigger_events.id`, because every surfaced nudge fires off
exactly one recorded trigger event and FR-5.11's "trigger reason" traces
back to that event's own span and confidence. `surfaced_at` is the moment
the nudge was actually shown to the operator, not merely generated, since
FR-5.11 and FR-7.4 both scope to nudges that surfaced. `disposition` mirrors
`NudgeDisposition` (fired/taken/parked) and defaults to `fired`, the state a
nudge is in at the instant it surfaces, before the operator has acted on it
or the call has ended. `trigger_reason` is copied onto the row rather than
re-derived by joining `trigger_events` at read time, so the debrief thread's
inherited nudge trace (FR-7.4) reads directly off this table without a
second lookup.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "nudges"
down_revision = "trigger_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "nudges",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("candidate_id", sa.String(length=64), nullable=False),
        sa.Column(
            "trigger_event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("trigger_events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "surfaced_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "disposition",
            sa.String(length=16),
            nullable=False,
            server_default="fired",
        ),
        sa.Column("trigger_reason", sa.Text(), nullable=False),
    )
    op.create_index(
        "ix_nudges_trigger_event_id",
        "nudges",
        ["trigger_event_id"],
    )
    op.create_index(
        "ix_nudges_candidate_id",
        "nudges",
        ["candidate_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_nudges_candidate_id", table_name="nudges")
    op.drop_index("ix_nudges_trigger_event_id", table_name="nudges")
    op.drop_table("nudges")
