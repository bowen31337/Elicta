"""SQLAlchemy models for the engagement-continuity tables.

These are the first ORM models in the service, and they exist to close a
specific gap: `migrations/versions/` described twenty tables that nothing in
the running product ever read or wrote, so engagement state lived only in
process memory and died with the service (PRD G4, FR-8.9).

Scope is deliberate. The seven tables here are exactly the ones an engagement's
memory is made of — the client, its meetings, the questions a meeting left
open, the standing requirements state, the compiled candidate bank, and the two
things the operator types in before any of it: the reference documents and the
client vocabulary. The remaining thirteen tables hold per-run pipeline output
that is rebuilt from the transcript on demand; they get their models when
something needs to read them back, not before, because an unused model is a
schema claim nobody checks.

The last two were in that "rebuilt on demand" group and should never have been.
Nothing rebuilds a document somebody uploaded or a keyterm somebody typed, so
the classification quietly meant "lost on restart" — a live run came back with
zero documents and zero vocabulary against engagements that had both, with no
warning, while the screen still offered to add more.

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
