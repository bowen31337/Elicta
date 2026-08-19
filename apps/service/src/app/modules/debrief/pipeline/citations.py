"""Binds every BMAD analyst claim to a citations-table row of utterance_id, timestamp, and speaker (PRD FR-8.7, FR-8.7a).

`run_bmad_analyst_chain` in `bmad_analyst.py` already resolves every claim's
citations into `ArtifactCitation`s grounded in the session's own
`ClassifiedUtterance`s, nested on the claim itself. This stage is the last
step: it flattens those nested citations into individual, durable
`CitationRow`s — the citations table PRD FR-8.7 asks for — and persists them
via an injected `save`, mirroring every other stage in this package: no
durable store exists yet in this codebase, so `SaveSessionCitationTable` is
supplied by whoever wires the app factory. Each row carries the citation's
`original_language` and `translated_text` straight through, so a row for a
cross-language claim persists both the original-language quote and its
translation (PRD FR-8.7a).

"A citation row persists for every claim" is an invariant `build_citation_rows`
enforces, not just documents: a claim whose `citations` list is empty — the
chain fabricated a claim it never actually grounded, or `resolve_citations`
was given nothing to resolve — fails the whole run instead of silently
persisting a citation table with a gap in it, the same fail-the-run-rather-
than-persist-partial-data reasoning `run_bmad_analyst_chain` uses for a
citation naming an unknown utterance_id.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from .models import (
    ArtifactCitation,
    BmadArtifactSet,
    CitationRow,
    CitationTableStatus,
    ClaimKind,
    SessionCitationTable,
)

SaveSessionCitationTable = Callable[[SessionCitationTable], Awaitable[None]]


def _rows_for_claim(
    session_id: str, claim_kind: ClaimKind, claim_index: int, citations: list[ArtifactCitation]
) -> list[CitationRow]:
    if not citations:
        raise ValueError(f"{claim_kind.value} at index {claim_index} has no citations to bind to a row")

    return [
        CitationRow(
            session_id=session_id,
            claim_kind=claim_kind,
            claim_index=claim_index,
            utterance_id=citation.utterance_id,
            start_seconds=citation.start_seconds,
            end_seconds=citation.end_seconds,
            speaker_tag=citation.speaker_tag,
            quoted_text=citation.quoted_text,
            original_language=citation.original_language,
            translated_text=citation.translated_text,
        )
        for citation in citations
    ]


def build_citation_rows(session_id: str, artifacts: BmadArtifactSet) -> list[CitationRow]:
    """Flatten every claim in `artifacts` into one `CitationRow` per grounded citation (PRD FR-8.7).

    Raises `ValueError` for any claim — an open question, a decision, the
    project brief, or the follow-up email — whose `citations` list is empty,
    since a citations table with a claim that has no row for it fails PRD
    FR-8.7's "a citation row persists for every claim" as surely as a citation
    naming an unknown utterance_id fails FR-2.7's grounding requirement.
    """

    rows: list[CitationRow] = []

    for index, question in enumerate(artifacts.open_questions):
        rows.extend(_rows_for_claim(session_id, ClaimKind.OPEN_QUESTION, index, question.citations))

    for index, decision in enumerate(artifacts.decisions):
        rows.extend(_rows_for_claim(session_id, ClaimKind.DECISION, index, decision.citations))

    rows.extend(_rows_for_claim(session_id, ClaimKind.PROJECT_BRIEF, 0, artifacts.project_brief.citations))
    rows.extend(_rows_for_claim(session_id, ClaimKind.FOLLOW_UP_EMAIL, 0, artifacts.follow_up_email.citations))

    return rows


async def persist_citation_table(
    session_id: str,
    artifacts: BmadArtifactSet,
    save: SaveSessionCitationTable,
    *,
    requested_at: datetime | None = None,
) -> SessionCitationTable:
    """Build every claim's citation rows and persist them as one `COMPLETE` citations table (PRD FR-8.7).

    On success, every claim in `artifacts` has contributed at least one
    `CitationRow` via `build_citation_rows`, and the whole run persists as one
    `COMPLETE` `SessionCitationTable`. If `build_citation_rows` raises — a
    claim with no citations to bind — this persists a `FAILED` record with no
    rows and re-raises nothing, same shape as `run_bmad_analyst_chain`'s
    failure handling, so a session that hasn't had its citations table built
    yet stays distinguishable from one whose build failed.
    """

    requested_at = requested_at or datetime.now(UTC)

    try:
        rows = build_citation_rows(session_id, artifacts)
    except Exception as exc:
        failed = SessionCitationTable(
            session_id=session_id,
            status=CitationTableStatus.FAILED,
            rows=[],
            requested_at=requested_at,
            completed_at=datetime.now(UTC),
            error=str(exc),
        )
        await save(failed)
        return failed

    result = SessionCitationTable(
        session_id=session_id,
        status=CitationTableStatus.COMPLETE,
        rows=rows,
        requested_at=requested_at,
        completed_at=datetime.now(UTC),
    )
    await save(result)
    return result
