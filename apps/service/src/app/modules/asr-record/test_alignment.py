"""Tests for aligning two engines' record-path transcripts and scoring agreement.

Loaded via `importlib.import_module` with the full dotted path — same reason
as `test_service.py`: `asr-record` is not a valid Python identifier so a
relative import cannot be resolved by pytest's default collection mode.
"""

from __future__ import annotations

import importlib
from datetime import UTC, datetime

import pytest

_models = importlib.import_module("app.modules.asr-record.models")
_alignment = importlib.import_module("app.modules.asr-record.alignment")

RecordPathTranscript = _models.RecordPathTranscript
TranscriptSegment = _models.TranscriptSegment
TranscriptionStatus = _models.TranscriptionStatus
align_transcripts = _alignment.align_transcripts
align_completed_transcripts = _alignment.align_completed_transcripts
divergent_spans = _alignment.divergent_spans
DIVERGENCE_THRESHOLD = _alignment.DIVERGENCE_THRESHOLD

FIXED = datetime(2026, 1, 1, tzinfo=UTC)


def make_transcript(
    engine: str,
    segments: list[TranscriptSegment],
    *,
    session_id: str = "session-1",
    status=TranscriptionStatus.COMPLETE,
) -> RecordPathTranscript:
    return RecordPathTranscript(
        session_id=session_id,
        status=status,
        engine=engine,
        segments=segments,
        text=" ".join(s.text for s in segments),
        requested_at=FIXED,
        completed_at=FIXED,
    )


def test_identical_wording_scores_full_agreement_per_span():
    reference = make_transcript(
        "engine-a",
        [
            TranscriptSegment(start_seconds=0.0, end_seconds=1.5, text="hello there"),
            TranscriptSegment(start_seconds=1.5, end_seconds=3.0, text="how are you"),
        ],
    )
    other = make_transcript(
        "engine-b",
        [
            TranscriptSegment(start_seconds=0.0, end_seconds=1.5, text="hello there"),
            TranscriptSegment(start_seconds=1.5, end_seconds=3.0, text="how are you"),
        ],
    )

    alignment = align_transcripts(reference, other, computed_at=FIXED)

    assert alignment.session_id == "session-1"
    assert alignment.reference_engine == "engine-a"
    assert alignment.other_engine == "engine-b"
    assert len(alignment.spans) == 2
    assert all(span.agreement_score == pytest.approx(1.0) for span in alignment.spans)
    assert all(span.is_divergent is False for span in alignment.spans)


def test_completely_different_wording_scores_zero_agreement():
    reference = make_transcript(
        "engine-a",
        [TranscriptSegment(start_seconds=0.0, end_seconds=1.0, text="apple banana")],
    )
    other = make_transcript(
        "engine-b",
        [TranscriptSegment(start_seconds=0.0, end_seconds=1.0, text="xylophone zebra")],
    )

    alignment = align_transcripts(reference, other, computed_at=FIXED)

    assert alignment.spans[0].agreement_score == 0.0
    assert alignment.spans[0].is_divergent is True


def test_partial_word_overlap_scores_between_zero_and_one():
    reference = make_transcript(
        "engine-a",
        [TranscriptSegment(start_seconds=0.0, end_seconds=1.0, text="the quick brown fox")],
    )
    other = make_transcript(
        "engine-b",
        [TranscriptSegment(start_seconds=0.0, end_seconds=1.0, text="the quick brown fix")],
    )

    alignment = align_transcripts(reference, other, computed_at=FIXED)

    assert 0.0 < alignment.spans[0].agreement_score < 1.0


def test_a_span_with_no_overlapping_speech_from_the_other_engine_scores_zero_not_null():
    reference = make_transcript(
        "engine-a",
        [TranscriptSegment(start_seconds=0.0, end_seconds=1.0, text="something was said")],
    )
    other = make_transcript(
        "engine-b",
        [TranscriptSegment(start_seconds=5.0, end_seconds=6.0, text="unrelated later speech")],
    )

    alignment = align_transcripts(reference, other, computed_at=FIXED)

    assert alignment.spans[0].other_text == ""
    assert alignment.spans[0].agreement_score == 0.0
    assert alignment.spans[0].is_divergent is True


def test_span_scoring_at_or_above_the_divergence_threshold_is_not_flagged():
    reference = make_transcript(
        "engine-a",
        [TranscriptSegment(start_seconds=0.0, end_seconds=1.0, text="hello there friend")],
    )
    other = make_transcript(
        "engine-b",
        [TranscriptSegment(start_seconds=0.0, end_seconds=1.0, text="hello there friend")],
    )

    alignment = align_transcripts(reference, other, computed_at=FIXED)

    assert alignment.spans[0].agreement_score >= DIVERGENCE_THRESHOLD
    assert alignment.spans[0].is_divergent is False


