"""AssemblyAI on the record path (spec §5.4b).

A different shape from Deepgram's: audio is uploaded to the vendor first, then
polled, then deleted. The delete is not optional — it is the only reason this
vendor's flow sits inside the audio promise, so several tests below exist
purely to prove the delete happens even when the run itself fails.

The utterance shape (`start`/`end` as int milliseconds, `speaker` as a
one-letter string) was checked against one live transcription before this
file was written — see the module docstring in `assemblyai_engines.py`.
No test here makes a live call; every engine test drives an
`httpx.MockTransport`.
"""

from __future__ import annotations

import httpx
import pytest

from app.modules.settings.models import SecretValue
from app.orchestration.assemblyai_engines import (
    AssemblyAIUnavailable,
    assemblyai_record_engine,
    to_batch_transcription,
)

RESPONSE = {
    "status": "completed",
    "text": "Yeah, the dock rule is fifteen minutes.",
    "utterances": [
        {"start": 0, "end": 3840, "speaker": "A", "text": "Yeah, the dock rule is fifteen minutes."},
        {"start": 3900, "end": 6200, "speaker": "B", "text": "Is that written down anywhere?"},
    ],
}


class MockStore:
    """A settings store that always has the credential, unless told not to."""

    def __init__(self, secret: SecretValue | None = SecretValue("test_key")) -> None:
        self._secret = secret

    def get_secret(self, key):
        return self._secret


def mock_read_audio(session_id: str) -> bytes:
    return b"mock audio data"


def test_milliseconds_become_seconds() -> None:
    """AssemblyAI reports milliseconds and the record path stores seconds.
    Storing one as the other silently misplaces every citation in the debrief."""

    output = to_batch_transcription(RESPONSE, "assemblyai")

    assert [(s.start_seconds, s.end_seconds) for s in output.segments] == [
        (0.0, 3.84),
        (3.9, 6.2),
    ]


def test_the_speaker_travels_with_the_segment() -> None:
    output = to_batch_transcription(RESPONSE, "assemblyai")

    assert [s.speaker for s in output.segments] == ["A", "B"]


def test_the_engine_names_itself() -> None:
    """`engine` plus `session_id` identify a transcript, so this must differ
    from Deepgram's or the two engines overwrite each other."""

    assert to_batch_transcription(RESPONSE, "assemblyai").engine == "assemblyai"


def test_a_response_with_no_utterances_is_a_failure() -> None:
    with pytest.raises(ValueError, match="no utterances"):
        to_batch_transcription({"status": "completed", "utterances": []}, "assemblyai")


@pytest.mark.asyncio
async def test_a_successful_run_uploads_polls_completes_and_deletes() -> None:
    """The whole upload -> submit -> poll -> completed -> delete round trip,
    mapped to `BatchTranscriptionOutput`."""

    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.method == "POST" and request.url.path == "/v2/upload":
            return httpx.Response(200, json={"upload_url": "https://cdn.assemblyai.com/upload/xyz"})
        if request.method == "POST" and request.url.path == "/v2/transcript":
            return httpx.Response(200, json={"id": "abc123"})
        if request.method == "GET" and request.url.path == "/v2/transcript/abc123":
            return httpx.Response(200, json=RESPONSE)
        if request.method == "DELETE" and request.url.path == "/v2/transcript/abc123":
            return httpx.Response(200, json={"status": "deleted"})
        raise AssertionError(f"unexpected request: {request.method} {request.url.path}")

    engine = assemblyai_record_engine(
        mock_read_audio,
        MockStore(),
        transport=httpx.MockTransport(handler),
        poll_seconds=0.01,
    )

    output = await engine("session_123", "audio_ref_unused", ["FROSTLINE"])

    assert output.engine == "assemblyai"
    assert len(output.segments) == 2
    assert output.segments[0].text == "Yeah, the dock rule is fifteen minutes."
    assert ("DELETE", "/v2/transcript/abc123") in calls


