"""Give the reference-document and vocabulary tables what the product reads.

`reference_documents` and `vocabulary_terms` were created early and never read
by anything: documents and keyterms lived in process memory, so a restart lost
them while the screen went on offering to add more. Binding them to the running
product needs three columns the original revisions had no reason to include —
the name an operator's list is keyed on, the text a compile reads, and the
order things were added in.

`ordinal` on both, because the lists are shown in the order they were typed and
a set of rows has no order of its own.

Revision ID: document_and_vocabulary_continuity
Revises: continuity_bind
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "document_and_vocabulary_continuity"
down_revision = "continuity_bind"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "reference_documents",
        sa.Column("name", sa.String(length=512), nullable=False, server_default=""),
    )
    op.add_column(
        "reference_documents",
        sa.Column("extracted_text", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "reference_documents",
        sa.Column("ordinal", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "vocabulary_terms",
        sa.Column("ordinal", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("vocabulary_terms", "ordinal")
    op.drop_column("reference_documents", "ordinal")
    op.drop_column("reference_documents", "extracted_text")
    op.drop_column("reference_documents", "name")