def test_span_scoring_below_the_divergence_threshold_is_flagged():
    reference = make_transcript(
        "engine-a",
        [TranscriptSegment(start_seconds=0.0, end_seconds=1.0, text="the quick brown fox jumps")],
    )
    other = make_transcript(
        "engine-b",
        [TranscriptSegment(start_seconds=0.0, end_seconds=1.0, text="a slow gray dog sleeps")],
    )

    alignment = align_transcripts(reference, other, computed_at=FIXED)

    assert alignment.spans[0].agreement_score < DIVERGENCE_THRESHOLD
    assert alignment.spans[0].is_divergent is True


def test_every_divergent_span_is_flagged_not_just_the_worst_one():
    reference = make_transcript(
        "engine-a",
        [
            TranscriptSegment(start_seconds=0.0, end_seconds=1.0, text="hello there"),
            TranscriptSegment(start_seconds=1.0, end_seconds=2.0, text="apple banana"),
            TranscriptSegment(start_seconds=2.0, end_seconds=3.0, text="cats and dogs"),
        ],
    )
    other = make_transcript(
        "engine-b",
        [
            TranscriptSegment(start_seconds=0.0, end_seconds=1.0, text="hello there"),
            TranscriptSegment(start_seconds=1.0, end_seconds=2.0, text="xylophone zebra"),
            TranscriptSegment(start_seconds=2.0, end_seconds=3.0, text="cats and rabbits"),
        ],
    )

    alignment = align_transcripts(reference, other, computed_at=FIXED)

    divergent = [span for span in alignment.spans if span.is_divergent]
    assert len(divergent) == 2
    assert {span.reference_text for span in divergent} == {"apple banana", "cats and dogs"}


def test_divergent_spans_returns_only_the_flagged_spans():
    reference = make_transcript(
        "engine-a",
        [
            TranscriptSegment(start_seconds=0.0, end_seconds=1.0, text="hello there"),
            TranscriptSegment(start_seconds=1.0, end_seconds=2.0, text="apple banana"),
        ],
    )
    other = make_transcript(
        "engine-b",
        [
            TranscriptSegment(start_seconds=0.0, end_seconds=1.0, text="hello there"),
            TranscriptSegment(start_seconds=1.0, end_seconds=2.0, text="xylophone zebra"),
        ],
    )

    alignment = align_transcripts(reference, other, computed_at=FIXED)

    result = divergent_spans(alignment)
    assert len(result) == 1
    assert result[0].reference_text == "apple banana"


def test_divergent_spans_is_empty_when_nothing_diverges():
    reference = make_transcript(
        "engine-a",
        [TranscriptSegment(start_seconds=0.0, end_seconds=1.0, text="hello there")],
    )
    other = make_transcript(
        "engine-b",
        [TranscriptSegment(start_seconds=0.0, end_seconds=1.0, text="hello there")],
    )

    alignment = align_transcripts(reference, other, computed_at=FIXED)

    assert divergent_spans(alignment) == []


def test_agreement_score_is_bounded_between_zero_and_one():
    reference = make_transcript(
        "engine-a",
        [TranscriptSegment(start_seconds=0.0, end_seconds=1.0, text="hello world")],
    )
    other = make_transcript(
        "engine-b",
        [
            TranscriptSegment(start_seconds=0.0, end_seconds=0.5, text="hello"),
            TranscriptSegment(start_seconds=0.5, end_seconds=1.0, text="world"),
        ],
    )

    alignment = align_transcripts(reference, other, computed_at=FIXED)

    assert alignment.spans[0].other_text == "hello world"
    assert 0.0 <= alignment.spans[0].agreement_score <= 1.0


def test_aligning_across_different_sessions_raises():
    reference = make_transcript("engine-a", [], session_id="session-1")
    other = make_transcript("engine-b", [], session_id="session-2")

    with pytest.raises(ValueError, match="different sessions"):
        align_transcripts(reference, other)


def test_aligning_a_failed_transcript_raises():
    reference = make_transcript("engine-a", [], status=TranscriptionStatus.COMPLETE)
    other = make_transcript("engine-b", [], status=TranscriptionStatus.FAILED)

    with pytest.raises(ValueError, match="complete"):
        align_transcripts(reference, other)


def test_align_completed_transcripts_returns_none_when_fewer_than_two_completed():
    only_one = [make_transcript("engine-a", [])]

    assert align_completed_transcripts(only_one) is None

    one_failed = [
        make_transcript("engine-a", []),
        make_transcript("engine-b", [], status=TranscriptionStatus.FAILED),
    ]

    assert align_completed_transcripts(one_failed) is None


def test_align_completed_transcripts_aligns_the_two_completed_ones():
    transcripts = [
        make_transcript(
            "engine-a",
            [TranscriptSegment(start_seconds=0.0, end_seconds=1.0, text="hello world")],
        ),
        make_transcript(
            "engine-b",
            [TranscriptSegment(start_seconds=0.0, end_seconds=1.0, text="hello world")],
        ),
    ]

    alignment = align_completed_transcripts(transcripts, computed_at=FIXED)

    assert alignment is not None
    assert alignment.reference_engine == "engine-a"
    assert alignment.other_engine == "engine-b"
    assert alignment.spans[0].agreement_score == pytest.approx(1.0)
    assert alignment.computed_at == FIXED


