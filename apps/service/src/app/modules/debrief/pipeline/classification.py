"""Classifies every cleaned utterance to a template section and derives each coverage slot's fill_state (PRD FR-8.2).

`run_section_classification` takes the classification pass itself as an
injected callable rather than importing a concrete NLP/LLM vendor client
directly, mirroring `cleaning.py`'s `CleanTranscript` and `service.py`'s
`DiarizeAudio`: the vendor is still an open decision, and no durable store
exists yet in this codebase. The template taxonomy itself (`TemplateSection`s)
is likewise supplied by the caller rather than hardcoded — which taxonomy to
use (BMAD PRD sections as-is, or an internal variant) is its own open
decision (PRD D5).

This stage runs after transcript cleaning: it classifies `CleanedUtterance`s,
not raw diarized `Utterance`s, so the classifier reasons over the same
punctuated, disfluency-free text an operator or later BMAD analyst chain
would read, while `verbatim_text` still rides along on every
`ClassifiedUtterance` for citation purposes (PRD FR-2.7).

`compute_slot_fill_states` is the coverage-decision counterpart to
`tag_span_speaker` in `diarization.py`: a pure function, independent of the
classification engine, that folds a run's classified utterances into one
`CoverageSlotState` per known `TemplateSection` — `FILLED` once at least one
utterance landed in that section, `EMPTY` otherwise. Utterances the
classifier couldn't map to any known section (`UNCLASSIFIED_SECTION_KEY`)
don't count toward any slot's fill_state, the same way an unmatched
diarization turn doesn't get its own speaker slot.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from .models import (
    UNCLASSIFIED_SECTION_KEY,
    ClassifiedUtterance,
    CleanedUtterance,
    CoverageSlotState,
    FillState,
    SectionClassificationStatus,
    SessionSectionClassification,
    TemplateSection,
)

ClassifyUtterances = Callable[[str, list[CleanedUtterance], list[TemplateSection]], Awaitable[list[str]]]
SaveSessionSectionClassification = Callable[[SessionSectionClassification], Awaitable[None]]


def normalize_section_key(section_key: str, known_keys: set[str]) -> str:
    """Return `section_key` if it names a known `TemplateSection`, else `UNCLASSIFIED_SECTION_KEY`.

    A classifier that returns a key outside the supplied taxonomy (a vendor
    hallucination, a stale key from a prior taxonomy version) must not be
    allowed to silently mint a coverage slot that was never defined — folding
    it to `UNCLASSIFIED_SECTION_KEY` keeps every `ClassifiedUtterance.section_key`
    non-null while keeping the coverage matrix limited to slots the caller
    actually asked about.
    """

    return section_key if section_key in known_keys else UNCLASSIFIED_SECTION_KEY


def compute_slot_fill_states(
    slots: list[TemplateSection], utterances: list[ClassifiedUtterance]
) -> list[CoverageSlotState]:
    """Derive one `CoverageSlotState` per `TemplateSection`, in the same order as `slots`.

    A slot is `FILLED` once at least one utterance in `utterances` carries its
    `section_key`, and `EMPTY` otherwise. Utterances tagged
    `UNCLASSIFIED_SECTION_KEY` never fill a slot, since that key never names
    one of `slots`.
    """

    utterance_ids_by_section: dict[str, list[str]] = {}
    for utterance in utterances:
        utterance_ids_by_section.setdefault(utterance.section_key, []).append(utterance.utterance_id)

    return [
        CoverageSlotState(
            section_key=slot.key,
            title=slot.title,
            fill_state=FillState.FILLED if utterance_ids_by_section.get(slot.key) else FillState.EMPTY,
            utterance_ids=utterance_ids_by_section.get(slot.key, []),
        )
        for slot in slots
    ]


async def run_section_classification(
    session_id: str,
    utterances: list[CleanedUtterance],
    slots: list[TemplateSection],
    engine: str,
    classify: ClassifyUtterances,
    save: SaveSessionSectionClassification,
    *,
    requested_at: datetime | None = None,
) -> SessionSectionClassification:
    """Classify every utterance to a template section and persist each coverage slot's fill_state (PRD FR-8.2).

    On success, every utterance in `utterances` becomes a `ClassifiedUtterance`
    carrying the `section_key` `classify` returned for it (normalized against
    `slots` via `normalize_section_key`), and `compute_slot_fill_states`
    derives one `CoverageSlotState` per known section from the result. The
    whole run then persists as one `COMPLETE` `SessionSectionClassification`.
    If `classify` raises, or returns a different number of section keys than
    utterances given to it (a vendor contract violation we can't safely pair
    up), this persists a `FAILED` record with no utterances or slots and
    re-raises nothing — same shape as `run_transcript_cleaning`'s failure
    handling, so a session that hasn't been classified yet stays
    distinguishable from one whose classification run failed.
    """

    requested_at = requested_at or datetime.now(timezone.utc)
    known_keys = {slot.key for slot in slots}

    try:
        section_keys = await classify(session_id, utterances, slots)
        if len(section_keys) != len(utterances):
            raise ValueError(
                f"classify() returned {len(section_keys)} section keys for {len(utterances)} utterances"
            )
        classified_utterances = [
            ClassifiedUtterance(
                utterance_id=utterance.utterance_id,
                session_id=session_id,
                start_seconds=utterance.start_seconds,
                end_seconds=utterance.end_seconds,
                speaker_tag=utterance.speaker_tag,
                verbatim_text=utterance.verbatim_text,
                cleaned_text=utterance.cleaned_text,
                section_key=normalize_section_key(section_key, known_keys),
            )
            for utterance, section_key in zip(utterances, section_keys, strict=True)
        ]
    except Exception as exc:
        failed = SessionSectionClassification(
            session_id=session_id,
            status=SectionClassificationStatus.FAILED,
            engine=engine,
            utterances=[],
            slots=[],
            requested_at=requested_at,
            completed_at=datetime.now(timezone.utc),
            error=str(exc),
        )
        await save(failed)
        return failed

    result = SessionSectionClassification(
        session_id=session_id,
        status=SectionClassificationStatus.COMPLETE,
        engine=engine,
        utterances=classified_utterances,
        slots=compute_slot_fill_states(slots, classified_utterances),
        requested_at=requested_at,
        completed_at=datetime.now(timezone.utc),
    )
    await save(result)
    return result
