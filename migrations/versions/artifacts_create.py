"""create artifacts table

Revision ID: artifacts
Revises: meetings
Create Date: 2026-08-18

Persists the durable session-level artifacts the debrief pipeline produces
(PRD FR-8.1 through FR-8.6): the transcript, requirements coverage matrix,
open-questions list, decision/commitment log, draft project brief, and draft
follow-up email. One row per artifact per generation — `artifact_type`
distinguishes which of the six PRD FR-8.1-8.6 kinds a row holds rather than
splitting each kind into its own table, since every kind shares the same
shape: a session it belongs to, the language it was rendered in, its
content, and when it was generated. `artifact_language` is stored per row
rather than read live off the engagement, because PRD line "artifact
language is an explicit engagement setting" fixes it at generation time — an
engagement's setting changing later must not silently reattribute the
language of an artifact already produced. `session_id` mirrors
`open_questions.session_id` rather than a foreign key to `meetings`, keeping
this table scoped the same way the rest of the debrief pipeline's persisted
output already is.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "artifacts"
down_revision = "meetings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "artifacts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("artifact_type", sa.String(length=32), nullable=False),
        sa.Column("artifact_language", sa.String(length=16), nullable=False),
        sa.Column(
            "body",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_artifacts_session_id_artifact_type",
        "artifacts",
        ["session_id", "artifact_type"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_artifacts_session_id_artifact_type", table_name="artifacts"
    )
    op.drop_table("artifacts")
