"""create trigger_events table

Revision ID: trigger_events
Revises: citations_original_utterance
Create Date: 2026-08-18

Persists the outcome of evaluating a finalised utterance against the trigger
gate (PRD FR-5.1): "evaluate every finalised utterance against the trigger
gate" only has an auditable, calibratable record (FR-5.11: "every surfaced
nudge must carry its trigger reason") if each firing is stored, not just
acted on transiently in the live path. `utterance_id` is a foreign key to
`utterances.id`, matching the pattern `citations.utterance_id` already
established, because a trigger event only ever exists in the context of the
one finalised utterance it fired against. `trigger_kind` records which of
the deterministic or model-path triggers fired (FR-5.2 vague quantifier,
FR-5.3 unnamed actor, FR-5.4 contradiction, FR-5.5 novel entity, FR-5.6
coverage gap). `span_start`/`span_end` locate the exact substring of the
utterance's text that the trigger fired on, since a trigger reason
(FR-5.11) needs to point at the specific words that caused it rather than
the whole utterance. `confidence` records the trigger span's own confidence
score, because NFR-5.6 requires "triggers suppressed when the trigger span
itself falls below a confidence threshold" — persisting the score alongside
the event is what lets that suppression decision be audited after the fact
rather than trusted blindly.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "trigger_events"
down_revision = "citations_original_utterance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trigger_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("trigger_kind", sa.String(length=32), nullable=False),
        sa.Column(
            "utterance_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("utterances.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("span_start", sa.Integer(), nullable=False),
        sa.Column("span_end", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_trigger_events_utterance_id",
        "trigger_events",
        ["utterance_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_trigger_events_utterance_id", table_name="trigger_events")
    op.drop_table("trigger_events")