@pytest.mark.asyncio
async def test_a_status_error_response_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/v2/upload":
            return httpx.Response(200, json={"upload_url": "https://cdn.assemblyai.com/upload/xyz"})
        if request.method == "POST" and request.url.path == "/v2/transcript":
            return httpx.Response(200, json={"id": "abc123"})
        if request.method == "GET" and request.url.path == "/v2/transcript/abc123":
            return httpx.Response(200, json={"status": "error", "error": "vendor exploded"})
        if request.method == "DELETE" and request.url.path == "/v2/transcript/abc123":
            return httpx.Response(200, json={"status": "deleted"})
        raise AssertionError(f"unexpected request: {request.method} {request.url.path}")

    engine = assemblyai_record_engine(
        mock_read_audio,
        MockStore(),
        transport=httpx.MockTransport(handler),
        poll_seconds=0.01,
    )

    with pytest.raises(AssemblyAIUnavailable, match="AssemblyAI failed"):
        await engine("session_123", "audio_ref_unused", [])


@pytest.mark.asyncio
async def test_the_poll_ceiling_being_reached_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/v2/upload":
            return httpx.Response(200, json={"upload_url": "https://cdn.assemblyai.com/upload/xyz"})
        if request.method == "POST" and request.url.path == "/v2/transcript":
            return httpx.Response(200, json={"id": "abc123"})
        if request.method == "GET" and request.url.path == "/v2/transcript/abc123":
            return httpx.Response(200, json={"status": "processing"})
        if request.method == "DELETE" and request.url.path == "/v2/transcript/abc123":
            return httpx.Response(200, json={"status": "deleted"})
        raise AssertionError(f"unexpected request: {request.method} {request.url.path}")

    engine = assemblyai_record_engine(
        mock_read_audio,
        MockStore(),
        transport=httpx.MockTransport(handler),
        poll_seconds=0.01,
        poll_ceiling_seconds=0.03,
    )

    with pytest.raises(AssemblyAIUnavailable, match="still processing"):
        await engine("session_123", "audio_ref_unused", [])


@pytest.mark.asyncio
async def test_no_audio_raises_before_any_request() -> None:
    """Empty audio fails closed before reaching the network."""

    call_count = [0]

    def counting_transport(request: httpx.Request) -> httpx.Response:
        call_count[0] += 1
        return httpx.Response(200, json=RESPONSE)

    def empty_read_audio(session_id: str) -> bytes:
        return b""

    engine = assemblyai_record_engine(
        empty_read_audio,
        MockStore(),
        transport=httpx.MockTransport(counting_transport),
    )

    with pytest.raises(AssemblyAIUnavailable, match="nothing to transcribe"):
        await engine("session_123", "audio_ref_unused", [])

    assert call_count[0] == 0, "transport was called when audio was empty"


@pytest.mark.asyncio
async def test_no_credential_raises_before_any_request() -> None:
    """Missing AssemblyAI credential fails closed before reaching the network."""

    call_count = [0]

    def counting_transport(request: httpx.Request) -> httpx.Response:
        call_count[0] += 1
        return httpx.Response(200, json=RESPONSE)

    engine = assemblyai_record_engine(
        mock_read_audio,
        MockStore(secret=None),
        transport=httpx.MockTransport(counting_transport),
    )

    with pytest.raises(AssemblyAIUnavailable, match="credential"):
        await engine("session_123", "audio_ref_unused", [])

    assert call_count[0] == 0, "transport was called when credential was missing"


@pytest.mark.asyncio
async def test_delete_is_issued_even_when_the_run_fails() -> None:
    """The vendor is holding a copy of a client's meeting. The delete is the
    only reason storing audio with this vendor is acceptable, so it must run
    on the failure path exactly as it does on the success path."""

    delete_calls = [0]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/v2/upload":
            return httpx.Response(200, json={"upload_url": "https://cdn.assemblyai.com/upload/xyz"})
        if request.method == "POST" and request.url.path == "/v2/transcript":
            return httpx.Response(200, json={"id": "abc123"})
        if request.method == "GET" and request.url.path == "/v2/transcript/abc123":
            return httpx.Response(200, json={"status": "error", "error": "vendor exploded"})
        if request.method == "DELETE" and request.url.path == "/v2/transcript/abc123":
            delete_calls[0] += 1
            return httpx.Response(200, json={"status": "deleted"})
        raise AssertionError(f"unexpected request: {request.method} {request.url.path}")

    engine = assemblyai_record_engine(
        mock_read_audio,
        MockStore(),
        transport=httpx.MockTransport(handler),
        poll_seconds=0.01,
    )

    with pytest.raises(AssemblyAIUnavailable):
        await engine("session_123", "audio_ref_unused", [])

    assert delete_calls[0] == 1, "the vendor-side copy must be deleted even on failure"
