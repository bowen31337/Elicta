"""create citations table

Revision ID: citations
Revises: utterances
Create Date: 2026-08-18

Binds every BMAD analyst claim to the utterance it was heard in (PRD FR-8.7):
"every requirement claim carries a timestamp and speaker citation", and the
architecture's citation-integrity invariant that this is "structurally
guaranteed rather than prompt-dependent" (ADR-009) means the guarantee has to
live in DDL, not in application code that could forget to set it. `utterance_id`
is therefore a foreign key to `utterances.id` with `nullable=False` and no
default — there is no way to insert a citation without pointing it at a real
utterance row. The remaining columns mirror `CitationRow` in
`debrief/pipeline/models.py`, the pydantic shape `build_citation_rows` already
produces one of per grounded citation: `session_id` scopes the row the same
way `open_questions.session_id`/`artifacts.session_id` do; `claim_kind` plus
`claim_index` identify which BMAD analyst artifact claim (an open question, a
decision, the project brief, or the follow-up email, and its position within
that category's list) the row grounds, since claims themselves have no table
of their own to key off; `start_seconds`/`end_seconds`/`speaker_tag`/
`quoted_text` are copied from the citation rather than re-derived by joining
`utterances` at read time, because `ArtifactCitation` already resolved them
once against the session's classified utterances and a citation must not
drift from what was actually cited. `translated_text` stays a plain nullable
column, not a second utterance foreign key, because FR-8.7a's translation is
rendered text carried alongside the original quote, not a second utterance
of its own.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "citations"
down_revision = "utterances"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "citations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("claim_kind", sa.String(length=32), nullable=False),
        sa.Column("claim_index", sa.Integer(), nullable=False),
        sa.Column(
            "utterance_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("utterances.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("start_seconds", sa.Float(), nullable=False),
        sa.Column("end_seconds", sa.Float(), nullable=False),
        sa.Column("speaker_tag", sa.String(length=64), nullable=False),
        sa.Column("quoted_text", sa.Text(), nullable=False),
        sa.Column("original_language", sa.String(length=16), nullable=False),
        sa.Column("translated_text", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_citations_session_id_claim_kind",
        "citations",
        ["session_id", "claim_kind"],
    )


def downgrade() -> None:
    op.drop_index("ix_citations_session_id_claim_kind", table_name="citations")
    op.drop_table("citations")
