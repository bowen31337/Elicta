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
import contextlib
import json
import time

import pytest

from app.modules.settings.models import LiveSpeechModel, SecretKey
from app.modules.settings.store import InMemorySettingsStore
from app.orchestration.deepgram_flux import (
    EOT_THRESHOLD_ENV,
    EOT_TIMEOUT_ENV,
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


async def _noop(session_id: str, text: str, speaker: str | None, **kwargs: object) -> None:
    return None


# --- the stream ----------------------------------------------------------


@pytest.mark.asyncio
async def test_a_finished_turn_reaches_the_panel() -> None:
    heard: list[tuple[str, str, str | None]] = []

    async def observe(
        session_id: str, text: str, speaker: str | None, **kwargs: object
    ) -> None:
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


def test_the_socket_library_is_imported_where_a_freeze_can_see_it() -> None:
    """The shipped app was deaf for a build because of a lazy import.

    PyInstaller finds a frozen build's modules by *reading the source*, so an
    import inside a function is an import it does not see and a module it does
    not bundle. `websockets` was imported inside `_open`, the desktop bundle
    went out without it, and every attempt to open a socket raised
    `ModuleNotFoundError` inside the chunk handler — which swallows failures
    to protect the recording. Audio arrived, the lane reported itself ready,
    and not one line was ever transcribed.

    Asserted against the source text rather than by importing, because
    importing proves only that *this* interpreter can find it, which was never
    in doubt. What has to be true is that the import is written where a static
    reader will find it.

    This cannot see a freeze. `scripts/build-service-sidecar.sh` checks the
    frozen binary itself, which is the other half.
    """

    import pathlib

    source = pathlib.Path(__file__).with_name("deepgram_flux.py").read_text()
    body = source[: source.index("def flux_listen_url")]

    assert "from websockets" in body, "the socket library must be imported at module scope"


def test_no_import_hides_inside_a_function_in_this_module() -> None:
    """The general form of the rule, so the next one is caught too."""

    import pathlib
    import re

    source = pathlib.Path(__file__).with_name("deepgram_flux.py").read_text()
    hidden = [
        line.strip()
        for line in source.splitlines()
        # Indented, so inside something; and an import, so invisible to a
        # static reader walking the module's top level.
        if re.match(r"\s+(import |from \S+ import )", line)
    ]

    assert hidden == [], f"these imports cannot be seen by a freeze: {hidden}"


@pytest.mark.asyncio
async def test_a_stream_whose_reader_ends_is_reopened_on_the_next_chunk() -> None:
    """The meeting transcribed two turns and then went silent for good.

    A socket the vendor closes ends the reader task. Left in place, `feed`
    goes on sending into it perfectly happily and nobody reads a word back —
    so audio kept arriving at the service, every part of the chain reported
    success, and the transcript simply stopped. There is no error to see
    because nothing failed; the stream was merely deaf.
    """

    class _EndsAfterOne(_Socket):
        """A socket that delivers one turn and then closes, as a vendor does."""

        async def __anext__(self) -> object:
            if self._messages:
                return self._messages.pop(0)
            self._delivered.set()
            raise StopAsyncIteration

    heard: list[str] = []

    async def observe(
        session_id: str, text: str, speaker: str | None, **kwargs: object
    ) -> None:
        heard.append(text)

    opened: list[_Socket] = []

    async def connect(url: str, **kwargs: object):
        opened.append(_EndsAfterOne([_turn(f"turn {len(opened) + 1}")]))
        return opened[-1]

    lane = FluxUtterances(_store(), observe, connect=connect)

    await lane.feed("meeting-1", WINDOW)
    await opened[0].drained()
    await asyncio.sleep(0)

    # The next chunk finds no stream and opens a fresh one, rather than
    # sending into the dead one for the rest of the meeting.
    await lane.feed("meeting-1", WINDOW)
    await opened[1].drained()
    await asyncio.sleep(0)

    assert len(opened) == 2
    assert heard == ["turn 1", "turn 2"]
    await lane.aclose()


@pytest.mark.asyncio
async def test_closing_a_meeting_is_not_mistaken_for_a_dead_reader() -> None:
    """`close()` cancels the reader, which runs the same teardown. Without an
    identity check the two race, and the loser drops a stream a later chunk
    had legitimately opened."""

    socket = _Socket()
    connect, _ = _connector(socket)
    lane = FluxUtterances(_store(), _noop, connect=connect)
    await lane.feed("meeting-1", WINDOW)

    await lane.close("meeting-1")
    await asyncio.sleep(0)

    assert socket.closed is True
    assert lane._streams == {}


# --- when a turn ends, which is the whole of the perceived delay ---------


def test_a_turn_is_allowed_to_finish_before_it_is_called_finished() -> None:
    """These were tuned down for speed and it was the wrong lever.

    At `eot_threshold=0.6` and `eot_timeout_ms=1500` a meeting came back as a
    column of one- and two-word lines — "two", "All", "Car", "Does", "So" —
    because almost every pause for breath was read as somebody finishing. The
    vendor's own words for the lower range are "faster responses, more false
    positives", and a false positive here is a turn ending mid-sentence. It
    costs accuracy twice: each fragment is then recognised with no context
    from the words before it.

    The speed came from interim turns instead, which put words on screen as
    they are spoken — so there is nothing left to buy by ending a turn early,
    and only coherence to lose.
    """

    url = flux_listen_url("flux-general-en")

    assert "eot_threshold=0.7" in url
    assert "eot_timeout_ms=5000" in url


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        ("0.5", "eot_threshold=0.5"),
        ("0.9", "eot_threshold=0.9"),
        # Below the vendor's floor and above its ceiling: clamped, never sent.
        ("0.1", "eot_threshold=0.5"),
        ("2", "eot_threshold=1"),
        ("nonsense", "eot_threshold=0.7"),
    ],
)
def test_the_threshold_is_tunable_and_can_never_be_out_of_range(
    monkeypatch: pytest.MonkeyPatch, configured: str, expected: str
) -> None:
    """Clamped rather than passed through.

    An out-of-range value is a 400 on the socket, which this lane reports as
    the vendor being unreachable and an operator reads as a broken
    credential — sending them to replace a key that was fine. A mistyped knob
    should cost a slightly wrong turn boundary, never a meeting.
    """

    monkeypatch.setenv(EOT_THRESHOLD_ENV, configured)

    assert expected in flux_listen_url("flux-general-en")


