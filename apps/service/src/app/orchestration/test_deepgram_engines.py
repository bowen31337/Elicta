"""Deepgram on the record path (spec §5.4a).

The response fixture below is the shape a real 90-minute run returned, trimmed
to two utterances. No test here makes a live call.
"""

from __future__ import annotations

import httpx
import pytest

from app.orchestration.deepgram_engines import (
    DeepgramUnavailable,
    deepgram_listen_url,
    deepgram_record_engine,
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


class _DefaultSettings:
    """The settings half of a store double: everything at its default.

    Both engines read `connectors` per call now — `keyterm_prompting` and
    `disable_vendor_retention` are operator-facing switches, so what they are
    set to has to reach the request — and every double below only ever cared
    about the credential.
    """

    def read(self):
        from app.modules.settings.models import ServiceSettings

        return ServiceSettings()


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


@pytest.mark.asyncio
async def test_a_successful_call_returns_batch_transcription_output() -> None:
    """Tests that _listen and to_batch_transcription are wired together."""

    def mock_read_audio(session_id: str) -> bytes:
        return b"mock audio data"

    class MockStore(_DefaultSettings):
        def get_secret(self, key):
            from app.modules.settings.models import SecretValue
            return SecretValue("test_key")

    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json=RESPONSE)
    )

    engine = deepgram_record_engine(
        mock_read_audio,
        MockStore(),
        transport=transport,
    )
    output = await engine("session_123", "audio_ref_unused", ["FROSTLINE"])

    assert output.engine == "deepgram"
    assert len(output.segments) == 2
    assert output.segments[0].text == "Yeah, the dock rule is fifteen minutes."
    assert output.segments[1].text == "Is that written down anywhere?"


@pytest.mark.asyncio
async def test_a_504_response_raises_deepgram_unavailable_with_timeout_message() -> None:
    """504 timeout is distinguished from other HTTP errors in the message."""

    def mock_read_audio(session_id: str) -> bytes:
        return b"mock audio"

    class MockStore(_DefaultSettings):
        def get_secret(self, key):
            from app.modules.settings.models import SecretValue
            return SecretValue("test_key")

    transport = httpx.MockTransport(
        lambda request: httpx.Response(504)
    )

    engine = deepgram_record_engine(
        mock_read_audio,
        MockStore(),
        transport=transport,
    )

    with pytest.raises(DeepgramUnavailable, match="timed out"):
        await engine("session_123", "audio_ref_unused", [])


@pytest.mark.asyncio
async def test_a_401_response_raises_deepgram_unavailable_with_status_code() -> None:
    """Non-200 errors other than 504 include the status code."""

    def mock_read_audio(session_id: str) -> bytes:
        return b"mock audio"

    class MockStore(_DefaultSettings):
        def get_secret(self, key):
            from app.modules.settings.models import SecretValue
            return SecretValue("test_key")

    transport = httpx.MockTransport(
        lambda request: httpx.Response(401)
    )

    engine = deepgram_record_engine(
        mock_read_audio,
        MockStore(),
        transport=transport,
    )

    with pytest.raises(DeepgramUnavailable, match="401"):
        await engine("session_123", "audio_ref_unused", [])


@pytest.mark.asyncio
async def test_no_audio_raises_before_any_request() -> None:
    """Empty audio fails closed before reaching the network."""

    call_count = [0]

    def mock_read_audio(session_id: str) -> bytes:
        return b""

    class MockStore(_DefaultSettings):
        def get_secret(self, key):
            from app.modules.settings.models import SecretValue
            return SecretValue("test_key")

    def counting_transport(request):
        call_count[0] += 1
        return httpx.Response(200, json=RESPONSE)

    transport = httpx.MockTransport(counting_transport)

    engine = deepgram_record_engine(
        mock_read_audio,
        MockStore(),
        transport=transport,
    )

    with pytest.raises(DeepgramUnavailable, match="nothing to transcribe"):
        await engine("session_123", "audio_ref_unused", [])

    assert call_count[0] == 0, "transport was called when audio was empty"


@pytest.mark.asyncio
async def test_no_credential_raises_before_any_request() -> None:
    """Missing Deepgram credential fails closed before reaching the network."""

    call_count = [0]

    def mock_read_audio(session_id: str) -> bytes:
        return b"mock audio"

    class MockStore(_DefaultSettings):
        def get_secret(self, key):
            return None

    def counting_transport(request):
        call_count[0] += 1
        return httpx.Response(200, json=RESPONSE)

    transport = httpx.MockTransport(counting_transport)

    engine = deepgram_record_engine(
        mock_read_audio,
        MockStore(),
        transport=transport,
    )

    with pytest.raises(DeepgramUnavailable, match="credential"):
        await engine("session_123", "audio_ref_unused", [])

    assert call_count[0] == 0, "transport was called when credential was missing"


