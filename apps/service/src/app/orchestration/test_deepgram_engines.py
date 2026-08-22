"""Deepgram on the record path (spec §5.4a).

The response fixture below is the shape a real 90-minute run returned, trimmed
to two utterances. No test here makes a live call.
"""

from __future__ import annotations

import pytest

from app.orchestration.deepgram_engines import (
    deepgram_listen_url,
    to_batch_transcription,
)

RESPONSE = {
    "results": {
        "channels": [
            {"alternatives": [{"transcript": "Yeah, the dock rule is fifteen minutes."}]}
        ],
        "utterances": [
            {
                "start": 0.0,
                "end": 3.84,
                "speaker": 0,
                "transcript": "Yeah, the dock rule is fifteen minutes.",
                "confidence": 0.99,
            },
            {
                "start": 3.9,
                "end": 6.2,
                "speaker": 1,
                "transcript": "Is that written down anywhere?",
                "confidence": 0.98,
            },
        ],
    }
}


def test_every_utterance_becomes_a_timed_segment() -> None:
    output = to_batch_transcription(RESPONSE, "deepgram")

    assert output.engine == "deepgram"
    assert [(s.start_seconds, s.end_seconds) for s in output.segments] == [
        (0.0, 3.84),
        (3.9, 6.2),
    ]
    assert output.segments[1].text == "Is that written down anywhere?"


def test_the_speaker_travels_with_the_segment() -> None:
    """`TranscriptSegment.speaker` exists and the record path shows it."""

    output = to_batch_transcription(RESPONSE, "deepgram")

    assert [s.speaker for s in output.segments] == ["0", "1"]


def test_the_full_transcript_comes_from_the_alternative() -> None:
    """Not from joining the utterances, which drops the vendor's punctuation
    and spacing decisions."""

    output = to_batch_transcription(RESPONSE, "deepgram")

    assert output.text == "Yeah, the dock rule is fifteen minutes."


def test_a_response_with_no_utterances_is_a_failure_not_an_empty_transcript() -> None:
    """An empty transcript reads as a meeting where nobody spoke."""

    with pytest.raises(ValueError, match="no utterances"):
        to_batch_transcription({"results": {"channels": [], "utterances": []}}, "deepgram")


def test_the_request_carries_the_engagement_vocabulary() -> None:
    url = deepgram_listen_url("nova-3", ["FROSTLINE", "cross dock"])

    assert "keyterm=FROSTLINE" in url
    assert "keyterm=cross+dock" in url or "keyterm=cross%20dock" in url


def test_the_request_opts_out_of_vendor_retention() -> None:
    """NFR-2.3: retention is a request parameter, not only a contract clause."""

    assert "mip_opt_out=true" in deepgram_listen_url("nova-3", [])


def test_the_request_describes_the_audio_the_capture_path_produces() -> None:
    url = deepgram_listen_url("nova-3", [])

    for expected in ("encoding=linear16", "sample_rate=16000", "channels=1"):
        assert expected in url

    for expected in ("diarize=true", "utterances=true", "model=nova-3"):
        assert expected in url
