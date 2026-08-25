"""SQLAlchemy models for the engagement-continuity tables.

These are the first ORM models in the service, and they exist to close a
specific gap: `migrations/versions/` described twenty tables that nothing in
the running product ever read or wrote, so engagement state lived only in
process memory and died with the service (PRD G4, FR-8.9).

Scope is deliberate. The tables here are the ones an engagement's memory is
made of — the client, its meetings, the questions a meeting left open, the
standing requirements state, the compiled candidate bank, the two things the
operator types in before any of it (the reference documents and the client
vocabulary), the consent confirmations, and what the record path produced. The
remaining tables hold per-run pipeline output that really is rebuilt from the
transcript on demand; they get their models when something needs to read them
back, not before, because an unused model is a schema claim nobody checks.

Five of the tables here arrived by being moved *out* of that "rebuilt on
demand" group, which for them quietly meant "lost on restart". Nothing rebuilds
a document somebody uploaded or a keyterm somebody typed — a live run came back
with zero of both against engagements that had them, with no warning, while the
screen still offered to add more. Nothing rebuilds a consent confirmation
either; it describes a moment. And nothing rebuilds the record path's
transcripts or the alignment computed from them, because NFR-2.4 destroys the
raw audio the moment transcription and diarization finish — by the time the
destruction event is written, the thing that could regenerate them is gone.

The lesson each time is the same, and worth applying before adding a model
here: "rebuilt on demand" is a claim about what would actually do the
rebuilding. If the answer is nothing, the classification is a way of saying the
data is lost and no one has noticed yet.

**Column types are portable on purpose.** The migration chain is written for
PostgreSQL (`JSONB`, `UUID`, `ARRAY`), which is the deployment target. But the
desktop product ships a single-user service with no database server, so the
same models have to run on SQLite. `sa.JSON` renders as `JSONB` on PostgreSQL
and as `TEXT` on SQLite, and `sa.String` covers the id columns — see the
`ids_to_text` revision for why the ids are text rather than `UUID`.
"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base whose `metadata` is what Alembic autogenerates against."""


class Engagement(Base):
    """One client engagement — the root every other row here hangs off."""

    __tablename__ = "engagements"

    id: Mapped[str] = mapped_column(sa.String(64), primary_key=True)
    client_name: Mapped[str] = mapped_column(sa.String(256), nullable=False, default="")
    sector: Mapped[str] = mapped_column(sa.String(128), nullable=False, default="")
    purpose: Mapped[str] = mapped_column(sa.Text(), nullable=False, default="")
    scope_boundary: Mapped[str] = mapped_column(sa.Text(), nullable=False, default="")
    template_id: Mapped[str] = mapped_column(sa.String(128), nullable=False, default="")
    artifact_language: Mapped[str] = mapped_column(sa.String(16), nullable=False, default="en")
    # PostgreSQL's ARRAY(String) in the migration; JSON here so one model runs
    # on both engines. Both store the same list of BCP-47 tags (FR-2.14).
    expected_languages: Mapped[list] = mapped_column(sa.JSON(), nullable=False, default=list)
    # FR-3.1 client background, which the migration predates: it is the input
    # to expected-language derivation, so losing it across a restart would
    # make the derivation unreproducible.
    commercial_context: Mapped[str] = mapped_column(sa.Text(), nullable=False, default="")
    # Soft delete: set, and the row stops being loaded. Marking rather than
    # erasing keeps a removal reversible, and leaves the harder question — what
    # a real erasure should also destroy — open rather than answered by
    # accident in a product that records client meetings.
    deleted_at: Mapped[datetime | None] = mapped_column(sa.DateTime(), nullable=True)


