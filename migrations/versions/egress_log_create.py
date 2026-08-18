"""create egress_log table

Revision ID: egress_log
Revises: operator_voiceprints
Create Date: 2026-08-18

Records one row per outbound request through the audited egress chokepoint
(PRD NFR-2.7): which processor received it, a digest of the request body
(not the body itself, to avoid duplicating client content in the audit
trail), its size, and the processing region, so operators can prove what
left the perimeter and where it went.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "egress_log"
down_revision = "operator_voiceprints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "egress_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("processor_name", sa.String(length=128), nullable=False),
        sa.Column("request_digest", sa.String(length=128), nullable=False),
        sa.Column("byte_count", sa.BigInteger(), nullable=False),
        sa.Column("region", sa.String(length=64), nullable=False),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_egress_log_processor_name",
        "egress_log",
        ["processor_name"],
    )
    op.create_index(
        "ix_egress_log_sent_at",
        "egress_log",
        ["sent_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_egress_log_sent_at", table_name="egress_log")
    op.drop_index("ix_egress_log_processor_name", table_name="egress_log")
    op.drop_table("egress_log")
