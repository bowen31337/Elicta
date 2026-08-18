"""Builds the requirements coverage matrix artifact from a section-classification run (PRD FR-8.2).

`run_section_classification` already derives one `CoverageSlotState` per BMAD
taxonomy section for a single classification run (PRD FR-8.2).
`build_coverage_matrix` turns that run's result into the coverage matrix
artifact itself: one `CoverageMatrixEntry` per known section, in the same
taxonomy order as the classification run used, with every `FILLED` slot
grounded in a record-path citation (PRD FR-2.7/FR-8.7).

`cite` is injected rather than importing `asr-record`'s citation lookup
directly, mirroring every other vendor/cross-module boundary in this module
(`ClassifyUtterances`, `CleanTranscript`, `DiarizeAudio`): whoever wires the
app factory supplies an implementation that looks up the session's
`RecordPathTranscript` and calls `cite_record_path_span` on it, adapting the
result into a `CoverageCitation`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from app.modules.debrief.pipeline.models import (
    CoverageSlotState,
    FillState,
    SectionClassificationStatus,
    SessionSectionClassification,
)

from .models import CoverageCitation, CoverageMatrixEntry, CoverageMatrixStatus, RequirementsCoverageMatrix

CiteFilledSlot = Callable[[str, float, float], Awaitable[CoverageCitation]]
SaveCoverageMatrix = Callable[[RequirementsCoverageMatrix], Awaitable[None]]


def _slot_span(slot: CoverageSlotState, spans_by_utterance_id: dict[str, tuple[float, float]]) -> tuple[float, float]:
    spans = [spans_by_utterance_id[utterance_id] for utterance_id in slot.utterance_ids]
    return min(start for start, _ in spans), max(end for _, end in spans)


async def build_coverage_matrix(
    classification: SessionSectionClassification,
    cite: CiteFilledSlot,
    save: SaveCoverageMatrix,
    *,
    generated_at: datetime | None = None,
) -> RequirementsCoverageMatrix:
    """Build and persist the requirements coverage matrix for one classification run (PRD FR-8.2).

    Requires `classification` to be a `COMPLETE` `SessionSectionClassification`
    — a matrix built from a run that never classified anything would just show
    every slot `EMPTY`, indistinguishable from a session with nothing to say
    yet, so this persists a `FAILED` matrix carrying `classification.error`
    instead. On success, every `FILLED` slot in `classification.slots` is
    grounded with one `cite` call spanning the earliest start and latest end
    of the utterances that filled it; an `EMPTY` slot gets no citations, since
    there is nothing yet to cite. If `cite` raises for any filled slot, this
    persists a `FAILED` matrix rather than a partially grounded one — a
    coverage matrix silently missing a citation on one of its filled slots
    would be indistinguishable from one that was built correctly.
    """

    generated_at = generated_at or datetime.now(timezone.utc)

    if classification.status != SectionClassificationStatus.COMPLETE:
        failed = RequirementsCoverageMatrix(
            session_id=classification.session_id,
            status=CoverageMatrixStatus.FAILED,
            entries=[],
            is_fully_covered=False,
            generated_at=generated_at,
            error=classification.error or "section classification did not complete",
        )
        await save(failed)
        return failed

    spans_by_utterance_id = {
        utterance.utterance_id: (utterance.start_seconds, utterance.end_seconds)
        for utterance in classification.utterances
    }

    try:
        entries = []
        for slot in classification.slots:
            citations: list[CoverageCitation] = []
            if slot.fill_state == FillState.FILLED:
                start_seconds, end_seconds = _slot_span(slot, spans_by_utterance_id)
                citations = [await cite(classification.session_id, start_seconds, end_seconds)]
            entries.append(
                CoverageMatrixEntry(
                    section_key=slot.section_key,
                    title=slot.title,
                    fill_state=slot.fill_state,
                    utterance_ids=slot.utterance_ids,
                    citations=citations,
                )
            )
    except Exception as exc:
        failed = RequirementsCoverageMatrix(
            session_id=classification.session_id,
            status=CoverageMatrixStatus.FAILED,
            entries=[],
            is_fully_covered=False,
            generated_at=generated_at,
            error=str(exc),
        )
        await save(failed)
        return failed

    result = RequirementsCoverageMatrix(
        session_id=classification.session_id,
        status=CoverageMatrixStatus.COMPLETE,
        entries=entries,
        is_fully_covered=all(entry.fill_state == FillState.FILLED for entry in entries),
        generated_at=generated_at,
    )
    await save(result)
    return result
