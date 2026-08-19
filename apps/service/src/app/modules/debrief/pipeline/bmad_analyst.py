"""Runs a BMAD Analyst chain over a session's full classified transcript and persists the artifact set (PRD FR-4.1, FR-8).

`run_bmad_analyst_chain` takes the chain itself as an injected callable
rather than importing the Claude Agent SDK directly, mirroring
`classification.py`'s `ClassifyUtterances` and `cleaning.py`'s
`CleanTranscript`: no durable store exists yet in this codebase, and this
package stays decoupled from any concrete vendor client. Whoever wires the
app factory supplies the real chain — built on the Claude Agent SDK per the
PRD — as `RunBmadAnalystChain`.

This is the last stage of the debrief pipeline: it runs over every
`ClassifiedUtterance` a session has (the full transcript, cleaned,
speaker-tagged, and mapped to the requirements template taxonomy), not a
subset of it, and is the stage that produces the artifacts an operator
actually reads — the open-questions list (FR-8.3), the decision and
commitment log (FR-8.4), the draft project brief (FR-8.5), and the draft
follow-up email (FR-8.6). "The chain creates the full artifact set" means
exactly that: a run that produced only some of these four is treated the
same as a run that raised, since a partial bundle is a vendor contract
violation this stage can't safely present as done.

Every claim the chain makes must trace back to the session's own classified
utterances (PRD FR-2.7, FR-8.7): `resolve_citations` looks each cited
`utterance_id` up in the session's `ClassifiedUtterance`s rather than
trusting whatever timestamp, speaker, or wording the chain itself reports
for a citation, and a citation naming an utterance the session doesn't have
fails the run the same way a mismatched section-key count fails
classification.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from .models import (
    ArtifactCitation,
    BmadAnalystChainOutput,
    BmadAnalystChainStatus,
    BmadArtifactSet,
    BmadDecisionDraft,
    BmadFollowUpEmailDraft,
    BmadOpenQuestionDraft,
    BmadProjectBriefDraft,
    ClaimProvenance,
    ClassifiedUtterance,
    DecisionLogEntry,
    FollowUpEmailDraft,
    OpenQuestion,
    ProjectBriefDraft,
    SessionBmadAnalystChain,
)

RunBmadAnalystChain = Callable[[str, list[ClassifiedUtterance]], Awaitable[BmadAnalystChainOutput]]
SaveSessionBmadAnalystChain = Callable[[SessionBmadAnalystChain], Awaitable[None]]


def normalize_provenance(raw: str) -> ClaimProvenance:
    """Return `STATED` only for the chain's exact stated marker, `INFERRED` for everything else.

    A chain output the caller didn't explicitly mark `"stated"` — an unknown
    value, a typo, a vendor response that omitted the field — falls back to
    `INFERRED` rather than being assumed heard, the same fail-safe-to-the-
    visible-flag reasoning `normalize_section_key` uses for an unrecognized
    section key (PRD FR-8.8).
    """

    return ClaimProvenance.STATED if raw == ClaimProvenance.STATED.value else ClaimProvenance.INFERRED


def resolve_citations(
    utterance_ids: list[str], utterances_by_id: dict[str, ClassifiedUtterance]
) -> list[ArtifactCitation]:
    """Build one `ArtifactCitation` per id, sourced from the session's own classified utterances (PRD FR-2.7, FR-8.7a).

    Raises `ValueError` for any id that isn't one of `utterances_by_id` — an
    artifact claim citing an utterance the session doesn't have would be
    indistinguishable from one the chain fabricated, which is exactly what
    grounding every field in the actual `ClassifiedUtterance` (rather than
    the chain's own account of the citation) exists to prevent. Each
    citation's `original_language` and `translated_text` are likewise copied
    straight off the utterance, so a claim grounded in a cross-language
    utterance carries both the original quote and its translation (PRD
    FR-8.7a).
    """

    citations = []
    for utterance_id in utterance_ids:
        utterance = utterances_by_id.get(utterance_id)
        if utterance is None:
            raise ValueError(f"chain cited unknown utterance_id {utterance_id!r}")
        citations.append(
            ArtifactCitation(
                utterance_id=utterance.utterance_id,
                session_id=utterance.session_id,
                start_seconds=utterance.start_seconds,
                end_seconds=utterance.end_seconds,
                speaker_tag=utterance.speaker_tag,
                quoted_text=utterance.verbatim_text,
                original_language=utterance.original_language,
                translated_text=utterance.translated_text,
            )
        )
    return citations


def _build_open_question(
    draft: BmadOpenQuestionDraft, utterances_by_id: dict[str, ClassifiedUtterance]
) -> OpenQuestion:
    return OpenQuestion(
        text=draft.text,
        impact_rank=draft.impact_rank,
        provenance=normalize_provenance(draft.provenance),
        citations=resolve_citations(draft.citation_utterance_ids, utterances_by_id),
    )


def _build_decision(
    draft: BmadDecisionDraft, utterances_by_id: dict[str, ClassifiedUtterance]
) -> DecisionLogEntry:
    return DecisionLogEntry(
        text=draft.text,
        decided_by=draft.decided_by,
        provenance=normalize_provenance(draft.provenance),
        citations=resolve_citations(draft.citation_utterance_ids, utterances_by_id),
    )


def _build_project_brief(
    draft: BmadProjectBriefDraft, utterances_by_id: dict[str, ClassifiedUtterance]
) -> ProjectBriefDraft:
    return ProjectBriefDraft(
        body=draft.body,
        provenance=normalize_provenance(draft.provenance),
        citations=resolve_citations(draft.citation_utterance_ids, utterances_by_id),
    )


def _build_follow_up_email(
    draft: BmadFollowUpEmailDraft, utterances_by_id: dict[str, ClassifiedUtterance]
) -> FollowUpEmailDraft:
    return FollowUpEmailDraft(
        subject=draft.subject,
        body=draft.body,
        provenance=normalize_provenance(draft.provenance),
        citations=resolve_citations(draft.citation_utterance_ids, utterances_by_id),
    )


async def run_bmad_analyst_chain(
    session_id: str,
    utterances: list[ClassifiedUtterance],
    engine: str,
    run_chain: RunBmadAnalystChain,
    save: SaveSessionBmadAnalystChain,
    *,
    requested_at: datetime | None = None,
) -> SessionBmadAnalystChain:
    """Run the BMAD analyst chain over `utterances` and persist the full artifact set (PRD FR-4.1, FR-8).

    On success, every citation in the chain's `BmadAnalystChainOutput` is
    resolved against `utterances` via `resolve_citations`, and the run
    persists as one `COMPLETE` `SessionBmadAnalystChain` carrying all four
    artifact categories — open questions, decisions, the project brief, and
    the follow-up email — as one `BmadArtifactSet`. If `run_chain` raises, or
    any citation names an utterance not in `utterances` (a vendor contract
    violation we can't safely ground), this persists a `FAILED` record with
    no artifacts and re-raises nothing — same shape as
    `run_section_classification`'s failure handling, so a session that
    hasn't had the chain run yet stays distinguishable from one whose run
    failed.
    """

    requested_at = requested_at or datetime.now(UTC)
    utterances_by_id = {utterance.utterance_id: utterance for utterance in utterances}

    try:
        output = await run_chain(session_id, utterances)
        artifacts = BmadArtifactSet(
            open_questions=[_build_open_question(draft, utterances_by_id) for draft in output.open_questions],
            decisions=[_build_decision(draft, utterances_by_id) for draft in output.decisions],
            project_brief=_build_project_brief(output.project_brief, utterances_by_id),
            follow_up_email=_build_follow_up_email(output.follow_up_email, utterances_by_id),
        )
    except Exception as exc:
        failed = SessionBmadAnalystChain(
            session_id=session_id,
            status=BmadAnalystChainStatus.FAILED,
            engine=engine,
            artifacts=None,
            requested_at=requested_at,
            completed_at=datetime.now(UTC),
            error=str(exc),
        )
        await save(failed)
        return failed

    result = SessionBmadAnalystChain(
        session_id=session_id,
        status=BmadAnalystChainStatus.COMPLETE,
        engine=engine,
        artifacts=artifacts,
        requested_at=requested_at,
        completed_at=datetime.now(UTC),
    )
    await save(result)
    return result
