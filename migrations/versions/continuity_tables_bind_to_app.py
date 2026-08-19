"""reconcile the continuity tables with what the product actually stores

Revision ID: continuity_bind
Revises: reference_documents
Create Date: 2026-08-19

The twenty revisions before this one described a schema that nothing read or
wrote: engagement state lived in process memory and died with the service.
`app/persistence/` now binds five of those tables to the running product, and
binding them exposed three places where the described schema and the shipped
product disagreed. This revision settles each disagreement in favour of the
product, because the product's behaviour is observable and the schema's was
not.

**Identifiers are text, not UUIDs.** Every id the service mints is a readable
`eng-1` / `meeting-3` string, and those ids are already in the HTTP contract
and the desktop client. Changing the product to emit UUIDs would break both to
satisfy a column type no row had ever occupied, so the columns change instead.

**`engagements.commercial_context`** holds the FR-3.1 client background. It is
the input to expected-language derivation (FR-2.14), so an engagement that
lost it across a restart could not reproduce its own language set.

**`meetings.detail`** stores the assembled meeting read-model. It aggregates
attendees, coverage and nudge counts from tables this row does not own; the
alternative — re-deriving it on every read — would couple the meetings module
to three others it deliberately does not import.

`open_questions` is re-scoped from `session_id` to `engagement_id` for the
same reason its own docstring gives for existing: the point of the row is that
it outlives the meeting that raised it (FR-4.8).
"""

from alembic import op
import sqlalchemy as sa

revision = "continuity_bind"
down_revision = "reference_documents"
branch_labels = None
depends_on = None

# (table, column) pairs whose UUID type becomes text.
UUID_COLUMNS = [
    ("engagements", "id"),
    ("meetings", "id"),
    ("meetings", "engagement_id"),
    ("requirements_state", "engagement_id"),
    ("candidates", "id"),
    ("candidates", "engagement_id"),
    ("open_questions", "id"),
]


def upgrade() -> None:
    for table, column in UUID_COLUMNS:
        op.alter_column(
            table,
            column,
            type_=sa.String(length=64),
            existing_nullable=False,
            postgresql_using=f"{column}::text",
            server_default=None,
        )

    op.add_column(
        "engagements",
        sa.Column("commercial_context", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column("meetings", sa.Column("detail", sa.JSON(), nullable=True))

    # An open question belongs to the engagement it stays open across, not to
    # the one session that happened to raise it.
    op.drop_index("ix_open_questions_session_id_impact_rank", table_name="open_questions")
    op.alter_column(
        "open_questions",
        "session_id",
        new_column_name="engagement_id",
        type_=sa.String(length=64),
        existing_nullable=False,
    )
    op.create_index(
        "ix_open_questions_engagement_id_impact_rank",
        "open_questions",
        ["engagement_id", "impact_rank"],
    )

    # `ordinal` keeps a compiled bank in the order it was compiled in;
    # `inherited_from_open_question` is FR-4.8's "carried forward from last
    # time" flag, which a caller renders differently from a fresh candidate.
    op.add_column(
        "candidates",
        sa.Column("ordinal", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "candidates",
        sa.Column(
            "inherited_from_open_question",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("candidates", "inherited_from_open_question")
    op.drop_column("candidates", "ordinal")

    op.drop_index(
        "ix_open_questions_engagement_id_impact_rank", table_name="open_questions"
    )
    op.alter_column(
        "open_questions",
        "engagement_id",
        new_column_name="session_id",
        type_=sa.String(length=64),
        existing_nullable=False,
    )
    op.create_index(
        "ix_open_questions_session_id_impact_rank",
        "open_questions",
        ["session_id", "impact_rank"],
    )

    op.drop_column("meetings", "detail")
    op.drop_column("engagements", "commercial_context")

    for table, column in reversed(UUID_COLUMNS):
        op.alter_column(
            table,
            column,
            type_=sa.dialects.postgresql.UUID(as_uuid=True),
            existing_nullable=False,
            postgresql_using=f"{column}::uuid",
        )
