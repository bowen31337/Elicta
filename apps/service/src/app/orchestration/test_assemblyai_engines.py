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

import io
import json
import wave
from typing import Any

import httpx
import pytest

from app.modules.settings.models import SecretValue
from app.orchestration.assemblyai_engines import (
    CAPTURE_CHANNELS,
    CAPTURE_SAMPLE_RATE_HZ,
    CAPTURE_SAMPLE_WIDTH_BYTES,
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
    """A settings store that always has the credential, unless told not to.

    `read` answers with the default settings: the engine reads `connectors`
    per call now, because `keyterm_prompting` is an operator-facing switch and
    what it is set to has to reach the request.
    """

    def __init__(
        self,
        secret: SecretValue | None = SecretValue("test_key"),
        *,
        settings: Any = None,
    ) -> None:
        self._secret = secret
        self._settings = settings

    def get_secret(self, key):
        return self._secret

    def read(self):
        from app.modules.settings.models import ServiceSettings

        return self._settings or ServiceSettings()


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


@pytest.mark.asyncio
async def test_a_failed_delete_surfaces_even_though_transcription_succeeded() -> None:
    """The transcription itself succeeded, but the vendor refused to delete
    its copy. That must still fail the run, and name the transcript id so an
    operator can find and remove the copy that was left behind."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/v2/upload":
            return httpx.Response(200, json={"upload_url": "https://cdn.assemblyai.com/upload/xyz"})
        if request.method == "POST" and request.url.path == "/v2/transcript":
            return httpx.Response(200, json={"id": "abc123"})
        if request.method == "GET" and request.url.path == "/v2/transcript/abc123":
            return httpx.Response(200, json=RESPONSE)
        if request.method == "DELETE" and request.url.path == "/v2/transcript/abc123":
            return httpx.Response(404)
        raise AssertionError(f"unexpected request: {request.method} {request.url.path}")

    engine = assemblyai_record_engine(
        mock_read_audio,
        MockStore(),
        transport=httpx.MockTransport(handler),
        poll_seconds=0.01,
    )

    with pytest.raises(AssemblyAIUnavailable, match="abc123"):
        await engine("session_123", "audio_ref_unused", [])


@pytest.mark.asyncio
async def test_a_delete_transport_error_is_chained() -> None:
    """A network failure during delete must not be swallowed either — it
    surfaces as `AssemblyAIUnavailable` with the original exception chained,
    so the cause is still visible."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/v2/upload":
            return httpx.Response(200, json={"upload_url": "https://cdn.assemblyai.com/upload/xyz"})
        if request.method == "POST" and request.url.path == "/v2/transcript":
            return httpx.Response(200, json={"id": "abc123"})
        if request.method == "GET" and request.url.path == "/v2/transcript/abc123":
            return httpx.Response(200, json=RESPONSE)
        if request.method == "DELETE" and request.url.path == "/v2/transcript/abc123":
            raise httpx.ConnectError("connection reset")
        raise AssertionError(f"unexpected request: {request.method} {request.url.path}")

    engine = assemblyai_record_engine(
        mock_read_audio,
        MockStore(),
        transport=httpx.MockTransport(handler),
        poll_seconds=0.01,
    )

    with pytest.raises(AssemblyAIUnavailable, match="abc123") as excinfo:
        await engine("session_123", "audio_ref_unused", [])

    assert isinstance(excinfo.value.__cause__, httpx.HTTPError)


def test_a_response_missing_utterances_entirely_is_a_failure() -> None:
    """`payload.get("utterances") or []` treats a missing key the same as an
    empty list — this pins that the missing-key case is also refused."""

    with pytest.raises(ValueError, match="no utterances"):
        to_batch_transcription({"status": "completed"}, "assemblyai")


@pytest.mark.asyncio
async def test_the_upload_wraps_pcm_in_a_wav_container_with_the_right_format() -> None:
    """AssemblyAI infers format from the container, unlike Deepgram which is
    told the format in query parameters. A body with no header, or one
    claiming the wrong rate/channels/depth, silently fails to transcribe on
    the real vendor even though every mocked test here would still pass —
    so this parses the header back out rather than comparing a magic blob."""

    pcm = b"\x01\x00\x02\x00\x03\x00\x04\x00" * 100
    uploaded_bodies: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/v2/upload":
            uploaded_bodies.append(request.content)
            return httpx.Response(200, json={"upload_url": "https://cdn.assemblyai.com/upload/xyz"})
        if request.method == "POST" and request.url.path == "/v2/transcript":
            return httpx.Response(200, json={"id": "abc123"})
        if request.method == "GET" and request.url.path == "/v2/transcript/abc123":
            return httpx.Response(200, json=RESPONSE)
        if request.method == "DELETE" and request.url.path == "/v2/transcript/abc123":
            return httpx.Response(200, json={"status": "deleted"})
        raise AssertionError(f"unexpected request: {request.method} {request.url.path}")

    engine = assemblyai_record_engine(
        lambda session_id: pcm,
        MockStore(),
        transport=httpx.MockTransport(handler),
        poll_seconds=0.01,
    )

    await engine("session_123", "audio_ref_unused", [])

    assert len(uploaded_bodies) == 1
    body = uploaded_bodies[0]

    assert body[:4] == b"RIFF"
    assert body[8:12] == b"WAVE"

    with wave.open(io.BytesIO(body), "rb") as reader:
        assert reader.getframerate() == CAPTURE_SAMPLE_RATE_HZ
        assert reader.getnchannels() == CAPTURE_CHANNELS
        assert reader.getsampwidth() == CAPTURE_SAMPLE_WIDTH_BYTES
        assert reader.readframes(reader.getnframes()) == pcm


@pytest.mark.asyncio
async def test_the_wav_header_adds_exactly_44_bytes() -> None:
    """A future change that drops the header, or adds a second one, must
    fail here rather than only on the real vendor."""

    pcm = b"\x00\x01" * 500
    uploaded_bodies: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/v2/upload":
            uploaded_bodies.append(request.content)
            return httpx.Response(200, json={"upload_url": "https://cdn.assemblyai.com/upload/xyz"})
        if request.method == "POST" and request.url.path == "/v2/transcript":
            return httpx.Response(200, json={"id": "abc123"})
        if request.method == "GET" and request.url.path == "/v2/transcript/abc123":
            return httpx.Response(200, json=RESPONSE)
        if request.method == "DELETE" and request.url.path == "/v2/transcript/abc123":
            return httpx.Response(200, json={"status": "deleted"})
        raise AssertionError(f"unexpected request: {request.method} {request.url.path}")

    engine = assemblyai_record_engine(
        lambda session_id: pcm,
        MockStore(),
        transport=httpx.MockTransport(handler),
        poll_seconds=0.01,
    )

    await engine("session_123", "audio_ref_unused", [])

    assert len(uploaded_bodies[0]) == 44 + len(pcm)


@pytest.mark.asyncio
async def test_the_submitted_request_carries_the_engagement_vocabulary() -> None:
    """FR-2.9 / spec 7: `word_boost` is AssemblyAI's counterpart to Deepgram's
    `keyterm`, and it is the path the engagement's own vocabulary travels —
    the single most effective accuracy control an operator has. Sending the
    request without it still returns a transcript, just a wronger one, which
    is exactly the kind of silent loss no live run would report."""

    submitted_bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/v2/upload":
            return httpx.Response(200, json={"upload_url": "https://cdn.assemblyai.com/upload/xyz"})
        if request.method == "POST" and request.url.path == "/v2/transcript":
            submitted_bodies.append(json.loads(request.content))
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

    await engine("session_123", "audio_ref_unused", ["FROSTLINE", "cross dock"])

    assert submitted_bodies[0]["word_boost"] == ["FROSTLINE", "cross dock"]


@pytest.mark.asyncio
async def test_a_refused_poll_fails_fast_instead_of_spending_the_ceiling() -> None:
    """A 401 mid-poll is not "no status yet".

    Reading a refusal as a poll that has not come back yet ran the full
    1800-second ceiling — 600 requests — and then reported "still processing
    after 1800s", which is the wrong diagnosis with the debrief blocked behind
    it. The credential is what is wrong, and the message has to say so.
    """

    polls = [0]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/v2/upload":
            return httpx.Response(200, json={"upload_url": "https://cdn.assemblyai.com/upload/xyz"})
        if request.method == "POST" and request.url.path == "/v2/transcript":
            return httpx.Response(200, json={"id": "abc123"})
        if request.method == "GET" and request.url.path == "/v2/transcript/abc123":
            polls[0] += 1
            return httpx.Response(401, json={"error": "Authentication error, API token missing/invalid"})
        if request.method == "DELETE" and request.url.path == "/v2/transcript/abc123":
            return httpx.Response(200, json={"status": "deleted"})
        raise AssertionError(f"unexpected request: {request.method} {request.url.path}")

    engine = assemblyai_record_engine(
        mock_read_audio,
        MockStore(),
        transport=httpx.MockTransport(handler),
        poll_seconds=0.01,
        # Generous on purpose: a fix that only fails when the ceiling runs out
        # would still pass a test that set the ceiling low.
        poll_ceiling_seconds=1800.0,
    )

    with pytest.raises(AssemblyAIUnavailable, match="401") as excinfo:
        await engine("session_123", "audio_ref_unused", [])

    assert "still processing" not in str(excinfo.value)
    assert polls[0] == 1, "the poll loop kept asking after a refusal"


@pytest.mark.asyncio
async def test_a_poll_body_that_is_not_json_says_what_came_back() -> None:
    """A gateway's HTML error page reaches `.json()` as a decode traceback
    naming a byte offset. What matters is that the vendor did not answer with
    JSON, and what it said instead."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/v2/upload":
            return httpx.Response(200, json={"upload_url": "https://cdn.assemblyai.com/upload/xyz"})
        if request.method == "POST" and request.url.path == "/v2/transcript":
            return httpx.Response(200, json={"id": "abc123"})
        if request.method == "GET" and request.url.path == "/v2/transcript/abc123":
            return httpx.Response(200, text="<html><body>502 Bad Gateway</body></html>")
        if request.method == "DELETE" and request.url.path == "/v2/transcript/abc123":
            return httpx.Response(200, json={"status": "deleted"})
        raise AssertionError(f"unexpected request: {request.method} {request.url.path}")

    engine = assemblyai_record_engine(
        mock_read_audio,
        MockStore(),
        transport=httpx.MockTransport(handler),
        poll_seconds=0.01,
    )

    with pytest.raises(AssemblyAIUnavailable, match="not JSON") as excinfo:
        await engine("session_123", "audio_ref_unused", [])

    assert "502 Bad Gateway" in str(excinfo.value)
    assert not isinstance(excinfo.value, json.JSONDecodeError)


@pytest.mark.asyncio
async def test_an_upload_that_never_became_a_transcript_is_reported_not_hidden() -> None:
    """Upload succeeded, submit failed: the client's meeting is on the vendor
    and there is nothing here that can remove it.

    `DELETE /v2/transcript/{id}` is the only deletion this API has, and it
    deletes the audio through the transcript — an upload with no transcript
    has no handle. That copy must therefore be discoverable rather than
    silent: the failure names the upload it left behind, and
    `run_record_path_transcription` persists that sentence as this engine's
    FAILED transcript.
    """

    deletes = [0]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/v2/upload":
            return httpx.Response(200, json={"upload_url": "https://cdn.assemblyai.com/upload/xyz"})
        if request.method == "POST" and request.url.path == "/v2/transcript":
            return httpx.Response(500, text="internal error")
        if request.method == "DELETE":
            deletes[0] += 1
            return httpx.Response(200, json={"status": "deleted"})
        raise AssertionError(f"unexpected request: {request.method} {request.url.path}")

    engine = assemblyai_record_engine(
        mock_read_audio,
        MockStore(),
        transport=httpx.MockTransport(handler),
        poll_seconds=0.01,
    )

    with pytest.raises(AssemblyAIUnavailable) as excinfo:
        await engine("session_123", "audio_ref_unused", [])

    message = str(excinfo.value)
    assert "https://cdn.assemblyai.com/upload/xyz" in message, (
        "the copy left on the vendor must be identified, not merely implied"
    )
    assert "500" in message, "the reason the submit failed is part of the record"
    assert deletes[0] == 0, "there is no transcript to delete, and no other handle"


@pytest.mark.asyncio
async def test_keyterm_prompting_switched_off_sends_no_word_boost() -> None:
    """`word_boost` is this vendor's counterpart to Deepgram's `keyterm`, and
    the same Settings switch governs both. Read nowhere in the repo before
    this, so an operator could turn the vocabulary off and every request still
    carried it."""

    from app.modules.settings.models import ConnectorSettings, ServiceSettings

    submitted_bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/v2/upload":
            return httpx.Response(200, json={"upload_url": "https://cdn.assemblyai.com/upload/xyz"})
        if request.method == "POST" and request.url.path == "/v2/transcript":
            submitted_bodies.append(json.loads(request.content))
            return httpx.Response(200, json={"id": "abc123"})
        if request.method == "GET" and request.url.path == "/v2/transcript/abc123":
            return httpx.Response(200, json=RESPONSE)
        if request.method == "DELETE" and request.url.path == "/v2/transcript/abc123":
            return httpx.Response(200, json={"status": "deleted"})
        raise AssertionError(f"unexpected request: {request.method} {request.url.path}")

    engine = assemblyai_record_engine(
        mock_read_audio,
        MockStore(
            settings=ServiceSettings(
                connectors=ConnectorSettings(keyterm_prompting=False)
            )
        ),
        transport=httpx.MockTransport(handler),
        poll_seconds=0.01,
    )

    await engine("session_123", "audio_ref_unused", ["FROSTLINE"])

    assert submitted_bodies[0]["word_boost"] == []