class Meeting(Base):
    """One meeting within an engagement."""

    __tablename__ = "meetings"

    id: Mapped[str] = mapped_column(sa.String(64), primary_key=True)
    engagement_id: Mapped[str] = mapped_column(
        sa.String(64),
        sa.ForeignKey("engagements.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    purpose: Mapped[str] = mapped_column(sa.Text(), nullable=False, default="")
    target_sections: Mapped[list] = mapped_column(sa.JSON(), nullable=False, default=list)
    scheduled_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    capture_mode: Mapped[str] = mapped_column(sa.String(16), nullable=False, default="monolingual")
    state: Mapped[str] = mapped_column(sa.String(16), nullable=False, default="scheduled")
    # The assembled read-model the meeting detail route answers with. Stored
    # whole because it aggregates attendees, coverage and nudge counts that
    # this table does not own, and re-deriving it on read would couple this
    # module to three others it deliberately does not import.
    detail: Mapped[dict | None] = mapped_column(sa.JSON(), nullable=True)
    # Soft delete, for the reason `Engagement.deleted_at` gives. A meeting is
    # the row a consent record, a transcript and an audio-destruction event all
    # point at, so "take it off the operator's list" and "erase the record that
    # this meeting happened" must not be the same button.
    deleted_at: Mapped[datetime | None] = mapped_column(sa.DateTime(), nullable=True)


class OpenQuestion(Base):
    """A question a meeting ended without an answer to (FR-4.8, FR-8.3).

    Engagement-scoped rather than meeting-scoped: the point of the row is that
    it outlives the meeting that raised it and shapes the next meeting's bank.
    """

    __tablename__ = "open_questions"

    id: Mapped[int] = mapped_column(sa.Integer(), primary_key=True, autoincrement=True)
    engagement_id: Mapped[str] = mapped_column(
        sa.String(64),
        sa.ForeignKey("engagements.id", ondelete="CASCADE"),
        nullable=False,
    )
    text: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    impact_rank: Mapped[int] = mapped_column(sa.Integer(), nullable=False)

    __table_args__ = (
        sa.Index("ix_open_questions_engagement_id_impact_rank", "engagement_id", "impact_rank"),
    )


class RequirementsStateRow(Base):
    """The standing requirements state carried across an engagement (FR-8.9).

    One row per engagement, upserted whenever a meeting's debrief completes.
    """

    __tablename__ = "requirements_state"

    engagement_id: Mapped[str] = mapped_column(
        sa.String(64),
        sa.ForeignKey("engagements.id", ondelete="CASCADE"),
        primary_key=True,
    )
    confirmed_requirements: Mapped[list] = mapped_column(sa.JSON(), nullable=False, default=list)
    contradictions: Mapped[list] = mapped_column(sa.JSON(), nullable=False, default=list)
    decisions: Mapped[list] = mapped_column(sa.JSON(), nullable=False, default=list)
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )


class Candidate(Base):
    """One compiled candidate question in an engagement's bank (FR-4.8)."""

    __tablename__ = "candidates"

    id: Mapped[str] = mapped_column(sa.String(64), primary_key=True)
    engagement_id: Mapped[str] = mapped_column(
        sa.String(64),
        sa.ForeignKey("engagements.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    template_section: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    phrasing: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    priority: Mapped[int] = mapped_column(sa.Integer(), nullable=False)
    inherited_from_open_question: Mapped[bool] = mapped_column(
        sa.Boolean(), nullable=False, default=False
    )
    # The operator's judgement about the question, and the reason they read
    # the bank at all. Held only in memory it came back undone on every
    # restart, and it is promised to hold for every later meeting too.
    pruned: Mapped[bool] = mapped_column(
        sa.Boolean(), nullable=False, default=False, server_default=sa.false()
    )
    # Which document this question was drafted from, and the document
    # statuses it rests on. Nullable and empty respectively, because the
    # Analyst also reasons questions out of the engagement rather than off a
    # page — and *that* is the operator's signal that a bank is inference
    # rather than evidence, so it has to reload as absence rather than as a
    # value that went missing.
    # Typed to match `candidates_create` exactly — `Text` and a *nullable*
    # JSON column. The chain has carried both since that revision; only the
    # model and the wire type dropped them. The drift guard compares column
    # names, so a type or a nullability that disagreed with the chain would
    # pass it and fail on PostgreSQL, which is the failure the guard exists
    # to prevent in its other half.
    source_doc: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    authority_match: Mapped[list | None] = mapped_column(sa.JSON(), nullable=True)
    # Position within the engagement's bank, so the list reads back in the
    # order it was compiled in rather than in whatever order the rows return.
    ordinal: Mapped[int] = mapped_column(sa.Integer(), nullable=False, default=0)


metadata = Base.metadata


class ReferenceDocumentRow(Base):
    """One document attached to an engagement, and the text read out of it.

    `name` and `extracted_text` are not in the `reference_documents` migration,
    which predates both: the list an operator reads is keyed on the name, and
    the compiler reads the text, so a row carrying neither would restore a
    document that exists and says nothing. `source_uri` is empty for an upload
    and carries the link for an attachment, which is how the two intake paths
    stay one list (FR-3.2).
    """

    __tablename__ = "reference_documents"

    id: Mapped[str] = mapped_column(sa.String(64), primary_key=True)
    engagement_id: Mapped[str] = mapped_column(
        sa.String(64), sa.ForeignKey("engagements.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(sa.String(512), nullable=False, default="")
    status: Mapped[str] = mapped_column(sa.String(32), nullable=False, default="hypothesis")
    source_uri: Mapped[str] = mapped_column(sa.Text(), nullable=False, default="")
    extracted_text: Mapped[str] = mapped_column(sa.Text(), nullable=False, default="")
    ordinal: Mapped[int] = mapped_column(sa.Integer(), nullable=False, default=0)
    deleted_at: Mapped[datetime | None] = mapped_column(sa.DateTime(), nullable=True)


class ConsentRecordRow(Base):
    """One confirmation that consent was disclosed and given for a meeting.

    The legally significant row in this schema, and the last one to get a
    table: `ConsentRecord` has said "durable proof" since it was written, and
    the records lived in a plain list on `Backend` with nothing behind it. A
    restart lost them, which meant the answer to "did we have permission for
    this?" was as durable as the process — and unlike a document or a
    vocabulary term, a consent confirmation cannot be retyped from a source,
    because it describes a moment rather than a fact about the engagement.

    Two deliberate absences. There is **no foreign key** to `meetings`: this is
    an audit record *about* a meeting id, and cascading it away with the row it
    describes would delete the evidence along with the subject. And there is
    **no `deleted_at`**, alone among the tables here — the soft-delete
    convention exists so an operator can take something out of a list, and a
    record of who took responsibility for recording a client is not theirs to
    withdraw.
    """

    __tablename__ = "consent_records"

    # `{meeting_id}:{ordinal}` — the list for one meeting is rewritten whole,
    # so the ordinal is stable within a rewrite and the pair is unique.
    id: Mapped[str] = mapped_column(sa.String(128), primary_key=True)
    meeting_id: Mapped[str] = mapped_column(sa.String(64), nullable=False, index=True)
    confirmed_by: Mapped[str] = mapped_column(sa.String(512), nullable=False)
    # ISO-8601 text, not `DateTime`, alone among the timestamps here. The
    # value is `datetime.now(UTC)` — timezone-aware — and SQLite's DateTime
    # stores naive, so a round trip would silently drop the offset from a
    # legally significant instant and read back as an ambiguous local time.
    # Text is exact on every backend the deployment might use.
    confirmed_at: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    # Append order within a meeting. A re-confirmation after a late arrival is
    # the one that describes the meeting as recorded, so which came last has
    # to survive the restart too.
    ordinal: Mapped[int] = mapped_column(sa.Integer(), nullable=False, default=0)


class VocabularyTermRow(Base):
    """One client word the transcriber is told about (FR-2.9, FR-3.6).

    The single most consequential thing an operator types here, by the
    product's own account: a misheard product name reads as something brand new
    and fires a trigger about nothing. Losing the list on restart meant the
    meeting ran without it and nothing said so.
    """

    __tablename__ = "vocabulary_terms"

    id: Mapped[str] = mapped_column(sa.String(64), primary_key=True)
    engagement_id: Mapped[str] = mapped_column(
        sa.String(64), sa.ForeignKey("engagements.id", ondelete="CASCADE"), nullable=False
    )
    term: Mapped[str] = mapped_column(sa.String(256), nullable=False)
    term_type: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    pronunciation_hint: Mapped[str | None] = mapped_column(sa.String(256), nullable=True)
    ordinal: Mapped[int] = mapped_column(sa.Integer(), nullable=False, default=0)
    deleted_at: Mapped[datetime | None] = mapped_column(sa.DateTime(), nullable=True)


class RecordPathTranscriptRow(Base):
    """One engine's full-session transcript for one session (FR-2.5/2.6).

    The third arrival into this schema from the "rebuilt on demand" group at
    the top of this file, and the one where that description was furthest from
    true. A record-path transcript is not derived from anything still on the
    machine: NFR-2.4 destroys the raw audio the moment transcription and
    diarization both finish, so once this row is gone the recording it came
    from is gone with it and no amount of re-running rebuilds it.

    Losing it took the two reads above it down as well — a session with no
    transcript reports no alignment and no destruction record, so a meeting
    that really was recorded came back looking exactly like one that never
    happened. The desktop service runs under `--reload`, which made that every
    file save.

    No foreign key to `meetings`, for the reason `ConsentRecordRow` gives: the
    id here is a *session* id, which the record path and the live path both
    key on, and cascading a transcript away with a meeting row would destroy
    the only surviving account of what was said.

    `segments` is JSON rather than a child table. The list is produced whole by
    one batch run and read whole by the screen; a row per segment would be
    thousands of rows nothing ever queries individually.
    """

    __tablename__ = "record_path_transcripts"

    # `{session_id}:{ordinal}` — one session's transcripts are rewritten whole
    # (one per engine), so the pair is stable and unique without a sequence.
    id: Mapped[str] = mapped_column(sa.String(128), primary_key=True)
    session_id: Mapped[str] = mapped_column(sa.String(64), nullable=False, index=True)
    engine: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    # `complete` or `failed`. A failed run is persisted deliberately: a session
    # with no transcript at all cannot be told from one nobody has transcribed.
    status: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    segments: Mapped[list] = mapped_column(sa.JSON(), nullable=False, default=list)
    text: Mapped[str] = mapped_column(sa.Text(), nullable=False, default="")
    # ISO-8601 text, not `DateTime`, for the reason `ConsentRecordRow` records:
    # these are `datetime.now(UTC)` and SQLite's DateTime stores naive, so a
    # round trip would drop the offset and read back as ambiguous local time.
    requested_at: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    completed_at: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    error: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    # Which engine finished first, kept because the first is the alignment's
    # reference and the screen names it as such.
    ordinal: Mapped[int] = mapped_column(sa.Integer(), nullable=False, default=0)


class SessionAlignmentRow(Base):
    """What comparing one session's two transcripts found (FR-2.6/2.8).

    One row per session — the alignment is computed once both engines finish,
    and recomputing it is only possible while both transcripts still exist.
    They are in the table above for the same reason, so the pair stands or
    falls together.

    `spans` is JSON on the same reasoning as `segments`: produced whole,
    read whole, never queried span by span.
    """

    __tablename__ = "session_alignments"

    session_id: Mapped[str] = mapped_column(sa.String(64), primary_key=True)
    reference_engine: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    other_engine: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    spans: Mapped[list] = mapped_column(sa.JSON(), nullable=False, default=list)
    computed_at: Mapped[str] = mapped_column(sa.String(64), nullable=False)


class AudioDestructionEventRow(Base):
    """That a session's raw audio was destroyed, and whether it worked (NFR-2.4).

    The privacy control's own evidence. A failed attempt matters more than a
    successful one — it means the audio may still be sitting there — so both
    are persisted, and losing them on restart lost the ability to tell a
    session whose audio was destroyed from one whose audio was never held.

    Every attempt is kept rather than only the latest: a retry after a failure
    describes where the audio stands now, and the pair together describe what
    happened. No foreign key, and no `deleted_at`, for the reasons
    `ConsentRecordRow` sets out — this is a record *about* a session id, and
    nothing about it is an operator's to withdraw.
    """

    __tablename__ = "audio_destruction_events"

    # `{session_id}:{ordinal}`, as above.
    id: Mapped[str] = mapped_column(sa.String(128), primary_key=True)
    session_id: Mapped[str] = mapped_column(sa.String(64), nullable=False, index=True)
    audio_ref: Mapped[str] = mapped_column(sa.String(512), nullable=False, default="")
    status: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    requested_at: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    completed_at: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    error: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    # Attempt order for one session. Which came last is the answer to "where
    # does the audio stand now", so it has to survive the restart too.
    ordinal: Mapped[int] = mapped_column(sa.Integer(), nullable=False, default=0)


class OperatorVoiceprintRow(Base):
    """The operator's enrolled voice sample, as an embedding (FR-1.5).

    One row per operator — re-enrolling replaces it rather than adding another,
    which is what the unique index on `operator_id` enforces. Durable for the
    plainest of the reasons in this file: nothing rebuilds it. A voiceprint is
    not derived from a transcript or a document or anything else still on the
    machine; the only thing that produces one is a person recording themselves
    for a minute, and losing it on restart means asking them to do it again
    without saying why.

    `embedding` holds the vector, never the audio it came from. FR-1.7 forbids
    raw audio reaching persistent storage, and a fixed-width embedding is the
    reason this table can exist at all — it is 96 bytes whether the sample was
    three seconds or sixty, so it cannot become a recording by accident.

    The id is a plain string assigned by the application rather than the
    `postgresql.UUID` with a `gen_random_uuid()` default that this table's
    first revision declared. SQLite is the default state store and takes its
    schema from `metadata.create_all` rather than from Alembic, so a
    PostgreSQL-only column type here would mean the two databases disagreed
    about the shape of the same table — and only the deployment on PostgreSQL
    would ever find out.
    """

    __tablename__ = "operator_voiceprints"

    id: Mapped[str] = mapped_column(sa.String(64), primary_key=True)
    operator_id: Mapped[str] = mapped_column(sa.String(128), nullable=False, unique=True)
    embedding: Mapped[bytes] = mapped_column(sa.LargeBinary(), nullable=False)
    #: Which embedder produced the bytes. Verification refuses to compare a
    #: print stamped with a model it is not running, because scoring one
    #: embedder's vector against another's returns a number that looks like a
    #: similarity and means nothing.
    embedding_model: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    sample_duration_ms: Mapped[int] = mapped_column(sa.Integer(), nullable=False)
    enrolled_at: Mapped[str] = mapped_column(sa.String(64), nullable=False)
