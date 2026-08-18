"""Tests for grounding artifact claims and coverage decisions in record-path output.

Loaded via `importlib.import_module` with the full dotted path — same reason
as `test_alignment.py`: `asr-record` is not a valid Python identifier so a
relative import cannot be resolved by pytest's default collection mode.
"""

from __future__ import annotations

import importlib
from datetime import datetime, timezone

import pytest

_models = importlib.import_module("app.modules.asr-record.models")
_citation = importlib.import_module("app.modules.asr-record.citation")

RecordPathTranscript = _models.RecordPathTranscript
TranscriptSegment = _models.TranscriptSegment
TranscriptionStatus = _models.TranscriptionStatus
cite_record_path_span = _citation.cite_record_path_span
record_path_covers_span = _citation.record_path_covers_span

FIXED = datetime(2026, 1, 1, tzinfo=timezone.utc)


def make_transcript(
    segments: list[TranscriptSegment],
    *,
    session_id: str = "session-1",
    engine: str = "engine-a",
    status=TranscriptionStatus.COMPLETE,
    completed_at: datetime = FIXED,
) -> RecordPathTranscript:
    return RecordPathTranscript(
        session_id=session_id,
        status=status,
        engine=engine,
        segments=segments,
        text=" ".join(s.text for s in segments),
        requested_at=FIXED,
        completed_at=completed_at,
        error="batch engine unavailable" if status == TranscriptionStatus.FAILED else None,
    )


def test_cite_record_path_span_builds_a_reference_from_the_overlapping_segment():
    transcript = make_transcript(
        [TranscriptSegment(start_seconds=0.0, end_seconds=2.0, text="the budget is fifty thousand dollars")],
        session_id="session-1",
        engine="engine-a",
        completed_at=FIXED,
    )

    reference = cite_record_path_span(transcript, 0.0, 2.0)

    assert reference.session_id == "session-1"
    assert reference.engine == "engine-a"
    assert reference.start_seconds == 0.0
    assert reference.end_seconds == 2.0
    assert reference.quoted_text == "the budget is fifty thousand dollars"
    assert reference.transcript_completed_at == FIXED


def test_cite_record_path_span_concatenates_every_overlapping_segment_in_order():
    transcript = make_transcript(
        [
            TranscriptSegment(start_seconds=0.0, end_seconds=1.0, text="first"),
            TranscriptSegment(start_seconds=1.0, end_seconds=2.0, text="second"),
            TranscriptSegment(start_seconds=5.0, end_seconds=6.0, text="unrelated"),
        ]
    )

    reference = cite_record_path_span(transcript, 0.0, 2.0)

    assert reference.quoted_text == "first second"


def test_cite_record_path_span_raises_when_transcript_is_not_complete():
    transcript = make_transcript(
        [TranscriptSegment(start_seconds=0.0, end_seconds=1.0, text="hello")],
        status=TranscriptionStatus.FAILED,
    )

    with pytest.raises(ValueError, match="not complete"):
        cite_record_path_span(transcript, 0.0, 1.0)


def test_cite_record_path_span_raises_when_no_segment_covers_the_span():
    transcript = make_transcript(
        [TranscriptSegment(start_seconds=0.0, end_seconds=1.0, text="hello")],
    )

    with pytest.raises(ValueError, match="does not cover"):
        cite_record_path_span(transcript, 10.0, 11.0)


def test_record_path_covers_span_is_true_when_a_segment_overlaps():
    transcript = make_transcript(
        [TranscriptSegment(start_seconds=0.0, end_seconds=1.0, text="hello")],
    )

    assert record_path_covers_span(transcript, 0.5, 1.5) is True


def test_record_path_covers_span_is_false_with_no_overlapping_segment():
    transcript = make_transcript(
        [TranscriptSegment(start_seconds=0.0, end_seconds=1.0, text="hello")],
    )

    assert record_path_covers_span(transcript, 10.0, 11.0) is False


def test_record_path_covers_span_is_false_for_a_failed_transcript_even_with_a_nominal_segment():
    transcript = make_transcript(
        [TranscriptSegment(start_seconds=0.0, end_seconds=1.0, text="hello")],
        status=TranscriptionStatus.FAILED,
    )

    assert record_path_covers_span(transcript, 0.0, 1.0) is False
