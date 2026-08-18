"""create utterance_tokens table

Revision ID: utterance_tokens
Revises: nudges
Create Date: 2026-08-18

Persists the per-word breakdown of a transcribed utterance (PRD FR-2.3,
FR-2.13): each row is one token's `text`, its transcription `confidence`,
the `language_tag` the language-identification pass assigned it, and that
tag's own `language_confidence`. Span gating reads this table rather than
re-tokenizing `utterances.text` on the fly, because NFR-5.6 requires
suppressing a trigger "when the trigger span itself falls below a
confidence threshold" — that decision needs each word's own confidence and
language-tag confidence, not just the whole utterance's aggregate. `text`
is duplicated here rather than re-sliced from `utterances.text` at read
time because a token boundary is a tokenizer decision, not a pure
character-offset fact, and NFR-5.6's suppression logic must see exactly
what the transcription pipeline scored. `position` orders tokens within
their utterance (mirrors the ordering `utterances.start_ms` gives across
utterances within a meeting), since span gating needs the sequence of words
intact to walk a trigger span. `span_start`/`span_end` locate the token as
a character range within `utterances.text`, the same span representation
`trigger_events.span_start`/`span_end` already established, so a trigger's
span can be intersected against the tokens it covers. `utterance_id` is a
foreign key to `utterances.id`, matching the pattern `trigger_events` and
`citations` already established, since a token only ever exists in the
context of the one utterance it was transcribed from.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "utterance_tokens"
down_revision = "nudges"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "utterance_tokens",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "utterance_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("utterances.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("span_start", sa.Integer(), nullable=False),
        sa.Column("span_end", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("language_tag", sa.String(length=32), nullable=False),
        sa.Column("language_confidence", sa.Float(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_utterance_tokens_utterance_id_position",
        "utterance_tokens",
        ["utterance_id", "position"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_utterance_tokens_utterance_id_position",
        table_name="utterance_tokens",
    )
    op.drop_table("utterance_tokens")