@pytest.mark.parametrize(
    ("configured", "expected"),
    [("500", 500), ("60000", 60_000), ("10", 500), ("999999", 60_000), ("", 5000)],
)
def test_the_silence_timeout_is_tunable_within_the_vendor_range(
    monkeypatch: pytest.MonkeyPatch, configured: str, expected: int
) -> None:
    monkeypatch.setenv(EOT_TIMEOUT_ENV, configured)

    assert f"eot_timeout_ms={expected}" in flux_listen_url("flux-general-en")


# --- a failure that must not make itself permanent ----------------------


@pytest.mark.asyncio
async def test_a_failed_open_is_not_retried_by_the_very_next_chunk() -> None:
    """One refusal became a flood, and the flood is what kept it refused.

    A chunk arrives every hundred milliseconds and the socket is opened on
    demand, so a single failure — a throttle, a network blink, a key rotated
    mid-meeting — meant ten connection attempts a second at the vendor for the
    rest of the meeting. That is the shape that turns a momentary failure into
    a permanent one.
    """

    attempts = 0

    async def refuses(url: str, **kwargs: object):
        nonlocal attempts
        attempts += 1
        raise ConnectionError("refused")

    lane = FluxUtterances(_store(), _noop, connect=refuses)

    for _ in range(20):  # two seconds of chunks
        with contextlib.suppress(Exception):
            await lane.feed("meeting-1", WINDOW)

    assert attempts == 1, f"the vendor was asked {attempts} times for one failure"


@pytest.mark.asyncio
async def test_the_wait_grows_with_each_consecutive_failure() -> None:
    """A vendor that is down stays down for minutes, not milliseconds."""

    async def refuses(url: str, **kwargs: object):
        raise ConnectionError("refused")

    lane = FluxUtterances(_store(), _noop, connect=refuses)
    waits = []
    for _ in range(4):
        lane._retry_after.clear()  # as if the wait had elapsed
        with contextlib.suppress(Exception):
            await lane.feed("meeting-1", WINDOW)
        waits.append(round(lane._retry_after["meeting-1"] - time.monotonic()))

    assert waits == sorted(waits) and waits[0] < waits[-1], waits
    assert waits[-1] <= lane.BACKOFF_CEILING


@pytest.mark.asyncio
async def test_a_meeting_recovers_once_the_vendor_does() -> None:
    """Backing off must not become giving up: the operator is still talking,
    and nothing else will reopen this."""

    failing = True

    async def sometimes(url: str, **kwargs: object):
        if failing:
            raise ConnectionError("refused")
        return _Socket()

    lane = FluxUtterances(_store(), _noop, connect=sometimes)
    with contextlib.suppress(Exception):
        await lane.feed("meeting-1", WINDOW)
    assert lane._streams == {}

    failing = False
    lane._retry_after.clear()  # as if the wait had elapsed
    await lane.feed("meeting-1", WINDOW)

    assert "meeting-1" in lane._streams
    # And the count is forgotten, so the next hiccup starts from the floor
    # rather than from half a minute.
    assert "meeting-1" not in lane._failures
    await lane.aclose()


@pytest.mark.asyncio
async def test_audio_arriving_during_a_backoff_is_dropped_not_queued() -> None:
    """There is nowhere for it to go, and holding it grows without bound in
    the one process that must not. The recording is untouched — it is banked
    before this lane sees a byte."""

    async def refuses(url: str, **kwargs: object):
        raise ConnectionError("refused")

    lane = FluxUtterances(_store(), _noop, connect=refuses)
    with contextlib.suppress(Exception):
        await lane.feed("meeting-1", WINDOW)

    # Returns quietly rather than raising once the backoff is in force.
    await lane.feed("meeting-1", WINDOW)
