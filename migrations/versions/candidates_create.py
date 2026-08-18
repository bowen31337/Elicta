"""create candidates table

Revision ID: candidates
Revises: attendees
Create Date: 2026-08-18

Persists the compiled question bank (architecture section 3.6): the set of
candidate nudge questions assembled per engagement that the fast-lane
ranking function (section 3.7) scores and the hot path instantiates without
a model call. `template_section` ties a candidate back to the requirements
template slot it targets, `trigger_types` records which deterministic or
model-path triggers (FR-5.2-5.6) a candidate is eligible to answer, and
`phrasing` carries the `{slot}`-interpolated question text the hot path
fills in from `TriggerEvent.span` and the attendee roster, with `stub` as
its 3-5 word glanceable form. `lang` is the meeting language a given
phrasing renders in (FR-2.24) — independent of the operator's own language,
so a bank compiled for a mixed-language engagement holds more than one
phrasing per underlying question. `priority` and `requires` (prerequisite
candidate ids) feed section 3.7's scoring and prerequisite filter directly.
`authority_match` stores which roles can answer a candidate, mirroring
`attendees.domain_expertise`'s JSONB-array shape since more than one role
can qualify. `source_doc` carries the citation location for hypothesis-
derived candidates that section 3.11 populates from the compiler's native
citations rather than a bare filename. `embedding` is the vector this bank
is indexed by for retrieval and is stored as `LargeBinary`, matching the
blob convention already established by `operator_voiceprints.embedding`.
`engagement_id` is a real foreign key rather than an opaque string, because
unlike `nudges.candidate_id` (which names an identifier generated and
scored entirely within the live path with no table of its own), engagements
already exist as a row in this schema before their bank is compiled.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "candidates"
down_revision = "attendees"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "candidates",
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
        sa.Column("template_section", sa.String(length=128), nullable=False),
        sa.Column(
            "trigger_types",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("phrasing", sa.Text(), nullable=False),
        sa.Column("stub", sa.String(length=64), nullable=False),
        sa.Column("lang", sa.String(length=16), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column(
            "requires",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "authority_match",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("source_doc", sa.Text(), nullable=True),
        sa.Column("embedding", sa.LargeBinary(), nullable=False),
    )
    op.create_index(
        "ix_candidates_engagement_id",
        "candidates",
        ["engagement_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_candidates_engagement_id", table_name="candidates")
    op.drop_table("candidates")
