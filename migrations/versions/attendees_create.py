"""create attendees table

Revision ID: attendees
Revises: utterance_tokens
Create Date: 2026-08-18

Records who attends a meeting and how they map onto the stakeholder
landscape (PRD FR-3.10): `role`, `business_function`, `decision_authority`,
and `domain_expertise` are each structured columns so the analyst chain and
candidate scoring (PRD FR-4.7) can query and filter attendees consistently,
rather than parsing a free-text write-up. There is deliberately no free-text
assessment column here — FR-3.10 requires the stakeholder read to live in
these structured fields, not in a prose summary that would drift out of
sync with them. `domain_expertise` is JSONB rather than a scalar column
since an attendee can carry more than one area of expertise. `meeting_id` is
a foreign key rather than a duplicated engagement reference, mirroring how
`meetings.engagement_id` already scopes meeting rows to their parent, since
an attendee only ever exists in the context of the one meeting they
attended.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "attendees"
down_revision = "utterance_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "attendees",
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
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("role", sa.String(length=120), nullable=True),
        sa.Column("business_function", sa.String(length=120), nullable=True),
        sa.Column("decision_authority", sa.String(length=60), nullable=True),
        sa.Column(
            "domain_expertise",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_attendees_meeting_id",
        "attendees",
        ["meeting_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_attendees_meeting_id", table_name="attendees")
    op.drop_table("attendees")
