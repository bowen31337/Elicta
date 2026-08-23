"""create record_path_transcripts, session_alignments and audio_destruction_events

Revision ID: record_path_artifacts
Revises: consent_records
Create Date: 2026-08-23

The three artifacts the record path produces, and the last of the collections
that were classified as pipeline output "rebuilt from the transcript on demand"
without anything checking whether that was true of them.

It was not. Two of these *are* the transcript, and the third describes audio
that NFR-2.4 has already destroyed by the time the row is written — the raw
recording is discarded the moment transcription and diarization both finish, so
there is nothing left to re-derive them from. Losing them was not losing a
cache; it was losing the only surviving account of what was said in a meeting.

The three go together because they fail together. A session whose transcripts
are gone reports no alignment, because the alignment is computed from them, and
reports no destruction record, because that is keyed the same way — so all
three reads answer 404 at once and a meeting that really was recorded is
indistinguishable from one that never happened. The desktop service runs under
`uvicorn --reload`, which made "a restart" mean every file save, while the
meeting row itself survived in SQLite and made the loss look like a bug in the
reads rather than an absence of storage.

Conventions, and the departures from them:

No foreign key to `meetings` on any of the three, following `consent_records`.
The id is a *session* id, which both the record path and the live path key on,
and cascading a transcript away with a meeting row would destroy the account of
the meeting along with its row.

No `deleted_at` on any of the three, for the same reason `consent_records` has
none: soft delete exists so an operator can take something out of a list they
own, and none of these is in one. A transcript is not a list entry, and a
destruction record is the evidence for a privacy control rather than an item.

`segments` and `spans` are JSON rather than child tables. Each is produced
whole by one batch run and read whole by one screen; a row per segment would be
thousands of rows nothing ever queries individually. `sa.JSON` renders as
`JSONB` on PostgreSQL and `TEXT` on SQLite, which is what lets the same
revision run against the single-user SQLite file the desktop product ships.

The timestamps are ISO-8601 text rather than `DateTime`, the departure
`consent_records` records: every one of these values is `datetime.now(UTC)` and
SQLite's DateTime stores naive, so a round trip would drop the offset and read
back as an ambiguous local time.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "record_path_artifacts"
down_revision = "consent_records"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "record_path_transcripts",
        # `{session_id}:{ordinal}` — one session's transcripts are rewritten
        # whole, one per engine, so the pair is stable and unique.
        sa.Column("id", sa.String(length=128), primary_key=True),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("engine", sa.String(length=128), nullable=False),
        # `complete` or `failed`. A failed run is stored deliberately: a
        # session with no transcript cannot be told from an untranscribed one.
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("segments", sa.JSON(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column("requested_at", sa.String(length=64), nullable=False),
        sa.Column("completed_at", sa.String(length=64), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        # Which engine finished first: the first is the alignment's reference,
        # and the screen names it as such.
        sa.Column("ordinal", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "ix_record_path_transcripts_session_id",
        "record_path_transcripts",
        ["session_id"],
    )

    op.create_table(
        "session_alignments",
        # One row per session: the alignment is computed once, from the pair.
        sa.Column("session_id", sa.String(length=64), primary_key=True),
        sa.Column("reference_engine", sa.String(length=128), nullable=False),
        sa.Column("other_engine", sa.String(length=128), nullable=False),
        sa.Column("spans", sa.JSON(), nullable=False),
        sa.Column("computed_at", sa.String(length=64), nullable=False),
    )

    op.create_table(
        "audio_destruction_events",
        # `{session_id}:{ordinal}`, as above.
        sa.Column("id", sa.String(length=128), primary_key=True),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("audio_ref", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("requested_at", sa.String(length=64), nullable=False),
        sa.Column("completed_at", sa.String(length=64), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        # Attempt order for one session. A retry after a failure is what says
        # where the audio stands now, so which came last has to survive too.
        sa.Column("ordinal", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "ix_audio_destruction_events_session_id",
        "audio_destruction_events",
        ["session_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_audio_destruction_events_session_id",
        table_name="audio_destruction_events",
    )
    op.drop_table("audio_destruction_events")
    op.drop_table("session_alignments")
    op.drop_index(
        "ix_record_path_transcripts_session_id",
        table_name="record_path_transcripts",
    )
    op.drop_table("record_path_transcripts")