def test_consecutive_utterances_by_one_speaker_become_one_turn() -> None:
    """A `SpeakerTurn` is a continuous stretch attributed to one speaker, so
    two adjacent utterances from the same person are one turn, not two."""

    from app.orchestration.deepgram_engines import to_speaker_turns

    payload = {
        "results": {
            "channels": [{"alternatives": [{"transcript": "..."}]}],
            "utterances": [
                {"start": 0.0, "end": 2.0, "speaker": 0, "transcript": "a"},
                {"start": 2.0, "end": 4.0, "speaker": 0, "transcript": "b"},
                {"start": 4.0, "end": 6.0, "speaker": 1, "transcript": "c"},
            ],
        }
    }

    output = to_speaker_turns(payload, "deepgram")

    assert output.engine == "deepgram"
    assert [(t.start_seconds, t.end_seconds, t.speaker_tag) for t in output.turns] == [
        (0.0, 4.0, "0"),
        (4.0, 6.0, "1"),
    ]


def test_a_speaker_returning_later_starts_a_new_turn() -> None:
    """Merging by speaker alone would collapse a conversation into two turns."""

    from app.orchestration.deepgram_engines import to_speaker_turns

    payload = {
        "results": {
            "channels": [{"alternatives": [{"transcript": "..."}]}],
            "utterances": [
                {"start": 0.0, "end": 1.0, "speaker": 0, "transcript": "a"},
                {"start": 1.0, "end": 2.0, "speaker": 1, "transcript": "b"},
                {"start": 2.0, "end": 3.0, "speaker": 0, "transcript": "c"},
            ],
        }
    }

    output = to_speaker_turns(payload, "deepgram")

    assert [t.speaker_tag for t in output.turns] == ["0", "1", "0"]


@pytest.mark.asyncio
async def test_deepgram_diarizer_returns_merged_turns_from_the_mocked_response() -> None:
    """End-to-end: `deepgram_diarizer` is actually wired to `to_speaker_turns`,
    not just a same-shaped copy tested by nothing."""

    from app.orchestration.deepgram_engines import deepgram_diarizer

    def mock_read_audio(session_id: str) -> bytes:
        return b"mock audio data"

    class MockStore(_DefaultSettings):
        def get_secret(self, key):
            from app.modules.settings.models import SecretValue
            return SecretValue("test_key")

    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json=RESPONSE)
    )

    diarize = deepgram_diarizer(
        mock_read_audio,
        MockStore(),
        transport=transport,
    )
    output = await diarize("session_123", "audio_ref_unused")

    assert output.engine == "deepgram"
    assert [(t.start_seconds, t.end_seconds, t.speaker_tag) for t in output.turns] == [
        (0.0, 3.84, "0"),
        (3.9, 6.2, "1"),
    ]


def _store_with(**connector_options):
    """A real settings store with these connector switches set."""

    from app.modules.settings.models import ConnectorSettings, SecretKey
    from app.modules.settings.store import InMemorySettingsStore

    store = InMemorySettingsStore()
    store.write_connectors(ConnectorSettings(**connector_options))
    store.set_secret(SecretKey.DEEPGRAM_API_KEY, "dg")
    return store


@pytest.mark.asyncio
async def test_keyterm_prompting_switched_off_sends_no_keyterms() -> None:
    """The switch is on the Settings screen, so it has to reach the request.

    It was read nowhere in the repo: an operator could toggle it, save it, see
    it saved, and every request still carried the vocabulary. A switch that
    does nothing is worse than one that is not offered.
    """

    urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        return httpx.Response(200, json=RESPONSE)

    engine = deepgram_record_engine(
        lambda _session: b"mock audio data",
        _store_with(keyterm_prompting=False),
        transport=httpx.MockTransport(handler),
    )

    await engine("session_123", "audio_ref_unused", ["FROSTLINE"])

    assert "keyterm=" not in urls[0]


@pytest.mark.asyncio
async def test_keyterm_prompting_left_on_sends_them() -> None:
    """The default, and the case the accuracy of a real meeting rests on."""

    urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        return httpx.Response(200, json=RESPONSE)

    engine = deepgram_record_engine(
        lambda _session: b"mock audio data",
        _store_with(),
        transport=httpx.MockTransport(handler),
    )

    await engine("session_123", "audio_ref_unused", ["FROSTLINE"])

    assert "keyterm=FROSTLINE" in urls[0]


@pytest.mark.asyncio
async def test_the_retention_switch_reaches_the_request() -> None:
    """`disable_vendor_retention` is what `mip_opt_out` says on the wire.

    Hardcoding the opt-out on would be defensible; hardcoding it while
    offering the operator a switch that changes nothing is not — the audit
    §14.1 asks for reads the request, and the request would have disagreed
    with the screen.
    """

    urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        return httpx.Response(200, json=RESPONSE)

    engine = deepgram_record_engine(
        lambda _session: b"mock audio data",
        _store_with(disable_vendor_retention=False),
        transport=httpx.MockTransport(handler),
    )

    await engine("session_123", "audio_ref_unused", [])

    assert "mip_opt_out=false" in urls[0]