def test_a_span_neither_engine_put_words_in_is_not_a_divergence():
    # A pause the reference engine bracketed as a segment, where neither
    # engine transcribed a word. Scoring that zero would flag every silence
    # for debrief review, burying the divergences that mean something.
    reference = make_transcript(
        "engine-a",
        [TranscriptSegment(start_seconds=0.0, end_seconds=2.0, text="...")],
    )
    other = make_transcript(
        "engine-b",
        [TranscriptSegment(start_seconds=0.0, end_seconds=2.0, text="--")],
    )

    alignment = align_transcripts(reference, other, computed_at=FIXED)

    assert alignment.spans[0].agreement_score == pytest.approx(1.0)
    assert alignment.spans[0].is_divergent is False
    assert divergent_spans(alignment) == []


def test_a_single_misheard_word_in_a_long_span_is_flagged():
    """The errors that matter most are the ones a ratio hides.

    Two engines disagreeing about one word in twenty score 0.95, which clears
    the 0.8 threshold — so a misheard number or product name, which is exactly
    what two engines actually disagree about, never reached the operator.
    Measured over a recorded meeting: seven planted mishearings, a number and
    four product names among them, scored 0.91–0.96 and not one was surfaced.

    This module's own docstring says the bar is a near-exact match. This is
    that bar: the score still says how far apart they are, but any difference
    at all is something the operator gets to see rather than have resolved for
    them.
    """

    said = "the chilled stock cannot sit on the dock longer than fifteen minutes"
    heard = "the chilled stock cannot sit on the dock longer than fifty minutes"
    reference = make_transcript(
        "engine-a", [TranscriptSegment(start_seconds=0.0, end_seconds=6.0, text=said)]
    )
    other = make_transcript(
        "engine-b", [TranscriptSegment(start_seconds=0.0, end_seconds=6.0, text=heard)]
    )

    alignment = align_transcripts(reference, other, computed_at=FIXED)

    assert alignment.spans[0].agreement_score > DIVERGENCE_THRESHOLD, (
        "this is the case a ratio calls agreement"
    )
    assert alignment.spans[0].is_divergent is True


def test_wording_that_differs_only_in_punctuation_or_case_still_agrees():
    """Otherwise every span diverges and the review list means nothing."""

    reference = make_transcript(
        "engine-a",
        [TranscriptSegment(start_seconds=0.0, end_seconds=2.0, text="Under a minute.")],
    )
    other = make_transcript(
        "engine-b",
        [TranscriptSegment(start_seconds=0.0, end_seconds=2.0, text="under a minute")],
    )

    alignment = align_transcripts(reference, other, computed_at=FIXED)

    assert alignment.spans[0].is_divergent is False


class TestTwoEnginesThatAgreeAreNotReportedAsDisagreeing:
    """Reported from the recording screen: "the two columns are so different".

    One column held four words and the other held a paragraph, on a pair of
    transcripts that said the same thing. The cause is here rather than in
    either engine: a reference span was scored against every *whole* segment
    it overlapped, so cutting spans differently was itself read as
    disagreement.

    Two engines never cut spans the same way — Deepgram splits on silence
    (four words is a typical span) and AssemblyAI on sentences. So this did
    not merely add noise, it made the comparison report near-total
    disagreement between transcripts that matched word for word, which is the
    one number an operator is meant to act on.
    """

    #: The same eight words, cut in two and in one.
    FINE = [
        TranscriptSegment(
            start_seconds=0, end_seconds=2, text="be familiar with evacuation", speaker=None
        ),
        TranscriptSegment(
            start_seconds=2, end_seconds=4, text="procedures and fire exits", speaker=None
        ),
    ]
    COARSE = [
        TranscriptSegment(
            start_seconds=0,
            end_seconds=4,
            text="be familiar with evacuation procedures and fire exits",
            speaker=None,
        )
    ]

    def test_the_same_words_cut_differently_agree(self):
        alignment = align_transcripts(
            make_transcript("deepgram", self.FINE),
            make_transcript("assemblyai", self.COARSE),
        )

        assert [s.agreement_score for s in alignment.spans] == [1.0, 1.0]
        assert not any(s.is_divergent for s in alignment.spans)

    def test_the_other_column_holds_what_was_said_in_that_span(self):
        """Not the whole paragraph the span happened to fall inside."""

        alignment = align_transcripts(
            make_transcript("deepgram", self.FINE),
            make_transcript("assemblyai", self.COARSE),
        )

        assert alignment.spans[0].other_text == "be familiar with evacuation"
        assert alignment.spans[1].other_text == "procedures and fire exits"

    def test_a_real_disagreement_inside_a_coarse_span_still_shows(self):
        """The whole point of the pairing, and the thing not to break."""

        wrong = [
            TranscriptSegment(
                start_seconds=0,
                end_seconds=4,
                text="be familiar with evacuation procedures and fire escapes",
                speaker=None,
            )
        ]

        alignment = align_transcripts(
            make_transcript("deepgram", self.FINE),
            make_transcript("assemblyai", wrong),
        )

        assert not alignment.spans[0].is_divergent
        assert alignment.spans[1].is_divergent
        assert "escapes" in alignment.spans[1].other_text
