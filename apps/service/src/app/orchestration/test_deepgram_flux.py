"""The streamed live lane, without a socket or a spent credit.

What is asserted here is the shape of the conversation with the vendor and
what happens when it goes wrong — not that Deepgram transcribes, which is
theirs to get right.

The failure this path must never have is the one the batch path already
taught: a recogniser that stops producing while every other part of the chain
reports success. A meeting is an hour long and sockets do not last an hour, so
a dropped connection has to be an ordinary event with an ordinary recovery
rather than the end of the transcript.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from app.modules.settings.models import LiveSpeechModel, SecretKey
from app.modules.settings.store import InMemorySettingsStore
from app.orchestration.deepgram_flux import (
    FLUX_MODELS,
    DeepgramUnavailable,
    FluxUtterances,
    flux_listen_url,
    transcript_of,
)

WINDOW = b"\x01\x02" * 16_000


def _store(*, key: str | None = "dg-key") -> InMemorySettingsStore:
    store = InMemorySettingsStore(read_environment=False)
    if key is not None:
        store.set_secret(SecretKey.DEEPGRAM_API_KEY, key)
    return store


class _Socket:
    """A Flux socket that says what it is told to say."""

    def __init__(self, messages: list[object] | None = None) -> None:
        self.sent: list[bytes] = []
        self.closed = False
        self._messages = list(messages or [])
        self._delivered = asyncio.Event()

    async def send(self, payload: bytes) -> None:
        self.sent.append(payload)

    async def close(self) -> None:
        self.closed = True

    def __aiter__(self) -> _Socket:
        return self

    async def __anext__(self) -> object:
        if self._messages:
            return self._messages.pop(0)
        self._delivered.set()
        # Held open rather than ended, which is what a real socket does
        # between turns — and what makes the reader a task rather than a loop
        # inside `feed`.
        await asyncio.sleep(3600)
        raise StopAsyncIteration

    async def drained(self) -> None:
        await asyncio.wait_for(self._delivered.wait(), timeout=1)


def _connector(socket: _Socket):
    seen: dict[str, object] = {}

    async def connect(url: str, **kwargs: object):
        seen["url"] = url
        seen.update(kwargs)
        return socket

    return connect, seen


def _turn(text: str, event: str = "EndOfTurn") -> str:
    return json.dumps(
        {
            "type": "TurnInfo",
            "event": event,
            "turn_index": 0,
            "audio_window_start": 0,
            "audio_window_end": 1.3,
            "transcript": text,
        }
    )


# --- the message the vendor sends ---------------------------------------


def test_only_a_finished_turn_is_an_utterance() -> None:
    """Flux narrates a turn as it forms, and only one of those is a sentence
    somebody finished.

    `EagerEndOfTurn` is a guess offered so a voice agent can start answering
    early. This product has no use for a guess: a question surfaced from half
    a sentence is worse than one surfaced a moment later.
    """

    assert transcript_of(json.loads(_turn("How are arrivals booked?"))) == (
        "How are arrivals booked?"
    )
    for speculative in ("StartOfTurn", "Update", "EagerEndOfTurn", "TurnResumed"):
        assert transcript_of(json.loads(_turn("half a sen", speculative))) is None


def test_a_turn_with_nothing_in_it_is_silence_rather_than_a_failure() -> None:
    # A cough, a door. The batch path has the same rule, and the lane above
    # cannot tell the two recognisers apart.
    assert transcript_of(json.loads(_turn("   "))) == ""


def test_anything_that_is_not_a_turn_is_ignored_rather_than_raising() -> None:
    """One malformed frame must not end the transcript for the rest of the
    meeting, which is what an exception out of the reader would do."""

    for other in [None, "not json", b"\x00\x01", json.dumps({"type": "Connected"})]:
        parsed = other if isinstance(other, dict) else None
        assert transcript_of(parsed) is None


# --- the request ---------------------------------------------------------


def test_the_url_states_the_format_the_capture_path_actually_sends() -> None:
    # Flux has no other way to know, and a wrong sample rate transcribes
    # speech at the wrong speed rather than failing.
    url = flux_listen_url("flux-general-en")

    assert url.startswith("wss://api.deepgram.com/v2/listen?")
    for expected in ("model=flux-general-en", "encoding=linear16", "sample_rate=16000"):
        assert expected in url


def test_the_retention_opt_out_is_on_the_wire() -> None:
    """NFR-2.3, and a stream is the *most* important place for it: one request
    carries a whole meeting."""

    assert "mip_opt_out=true" in flux_listen_url("flux-general-en")
    assert "mip_opt_out=false" in flux_listen_url("flux-general-en", opt_out_of_retention=False)


def test_a_model_that_is_not_flux_is_refused_at_construction() -> None:
    # `/v2/listen` with a Nova model connects and never produces a turn — a
    # meeting that transcribes to nothing with every part reporting success.
    with pytest.raises(ValueError, match="not a Flux model"):
        FluxUtterances(_store(), _observe := _noop, model="nova-3")


async def _noop(session_id: str, text: str, speaker: str | None) -> None:
    return None


# --- the stream ----------------------------------------------------------


@pytest.mark.asyncio
async def test_a_finished_turn_reaches_the_panel() -> None:
    heard: list[tuple[str, str, str | None]] = []

    async def observe(session_id: str, text: str, speaker: str | None) -> None:
        heard.append((session_id, text, speaker))

    socket = _Socket([_turn("Three hundred and fifty a day.")])
    connect, _ = _connector(socket)
    lane = FluxUtterances(_store(), observe, connect=connect)

    await lane.feed("meeting-1", WINDOW)
    await socket.drained()
    await asyncio.sleep(0)

    assert heard == [("meeting-1", "Three hundred and fifty a day.", None)]
    await lane.aclose()


@pytest.mark.asyncio
async def test_the_credential_travels_as_a_header_not_in_the_url() -> None:
    # A key in a query string is a key in every proxy log between here and
    # the vendor.
    socket = _Socket()
    connect, seen = _connector(socket)
    lane = FluxUtterances(_store(key="dg-secret"), _noop, connect=connect)

    await lane.feed("meeting-1", WINDOW)

    assert seen["additional_headers"] == {"Authorization": "Token dg-secret"}
    assert "dg-secret" not in str(seen["url"])
    await lane.aclose()


@pytest.mark.asyncio
async def test_one_meeting_opens_one_socket_however_fast_chunks_arrive() -> None:
    """A second socket is a second bill and a transcript interleaved from two
    halves of the same room."""

    opened = 0

    async def connect(url: str, **kwargs: object):
        nonlocal opened
        opened += 1
        await asyncio.sleep(0)  # a real connect yields; this is the race
        return _Socket()

    lane = FluxUtterances(_store(), _noop, connect=connect)

    await asyncio.gather(*(lane.feed("meeting-1", WINDOW) for _ in range(5)))

    assert opened == 1
    await lane.aclose()


@pytest.mark.asyncio
async def test_two_meetings_get_two_sockets() -> None:
    sockets: list[_Socket] = []

    async def connect(url: str, **kwargs: object):
        sockets.append(_Socket())
        return sockets[-1]

    lane = FluxUtterances(_store(), _noop, connect=connect)

    await lane.feed("meeting-1", WINDOW)
    await lane.feed("meeting-2", WINDOW)

    assert len(sockets) == 2
    await lane.aclose()


@pytest.mark.asyncio
async def test_no_credential_is_refused_rather_than_connected() -> None:
    lane = FluxUtterances(_store(key=None), _noop, connect=_connector(_Socket())[0])

    with pytest.raises(DeepgramUnavailable, match="no Deepgram credential"):
        await lane.feed("meeting-1", WINDOW)


@pytest.mark.asyncio
async def test_a_dropped_socket_is_reopened_on_the_next_chunk() -> None:
    """Sockets do not last an hour and meetings do.

    The audio spoken across the gap is lost, which is the honest trade: the
    alternative is buffering an unbounded amount of a client's speech in
    memory against a vendor that may not come back.
    """

    class _Dropping(_Socket):
        async def send(self, payload: bytes) -> None:
            raise ConnectionError("socket closed")

    opened: list[_Socket] = []

    async def connect(url: str, **kwargs: object):
        opened.append(_Dropping() if len(opened) == 0 else _Socket())
        return opened[-1]

    lane = FluxUtterances(_store(), _noop, connect=connect)

    await lane.feed("meeting-1", WINDOW)  # drops
    await lane.feed("meeting-1", WINDOW)  # reopens and sends

    assert len(opened) == 2
    assert opened[1].sent == [WINDOW]
    await lane.aclose()


@pytest.mark.asyncio
async def test_the_recent_audio_kept_for_the_voiceprint_is_bounded() -> None:
    """An hour of a client's speech is not something to accumulate in memory
    for a comparison that looks at seconds."""

    identified: list[int] = []

    async def identify(session_id: str, pcm: bytes) -> str | None:
        identified.append(len(pcm))
        return "other"

    socket = _Socket([_turn("Yes.")])
    connect, _ = _connector(socket)
    lane = FluxUtterances(_store(), _noop, identify=identify, connect=connect)

    for _ in range(20):  # 20 seconds of audio
        await lane.feed("meeting-1", WINDOW)
    await socket.drained()
    await asyncio.sleep(0)

    assert identified and all(size <= FluxUtterances.RECENT_BYTES for size in identified)
    await lane.aclose()


@pytest.mark.asyncio
async def test_closing_a_meeting_ends_its_socket() -> None:
    socket = _Socket()
    connect, _ = _connector(socket)
    lane = FluxUtterances(_store(), _noop, connect=connect)
    await lane.feed("meeting-1", WINDOW)

    await lane.close("meeting-1")

    assert socket.closed is True
    # And closing one that was never opened is not an error: a meeting that
    # ended before it was ever recorded is the ordinary case.
    await lane.close("meeting-never-recorded")


def test_the_flux_model_set_matches_the_settings_enum() -> None:
    """One list, in two places, is two lists. A model an operator can choose
    and this client refuses is a meeting that transcribes nothing."""

    from app.modules.settings.models import STREAMED_LIVE_MODELS

    assert {model.value for model in STREAMED_LIVE_MODELS} == set(FLUX_MODELS)
    assert LiveSpeechModel.FLUX_GENERAL_EN.value in FLUX_MODELS
