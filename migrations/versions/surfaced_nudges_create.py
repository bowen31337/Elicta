"""create surfaced_nudges table

Revision ID: surfaced_nudges
Revises: meeting_soft_delete
Create Date: 2026-08-26

What the live panel actually surfaced in a meeting, and what became of it.

Distinct from `nudges`, which is the analysis pipeline's record and cannot
hold one of these: its `id` is a generated UUID where the live path issues
`nudge-1`, its `candidate_id` is NOT NULL where a templated nudge has none,
and its `trigger_event_id` is a NOT NULL foreign key into a chain the live
path never writes. Bending that table to fit would make one row mean two
different things depending on which half of the product wrote it.

Held in memory until now, with the reasoning that a nudge is a question
worth asking in the next thirty seconds and restoring a stale one would put
it in front of a client. That argues against *promoting* a restored nudge,
which is a panel decision, and not against remembering it: a restart lost
the meeting's whole history, and with it the operator's ability to reach any
question they had not dealt with yet. It also lost `raised_nudges`, so
`Park it` and `Go deeper` — which address a thread by id alone — answered
404 for every nudge raised before the restart.

`ordinal` is the order the meeting produced them in, so the stream replays
what the panel saw rather than whatever order rows return. `disposition` is
the operator's answer where they gave one, and is the part that outlives the
meeting whatever happens to the question.
"""

from alembic import op
import sqlalchemy as sa

revision = "surfaced_nudges"
down_revision = "meeting_soft_delete"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "surfaced_nudges",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "meeting_id",
            sa.String(length=64),
            sa.ForeignKey("meetings.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("stub", sa.Text(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("trigger_reason", sa.Text(), nullable=False),
        # What fired it. Nullable because a question the operator typed has
        # no trigger behind it — the escape hatch produces a real nudge.
        sa.Column("term", sa.Text(), nullable=True),
        sa.Column("category", sa.Text(), nullable=True),
        # Which bank candidate supplied it, or null where the wording was
        # templated because the bank had nothing for that trigger.
        sa.Column("candidate_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        # `taken` or `parked`, once the operator has said. Null until then,
        # which is a third state and not a default: a nudge nobody answered
        # is not a nudge that was ignored.
        sa.Column("disposition", sa.String(length=32), nullable=True),
        sa.Column("ordinal", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("surfaced_nudges")
