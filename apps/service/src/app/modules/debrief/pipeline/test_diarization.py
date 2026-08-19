"""Tests for tagging transcript spans with the speaker diarization attributes most of their duration to."""

from __future__ import annotations

from app.modules.debrief.pipeline.diarization import (
    tag_span_speaker,
    tag_spans_with_speakers,
)
from app.modules.debrief.pipeline.models import (
    UNKNOWN_SPEAKER_TAG,
    SpeakerTurn,
    TranscriptSpan,
)


def test_a_span_fully_inside_one_turn_is_tagged_with_that_speaker():
    span = TranscriptSpan(start_seconds=1.0, end_seconds=2.0, text="hello there")
    turns = [SpeakerTurn(start_seconds=0.0, end_seconds=5.0, speaker_tag="alice")]

    assert tag_span_speaker(span, turns) == "alice"


def test_a_span_is_tagged_with_whichever_speaker_overlaps_it_the_most():
    span = TranscriptSpan(start_seconds=0.0, end_seconds=4.0, text="hello there")
    turns = [
        SpeakerTurn(start_seconds=0.0, end_seconds=1.0, speaker_tag="alice"),
        SpeakerTurn(start_seconds=1.0, end_seconds=4.0, speaker_tag="bob"),
    ]

    assert tag_span_speaker(span, turns) == "bob"


def test_a_span_with_no_overlapping_turn_is_tagged_unknown_not_null():
    span = TranscriptSpan(start_seconds=10.0, end_seconds=11.0, text="something was said")
    turns = [SpeakerTurn(start_seconds=0.0, end_seconds=1.0, speaker_tag="alice")]

    assert tag_span_speaker(span, turns) == UNKNOWN_SPEAKER_TAG


def test_no_turns_at_all_is_tagged_unknown():
    span = TranscriptSpan(start_seconds=0.0, end_seconds=1.0, text="something was said")

    assert tag_span_speaker(span, []) == UNKNOWN_SPEAKER_TAG


def test_equal_overlap_breaks_the_tie_toward_the_earlier_speaking_turn():
    span = TranscriptSpan(start_seconds=0.0, end_seconds=2.0, text="hello there")
    turns = [
        SpeakerTurn(start_seconds=1.0, end_seconds=2.0, speaker_tag="bob"),
        SpeakerTurn(start_seconds=0.0, end_seconds=1.0, speaker_tag="alice"),
    ]

    assert tag_span_speaker(span, turns) == "alice"


def test_a_speakers_overlap_is_summed_across_multiple_turns():
    span = TranscriptSpan(start_seconds=0.0, end_seconds=4.0, text="hello there")
    turns = [
        SpeakerTurn(start_seconds=0.0, end_seconds=1.0, speaker_tag="alice"),
        SpeakerTurn(start_seconds=1.0, end_seconds=2.5, speaker_tag="bob"),
        SpeakerTurn(start_seconds=2.5, end_seconds=4.0, speaker_tag="alice"),
    ]

    assert tag_span_speaker(span, turns) == "alice"


def test_tag_spans_with_speakers_tags_every_span_in_order():
    spans = [
        TranscriptSpan(start_seconds=0.0, end_seconds=1.0, text="hi"),
        TranscriptSpan(start_seconds=1.0, end_seconds=2.0, text="hey"),
    ]
    turns = [
        SpeakerTurn(start_seconds=0.0, end_seconds=1.0, speaker_tag="alice"),
        SpeakerTurn(start_seconds=1.0, end_seconds=2.0, speaker_tag="bob"),
    ]

    assert tag_spans_with_speakers(spans, turns) == ["alice", "bob"]


def test_touching_but_non_overlapping_turns_do_not_count_as_overlap():
    span = TranscriptSpan(start_seconds=0.0, end_seconds=1.0, text="hello")
    turns = [SpeakerTurn(start_seconds=1.0, end_seconds=2.0, speaker_tag="alice")]

    assert tag_span_speaker(span, turns) == UNKNOWN_SPEAKER_TAG
