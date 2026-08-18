"""create utterances table

Revision ID: utterances
Revises: coverage_slots
Create Date: 2026-08-18

Persists the append-only stream of transcribed speech segments captured
during a meeting (PRD FR-2.3, FR-2.7): which meeting and audio `stream_id`
it came from, the `speaker_tag` attributed to it, the transcribed `text`,
its `start_ms`/`end_ms` offsets within the recording, and the `source_path`
to the underlying audio so a segment can be re-derived or replayed. Rows are
append-only — the live capture pipeline only ever inserts new utterances as
speech is transcribed, it never revises one in place, so there is no
`updated_at` column. `meeting_id` is a foreign key rather than a duplicated
session identifier, matching `coverage_slots.meeting_id`, since an utterance
only ever exists in the context of the one meeting it was captured in.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "utterances"
down_revision = "coverage_slots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "utterances",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "meeting_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("meetings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("stream_id", sa.String(length=64), nullable=False),
        sa.Column("speaker_tag", sa.String(length=64), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("start_ms", sa.Integer(), nullable=False),
        sa.Column("end_ms", sa.Integer(), nullable=False),
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_utterances_meeting_id_start_ms",
        "utterances",
        ["meeting_id", "start_ms"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_utterances_meeting_id_start_ms", table_name="utterances"
    )
    op.drop_table("utterances")
