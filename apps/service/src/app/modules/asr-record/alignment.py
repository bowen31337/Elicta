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
service silently picking one engine's wording as the winner. A span is
`is_divergent` when the two readings are not the same words — case and
punctuation aside — because anything short of an exact match between two
independent engines is exactly the case an operator should be able to review
rather than have resolved for them.

The score is kept as the magnitude, not the trigger, and that separation is
the point. Flagging on `agreement_score < DIVERGENCE_THRESHOLD` hid the
errors two engines actually make: one word in twenty scores 0.95 and cleared
the bar, so a misheard number or product name — the substitutions that change
what a requirement means — never reached the operator. Measured over a
recorded meeting, seven planted mishearings scored 0.91-0.96 and not one was
surfaced. `DIVERGENCE_THRESHOLD` still marks the spans worth reading first.
"""

from __future__ import annotations

import difflib
import math
import re
from datetime import UTC, datetime

from .models import (
    AlignedSpan,
    RecordPathTranscript,
    SessionAlignment,
    TranscriptionStatus,
    TranscriptSegment,
)

_WORD_RE = re.compile(r"[a-z0-9']+")

#: Below this, the two readings are far enough apart to be worth reading
#: first. It no longer decides whether a span is surfaced at all — any
#: difference does that — so lowering it hides nothing.
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


def _clipped_words(segment: TranscriptSegment, start_seconds: float, end_seconds: float) -> list[str]:
    """The part of one segment that falls inside [start, end].

    Whole segments were taken before, and that made *how an engine cuts spans*
    into disagreement. Two engines never cut them the same way — Deepgram
    splits on silence, so four words is a typical span, and AssemblyAI on
    sentences — so a four-word reference span was scored against a whole
    paragraph, and two transcripts matching word for word were reported as
    near-total disagreement.

    Words are taken pro rata across the segment's duration, which assumes an
    even speaking rate inside it. That is an approximation and a mild one: it
    is applied only where one engine's span straddles another's, it errs by a
    word at the boundary rather than by a paragraph, and where both engines
    already agree on a boundary it does nothing at all.
    """

    words = segment.text.split()
    span = segment.end_seconds - segment.start_seconds
    if not words or span <= 0:
        return words
    first = max(0.0, (start_seconds - segment.start_seconds) / span)
    last = min(1.0, (end_seconds - segment.start_seconds) / span)
    clipped = words[int(first * len(words)) : math.ceil(last * len(words))]
    # A span narrower than one word's share rounds to nothing. Something was
    # said there, and an empty column would read as the engine having missed
    # it rather than as the boundary falling mid-word.
    return clipped or words[min(int(first * len(words)), len(words) - 1) :][:1]


def _overlapping_text(segments: list[TranscriptSegment], start_seconds: float, end_seconds: float) -> str:
    return " ".join(
        word
        for segment in segments
        if segment.start_seconds < end_seconds and segment.end_seconds > start_seconds
        for word in _clipped_words(segment, start_seconds, end_seconds)
    )


def _says_the_same(reference_text: str, other_text: str, full_other_text: str) -> bool:
    """Whether the other engine said these words here.

    The clip lands within a word of the boundary, so a run that agrees can
    still come back with one word too many or too few. Asking whether the
    reference's words appear as a run inside the *unclipped* overlap catches
    that, and it cannot mask a real substitution: a misheard word is not
    present to be found.
    """

    reference = _normalize_words(reference_text)
    if reference == _normalize_words(other_text):
        return True
    if not reference:
        return False
    whole = _normalize_words(full_other_text)
    return any(
        whole[index : index + len(reference)] == reference
        for index in range(0, max(0, len(whole) - len(reference) + 1))
    )


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
            is_divergent=not _says_the_same(segment.text, other_text, full_other_text),
        )
        for segment in reference.segments
        for other_text in [_overlapping_text(other.segments, segment.start_seconds, segment.end_seconds)]
        for full_other_text in [
            " ".join(
                other_segment.text
                for other_segment in other.segments
                if other_segment.start_seconds < segment.end_seconds
                and other_segment.end_seconds > segment.start_seconds
            )
        ]
        for score in [_agreement_score(segment.text, other_text)]
    ]

    return SessionAlignment(
        session_id=reference.session_id,
        reference_engine=reference.engine,
        other_engine=other.engine,
        spans=spans,
        computed_at=computed_at or datetime.now(UTC),
    )


def divergent_spans(alignment: SessionAlignment) -> list[AlignedSpan]:
    """The subset of `alignment`'s spans PRD FR-2.8 requires surfacing for debrief review.

    `is_divergent` already is the divergent-or-low-confidence flag (see its
    docstring on `AlignedSpan`) — this just selects on it, rather than
    re-deriving anything from `agreement_score`, so the debrief view and the
    threshold that produced `is_divergent` can never disagree.
    """

    return [span for span in alignment.spans if span.is_divergent]


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
