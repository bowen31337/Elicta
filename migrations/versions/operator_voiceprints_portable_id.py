"""make operator_voiceprints portable across SQLite and PostgreSQL

Revision ID: voiceprints_portable
Revises: record_path_artifacts
Create Date: 2026-08-23

`operator_voiceprints` was created with a `postgresql.UUID` primary key
defaulting to `gen_random_uuid()`. SQLite is this system's default state store
and builds its schema from `metadata.create_all` rather than from this chain,
so that column type meant the two databases held the same table in two
different shapes — and only a deployment on PostgreSQL would ever discover it,
at the first enrolment.

The table is recreated rather than altered because SQLite cannot change a
column's type in place, and because there is nothing to preserve: no model, no
route and no code of any kind read or wrote this table between its creation and
this revision, so it has never held a row.

The id is now assigned by the application (`voiceprint-{operator_id}`), which
also makes re-enrolment the upsert the unique index always intended rather than
an insert that collides with it.
"""

import sqlalchemy as sa
from alembic import op

revision = "voiceprints_portable"
down_revision = "record_path_artifacts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_operator_voiceprints_operator_id", table_name="operator_voiceprints")
    op.drop_table("operator_voiceprints")
    op.create_table(
        "operator_voiceprints",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("operator_id", sa.String(length=128), nullable=False),
        sa.Column("embedding", sa.LargeBinary(), nullable=False),
        sa.Column("embedding_model", sa.String(length=64), nullable=False),
        sa.Column("sample_duration_ms", sa.Integer(), nullable=False),
        # Stored as text, like every other timestamp the durable collections
        # write: they go through the same JSON dump, which renders a datetime
        # as an ISO-8601 string.
        sa.Column("enrolled_at", sa.String(length=64), nullable=False),
    )
    op.create_index(
        "ix_operator_voiceprints_operator_id",
        "operator_voiceprints",
        ["operator_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_operator_voiceprints_operator_id", table_name="operator_voiceprints")
    op.drop_table("operator_voiceprints")
