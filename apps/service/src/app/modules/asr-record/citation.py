"""Grounds artifact claims, citations, and coverage decisions in record-path output (PRD FR-2.7).

PRD FR-8 artifacts (the requirements coverage matrix, the open-questions
list, every requirement claim's timestamp-and-speaker citation) must derive
from the record path's batch, highest-accuracy transcript, never from the
live path's interim, lower-latency output — a live-path hypothesis can still
be revised or simply wrong in a way the record path has already resolved by
the time debrief artifacts are generated. `cite_record_path_span` is the one
function in this package that produces a `RecordPathSourceReference`, and it
only accepts a `RecordPathTranscript` (never a live-path transcript type, of
which none exists in this package), so nothing downstream can construct a
record-path-shaped citation without one actually backing it.

`record_path_covers_span` is the coverage-decision counterpart: it answers
"does the record path actually have transcribed speech for this span" as a
plain boolean rather than raising, since a coverage matrix (PRD FR-8.2) needs
to render an unfilled section, not fail to build.
"""

from __future__ import annotations

from .models import RecordPathSourceReference, RecordPathTranscript, TranscriptSegment, TranscriptionStatus


def _overlapping_segments(
    transcript: RecordPathTranscript, start_seconds: float, end_seconds: float
) -> list[TranscriptSegment]:
    return [
        segment
        for segment in transcript.segments
        if segment.start_seconds < end_seconds and segment.end_seconds > start_seconds
    ]


def record_path_covers_span(transcript: RecordPathTranscript, start_seconds: float, end_seconds: float) -> bool:
    """Whether `transcript` actually has record-path speech over `[start_seconds, end_seconds)`.

    False for any transcript that isn't `COMPLETE` — a `FAILED` batch run has
    no reliable segments to cover anything with — and false when no
    persisted segment overlaps the span, even if the transcript otherwise
    covers the session. Used to gate a coverage decision (PRD FR-8.2) on the
    record path rather than on whatever the live path guessed was said.
    """

    if transcript.status != TranscriptionStatus.COMPLETE:
        return False
    return bool(_overlapping_segments(transcript, start_seconds, end_seconds))


def cite_record_path_span(
    transcript: RecordPathTranscript, start_seconds: float, end_seconds: float
) -> RecordPathSourceReference:
    """Build the source reference for one artifact claim's citation (PRD FR-2.7/FR-8.7).

    Raises `ValueError` rather than returning a hollow reference when
    `transcript` isn't `COMPLETE` or when no persisted segment overlaps the
    requested span — an artifact claim citing a moment the record path
    doesn't actually cover would be indistinguishable from one sourced from
    the live path, which is exactly what this feature exists to prevent.
    `quoted_text` concatenates every overlapping segment's text in order,
    the same overlap rule `alignment.py` uses to compare the two engines
    over a span.
    """

    if transcript.status != TranscriptionStatus.COMPLETE:
        raise ValueError("cannot cite a span from a record-path transcript that is not complete")

    overlapping = _overlapping_segments(transcript, start_seconds, end_seconds)
    if not overlapping:
        raise ValueError("cannot cite a span the record-path transcript does not cover")

    return RecordPathSourceReference(
        session_id=transcript.session_id,
        engine=transcript.engine,
        start_seconds=start_seconds,
        end_seconds=end_seconds,
        quoted_text=" ".join(segment.text for segment in overlapping),
        transcript_completed_at=transcript.completed_at,
    )
