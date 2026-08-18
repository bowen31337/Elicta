import pytest

from .transcript import RecordedTranscript, RecordedUtterance


def _utterance(utterance_id: str, start_ms: int) -> RecordedUtterance:
    return RecordedUtterance(
        utterance_id=utterance_id,
        speaker_tag="speaker-1",
        text="hello",
        start_ms=start_ms,
    )


def test_rejects_negative_start_ms() -> None:
    with pytest.raises(ValueError):
        RecordedUtterance(
            utterance_id="u1",
            speaker_tag="speaker-1",
            text="hello",
            start_ms=-1,
        )


def test_ordered_by_offset_sorts_ascending() -> None:
    transcript = RecordedTranscript(
        utterances=[
            _utterance("u3", 3000),
            _utterance("u1", 1000),
            _utterance("u2", 2000),
        ]
    )

    ordered = transcript.ordered_by_offset()

    assert [u.utterance_id for u in ordered] == ["u1", "u2", "u3"]


def test_ordered_by_offset_is_stable_for_ties() -> None:
    """Cross-talk: two utterances at the same offset keep their original
    relative order rather than being reshuffled."""
    transcript = RecordedTranscript(
        utterances=[
            _utterance("first-at-500", 500),
            _utterance("second-at-500", 500),
        ]
    )

    ordered = transcript.ordered_by_offset()

    assert [u.utterance_id for u in ordered] == ["first-at-500", "second-at-500"]


def test_ordered_by_offset_empty_transcript() -> None:
    assert RecordedTranscript(utterances=[]).ordered_by_offset() == []
