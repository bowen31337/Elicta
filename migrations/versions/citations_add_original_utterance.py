"""add original_utterance_id to citations

Revision ID: citations_original_utterance
Revises: citations
Create Date: 2026-08-18

FR-2.19 requires the original-language utterance to be retained "permanently
and inseparably" alongside any translation, and FR-8.7a requires a
cross-language citation to carry both the original-language utterance and its
translation so the original can render on expand. `citations.utterance_id`
already binds every claim to a real utterance row (FR-8.7, `citations_create`
revision), and `translated_text` already carries the rendered translation —
but nothing in DDL previously stopped a row from having `translated_text` set
without also pointing at the specific utterance that translation came from.
`original_utterance_id` closes that gap: it is a second, explicit foreign key
to `utterances.id` that a translated citation must populate, and the
`ck_citations_translated_requires_original` check constraint makes "a
translated citation cannot exist without its original" a structural guarantee
(ADR-009) rather than something application code has to remember. It is
nullable at the column level — same-language citations never populate
`translated_text` and have no original to distinguish from `utterance_id` —
but the check constraint forbids the one combination FR-2.19/FR-8.7a rule
out: translated text with no original utterance recorded.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "citations_original_utterance"
down_revision = "citations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "citations",
        sa.Column(
            "original_utterance_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("utterances.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "ck_citations_translated_requires_original",
        "citations",
        "translated_text IS NULL OR original_utterance_id IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_citations_translated_requires_original",
        "citations",
        type_="check",
    )
    op.drop_column("citations", "original_utterance_id")
