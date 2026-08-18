"""create vocabulary_terms table

Revision ID: vocabulary_terms
Revises: candidates
Create Date: 2026-08-18

Holds the client vocabulary captured per engagement (PRD FR-3.6) so live
detection can recognize client-specific terminology instead of flagging it
as an undefined or ambiguous term (FR-2.9). `term` is the vocabulary entry
itself, `term_type` classifies it (e.g. acronym, product name, internal
jargon) so the detection and glossary paths can treat categories
differently, and `pronunciation_hint` carries an optional phonetic spelling
for terms that ASR is prone to mishear. `engagement_id` is a foreign key
mirroring `candidates.engagement_id`, since a client's vocabulary is scoped
to the one engagement it was captured for.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "vocabulary_terms"
down_revision = "candidates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vocabulary_terms",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "engagement_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("engagements.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("term", sa.String(length=256), nullable=False),
        sa.Column("term_type", sa.String(length=64), nullable=False),
        sa.Column("pronunciation_hint", sa.String(length=256), nullable=True),
    )
    op.create_index(
        "ix_vocabulary_terms_engagement_id",
        "vocabulary_terms",
        ["engagement_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_vocabulary_terms_engagement_id", table_name="vocabulary_terms"
    )
    op.drop_table("vocabulary_terms")
