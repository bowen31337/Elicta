"""create reference_documents table

Revision ID: reference_documents
Revises: vocabulary_terms
Create Date: 2026-08-18

Persists the source documents an engagement's requirements are grounded in
or hypothesized against (PRD FR-3.2, FR-3.4). `engagement_id` is a real
foreign key, mirroring `candidates.engagement_id` and
`vocabulary_terms.engagement_id`, since a reference document is only ever
uploaded for the one engagement it informs. `status` classifies how much
weight a document carries when the compiler or live detection cites it:
`ground_truth` for material the client has confirmed as authoritative,
`hypothesis` for material assumed correct until confirmed, and `superseded`
for material a later document has replaced — the `ck_reference_documents_status`
check constraint makes this the closed set FR-3.2/FR-3.4 require rather than
an application-level convention. `source_uri` records where the document's
original content lives so a citation can resolve back to it, and
`indexed_at` records when the document was last processed into the
retrieval index, mirroring `artifacts.generated_at` and `nudges.surfaced_at`
in marking the moment of an underlying pipeline step rather than row
creation.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "reference_documents"
down_revision = "vocabulary_terms"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reference_documents",
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
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("source_uri", sa.Text(), nullable=False),
        sa.Column(
            "indexed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_reference_documents_status",
        "reference_documents",
        "status IN ('ground_truth', 'hypothesis', 'superseded')",
    )
    op.create_index(
        "ix_reference_documents_engagement_id",
        "reference_documents",
        ["engagement_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_reference_documents_engagement_id",
        table_name="reference_documents",
    )
    op.drop_constraint(
        "ck_reference_documents_status",
        "reference_documents",
        type_="check",
    )
    op.drop_table("reference_documents")
