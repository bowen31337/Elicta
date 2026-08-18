"""Aligns two engines' record-path transcripts and scores their agreement per span.

PRD FR-2.6 runs two independent batch engines over the same session audio so
their outputs can be reconciled against each other; reconciliation only
means something once both engines have actually produced a `COMPLETE`
transcript (`align_record_path_transcripts` below decides when that's the
case). Alignment here is time-based rather than a full sequence-alignment
algorithm: one transcript's segments are treated as the reference timeline,
and for each of its spans the other engine's overlapping segments are
concatenated and compared by normalized word overlap. This is intentionally
simple — good enough to surface a per-span confidence signal — not a
phoneme- or WER-level aligner.

PRD FR-2.8 additionally requires every divergent or low-confidence span to
be surfaced to the operator for review during debrief rather than the
service silently picking one engine's wording as the winner. `DIVERGENCE_THRESHOLD`
is the agreement-score cutoff below which a span is flagged `is_divergent`;
it is intentionally not 0.0, since anything short of a (near-)exact match
between two independent engines is exactly the case an operator should be
able to review rather than have resolved for them.
"""

from __future__ import annotations

import difflib
import re
from datetime import datetime, timezone

from .models import AlignedSpan, RecordPathTranscript, SessionAlignment, TranscriptSegment, TranscriptionStatus

_WORD_RE = re.compile(r"[a-z0-9']+")

DIVERGENCE_THRESHOLD = 0.8


def _normalize_words(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower())


def _agreement_score(reference_text: str, other_text: str) -> float:
    reference_words = _normalize_words(reference_text)
    other_words = _normalize_words(other_text)
    if not reference_words and not other_words:
        return 1.0
    if not reference_words or not other_words:
        return 0.0
    return difflib.SequenceMatcher(a=reference_words, b=other_words).ratio()


def _overlapping_text(segments: list[TranscriptSegment], start_seconds: float, end_seconds: float) -> str:
    overlapping = [
        segment
        for segment in segments
        if segment.start_seconds < end_seconds and segment.end_seconds > start_seconds
    ]
    return " ".join(segment.text for segment in overlapping)


def align_transcripts(
    reference: RecordPathTranscript,
    other: RecordPathTranscript,
    *,
    computed_at: datetime | None = None,
) -> SessionAlignment:
    """Align `other`'s output onto `reference`'s span timeline and score each span.

    Both transcripts must belong to the same session and both must be
    `COMPLETE` — this raises `ValueError` otherwise, since aligning a failed
    engine's (empty) output against a successful one would only ever produce
    meaningless zero scores rather than a real confidence signal.
    """

    if reference.session_id != other.session_id:
        raise ValueError("cannot align transcripts from different sessions")
    if reference.status != TranscriptionStatus.COMPLETE or other.status != TranscriptionStatus.COMPLETE:
        raise ValueError("both transcripts must be complete to align")

    spans = [
        AlignedSpan(
            start_seconds=segment.start_seconds,
            end_seconds=segment.end_seconds,
            reference_engine=reference.engine,
            reference_text=segment.text,
            other_engine=other.engine,
            other_text=other_text,
            agreement_score=score,
            is_divergent=score < DIVERGENCE_THRESHOLD,
        )
        for segment in reference.segments
        for other_text in [_overlapping_text(other.segments, segment.start_seconds, segment.end_seconds)]
        for score in [_agreement_score(segment.text, other_text)]
    ]

    return SessionAlignment(
        session_id=reference.session_id,
        reference_engine=reference.engine,
        other_engine=other.engine,
        spans=spans,
        computed_at=computed_at or datetime.now(timezone.utc),
    )


def align_completed_transcripts(
    transcripts: list[RecordPathTranscript],
    *,
    computed_at: datetime | None = None,
) -> SessionAlignment | None:
    """Align the first two `COMPLETE` transcripts among `transcripts`, if there are two.

    Used after a two-engine record-path run: if either engine failed, there
    is only one (or zero) `COMPLETE` transcript and nothing to reconcile, so
    this returns `None` rather than raising — a single engine's result never
    blocks that engine's own transcript from persisting.
    """

    complete = [t for t in transcripts if t.status == TranscriptionStatus.COMPLETE]
    if len(complete) < 2:
        return None
    return align_transcripts(complete[0], complete[1], computed_at=computed_at)
