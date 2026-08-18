"""create coverage_slots table

Revision ID: coverage_slots
Revises: artifacts
Create Date: 2026-08-18

Tracks, per meeting, how well each section of the requirements template has
been covered (PRD FR-6.5, FR-8.2): `meeting_id` is a foreign key rather than
a duplicated session identifier, since a coverage slot only ever exists in
the context of the one meeting whose live capture is filling it in.
`fill_state` records the section's coverage (e.g. empty/partial/filled) so
the coverage matrix artifact (FR-8.2) can render progress without
recomputing it from raw transcript data, and `citations` carries the
grounding references (PRD FR-8.7) that justify that fill state. `satisfied_at`
is included because FR-6.7 marks a slot satisfied when the operator taps the
"Asked it" chip, and that timestamp has to live on this table for the
suppression check to read.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "coverage_slots"
down_revision = "artifacts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "coverage_slots",
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
        sa.Column("template_section", sa.String(length=200), nullable=False),
        sa.Column(
            "fill_state",
            sa.String(length=20),
            nullable=False,
            server_default="empty",
        ),
        sa.Column(
            "citations",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("satisfied_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_coverage_slots_meeting_id_template_section",
        "coverage_slots",
        ["meeting_id", "template_section"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_coverage_slots_meeting_id_template_section",
        table_name="coverage_slots",
    )
    op.drop_table("coverage_slots")
