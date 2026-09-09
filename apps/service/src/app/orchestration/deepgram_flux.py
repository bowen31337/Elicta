"""The live path as a stream, endpointed on turns rather than on a clock.

This replaces the fixed-window arrangement in `trigger/listener.py` for the
models that can do it, and the reason is latency measured rather than assumed.
A window is a buffer, and a buffer is a wait: nothing is recognised until the
window holding it is full, so the clock — not the recogniser — set how long an
operator waited. Recognising a window costs about 0.2s on this system; the
buffering either side of it cost five to nine seconds. The model was around
four per cent of the delay, which is why changing the model could not have
fixed it and this could.

What it buys beyond speed is the *shape* of what comes out. A fixed window cuts
speech wherever the clock lands, so one sentence arrives as two halves and the
trigger gate sees each alone; the shorter the window, the worse that gets.
Flux endpoints on turn boundaries from acoustic and semantic cues, so a
sentence arrives once, whole, when the speaker finishes it.

**The interface is deliberately the same as `LiveUtterances`.** One async
`feed(session_id, pcm)`, so `feed_live_lane` cannot tell which is underneath
and the composition root chooses per deployment.

Two things this does not pretend to fix:

*The upload chunk is still the floor.* Deepgram recommends 80ms of audio at a
time; the capture path posts a second at a time to our own service, so a second
is as fast as this can be however quick the model is. That is a real remaining
cost and it lives in `chunkUploader.ts`, not here.

*A dropped socket must not end the meeting.* Sockets fail; meetings are an
hour long. A failed send reconnects on the next chunk and the audio spoken
across the gap is lost, which is the honest trade — the alternative is
buffering an unbounded amount of a client's speech in memory against a vendor
that may not come back.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
from collections.abc import Awaitable, Callable
from typing import Any, NamedTuple
from urllib.parse import urlencode

# **Imported here rather than where it is used, and that is load-bearing.**
# It was a lazy import inside `_open`, which cost nothing at runtime and made
# the shipped app silently deaf: PyInstaller finds a frozen build's modules by
# reading the source, so an import it cannot see is a module it does not
# bundle. The desktop bundle went out with no `websockets` in it at all, and
# every attempt to open a socket raised `ModuleNotFoundError` inside the chunk
# handler, which swallows failures to protect the recording. Audio arrived,
# the lane reported itself ready, and not one line was ever transcribed.
#
# `test_deepgram_flux.py` asserts this import is at module scope, and
# `scripts/build-service-sidecar.sh` asserts the frozen binary can actually
# import it — the second because the first cannot see a freeze.
from websockets.asyncio.client import connect as websocket_connect

from app.modules.settings.models import SpeechVendor
from app.modules.settings.speech_resolution import resolve_speech_key

from .deepgram_engines import DeepgramUnavailable

logger = logging.getLogger(__name__)

LISTEN_URL = "wss://api.deepgram.com/v2/listen"

#: The models this client can drive. Flux is `/v2/listen` only — a Nova model
#: named here would connect and never produce a turn, so the set is closed and
#: the caller checks it rather than discovering the mistake mid-meeting.
FLUX_MODELS = frozenset({"flux-general-en", "flux-general-multi"})


#: How sure Flux must be that a speaker has finished before it ends the turn.
#:
#: **The vendor's default, and it was briefly 0.6.** Lowering it was the
#: obvious move when a whole sentence took a second to appear, and it was the
#: wrong lever: the vendor's own words for the lower range are "faster
#: responses, more false positives", and a false positive here is a turn that
#: ends mid-sentence. A meeting came back as a column of one- and two-word
#: lines — "two", "All", "Car", "Does", "So" — because almost every pause was
#: read as somebody finishing. It also costs accuracy twice over: each
#: fragment is recognised with no context from the words before it.
#:
#: The speed came from somewhere else in the end. Interim turns put words on
#: screen as they are spoken, so there is nothing left to buy by ending a turn
#: early — only coherence to lose.
EOT_THRESHOLD = 0.7
EOT_THRESHOLD_ENV = "ELICTA_FLUX_EOT_THRESHOLD"
EOT_THRESHOLD_RANGE = (0.5, 1.0)

#: How much silence forces a turn to end regardless of confidence.
#:
#: **The vendor's default, and it was briefly 1500ms.** A second and a half
#: sounds like a long pause and is not: it is somebody thinking, or drawing
#: breath mid-list, and every one of those became the end of a sentence.
#:
#: Five seconds is a long time to wait for a line to *settle*, and that no
#: longer matters — the words are already on screen from the interim turns.
#: What waits is the moment the sentence is handed to the gate, and the gate
#: is better served by a whole one.
EOT_TIMEOUT_MS = 5000
EOT_TIMEOUT_ENV = "ELICTA_FLUX_EOT_TIMEOUT_MS"
EOT_TIMEOUT_RANGE = (500, 60_000)


def _tuned(env: str, default: float, bounds: tuple[float, float]) -> float:
    """A tuning knob from the environment, clamped to what the vendor accepts.

    Clamped rather than passed through, and that is the point: an out-of-range
    value is a 400 on the socket, which this lane reports as the vendor being
    unreachable and an operator reads as a broken credential. A mistyped knob
    should cost a slightly wrong turn boundary, never a meeting.
    """

    raw = os.environ.get(env, "").strip()
    if not raw:
        return default
    try:
        configured = float(raw)
    except ValueError:
        return default
    return min(max(configured, bounds[0]), bounds[1])


def flux_listen_url(model: str, *, opt_out_of_retention: bool = True) -> str:
    """The socket URL, carrying the format and the retention opt-out.

    `encoding` and `sample_rate` restate what the capture path uploads, the
    same declaration `deepgram_listen_url` makes for the batch endpoint —
    Flux has no other way to know, and a wrong sample rate transcribes speech
    at the wrong speed rather than failing.

    `mip_opt_out` is NFR-2.3 and is set per request rather than left to the
    contract, so an audit can see it on the wire. A stream is one request that
    carries a whole meeting, which makes it the *most* important place for it
    rather than the least.
    """

    params = [
        ("model", model),
        ("encoding", "linear16"),
        ("sample_rate", "16000"),
        ("mip_opt_out", "true" if opt_out_of_retention else "false"),
        # When a turn ends, which is what an operator experiences as the
        # delay — the recognising itself is milliseconds.
        ("eot_threshold", f"{_tuned(EOT_THRESHOLD_ENV, EOT_THRESHOLD, EOT_THRESHOLD_RANGE):g}"),
        (
            "eot_timeout_ms",
            f"{int(_tuned(EOT_TIMEOUT_ENV, EOT_TIMEOUT_MS, EOT_TIMEOUT_RANGE))}",
        ),
    ]
    return f"{LISTEN_URL}?{urlencode(params)}"


class Turn(NamedTuple):
    """What one server message says about a turn in progress.

    `final` is the whole distinction. Flux narrates a turn as it forms and
    then confirms it, and the two are read very differently: an interim line
    is text that may still change and must never be reasoned about, a final
    one is a sentence somebody finished and is what the gate sees.
    """

    text: str
    index: int
    final: bool


def turn_of(message: Any) -> Turn | None:
    """The turn in one server message, interim or final, or `None`.

    **Interim turns are why a transcript can keep up with a room.** Waiting
    for `EndOfTurn` alone means nothing appears until Flux is sure the speaker
    has stopped — about a second after they do, and longer if they trail off —
    so the screen sat blank through every sentence and then printed it whole.
    `Update` carries the words so far, so the line grows as it is spoken.

    What does **not** change is what the rest of the system acts on. Only a
    final turn becomes an utterance the gate reads: a question raised from
    half a sentence is worse than one raised a moment later, and interim text
    is by definition text that may still be wrong.

    `EagerEndOfTurn` is deliberately not final either. It is Flux guessing
    early so a voice agent can start talking; here it is one more interim
    reading, and `TurnResumed` proves why — the speaker had not finished.
    """

    if not isinstance(message, dict) or message.get("type") != "TurnInfo":
        return None
    event = message.get("event")
    if event not in ("Update", "EagerEndOfTurn", "EndOfTurn"):
        return None
    text = str(message.get("transcript", "") or "").strip()
    index = message.get("turn_index")
    return Turn(text, int(index) if isinstance(index, int) else 0, event == "EndOfTurn")


def transcript_of(message: Any) -> str | None:
    """The finished turn in one server message, or `None` if it is not one.

    Flux narrates a turn as it forms — `StartOfTurn`, `Update`,
    `EagerEndOfTurn`, `TurnResumed` — and only `EndOfTurn` is a sentence
    somebody actually finished. The rest are speculation for a voice agent
    deciding when to interrupt, and this product has no use for a guess: a
    question surfaced from half a sentence is worse than one surfaced a moment
    later.
    """

    if not isinstance(message, dict):
        return None
    if message.get("type") != "TurnInfo" or message.get("event") != "EndOfTurn":
        return None
    text = str(message.get("transcript", "") or "").strip()
    # A turn can end with nothing in it — a cough, a door. Present-but-empty
    # is silence, not a failure, and the caller drops it as it drops a quiet
    # window on the other path.
    return text


Observe = Callable[[str, str, str | None], Awaitable[None]]
Identify = Callable[[str, bytes], Awaitable[str | None]]
Connect = Callable[..., Any]


class _Stream:
    """One meeting's socket, and the task reading turns off it."""

    def __init__(self, socket: Any, reader: asyncio.Task[None]) -> None:
        self.socket = socket
        self.reader = reader
        #: The audio this turn has been built from, for the voiceprint. Held
        #: because verification needs the samples the words came from and a
        #: stream hands over words alone — bounded, because an hour of a
        #: client's speech is not something to accumulate in memory for a
        #: comparison that looks at seconds.
        self.recent = bytearray()


class FluxUtterances:
    """`LiveUtterances`, streamed.

    Sockets are opened lazily on a meeting's first chunk rather than when a
    session starts: a meeting that is booked and never recorded should cost
    nothing, and the credential is read per connection so a key entered on the
    Settings screen takes effect on the next meeting without a restart.
    """

    #: How much recent audio to keep for speaker verification. Four seconds
    #: covers a turn long enough to characterise a voice; beyond that the
    #: embedder gains nothing and the memory is a client's speech.
    RECENT_BYTES = 32_000 * 4

    #: How long to wait after a failed open, doubling per consecutive failure.
    #: The floor is longer than a chunk so a single refusal cannot be retried
    #: by the very next one; the ceiling is short enough that a meeting
    #: recovers on its own once the vendor does.
    BACKOFF_FLOOR = 2.0
    BACKOFF_CEILING = 30.0

    def __init__(
        self,
        store: Any,
        observe: Observe,
        *,
        identify: Identify | None = None,
        model: str = "flux-general-en",
        connect: Connect | None = None,
    ) -> None:
        if model not in FLUX_MODELS:
            raise ValueError(f"{model} is not a Flux model; Flux is /v2/listen only")
        self._store = store
        self._observe = observe
        self._identify = identify
        self._model = model
        self._connect = connect
        self._streams: dict[str, _Stream] = {}
        #: When a meeting may next try to open a socket, and how many tries
        #: have failed in a row.
        #:
        #: **Without this a failed open is retried ten times a second.** A
        #: chunk arrives every hundred milliseconds and `feed` opens the socket
        #: on demand, so one refusal — a throttle, a network blink, a key
        #: rotated mid-meeting — became a flood of connection attempts at the
        #: vendor for the rest of the meeting. That is the shape that turns a
        #: momentary failure into a permanent one: the retries are what keep
        #: it refused.
        self._retry_after: dict[str, float] = {}
        self._failures: dict[str, int] = {}
        #: One lock per meeting, so two chunks arriving together open one
        #: socket rather than two. A second socket is a second bill and a
        #: transcript interleaved from two halves of the same room.
        self._opening: dict[str, asyncio.Lock] = {}

    async def feed(self, session_id: str, pcm: bytes) -> None:
        """Forward one chunk, opening the socket if this is the first."""

        stream = await self._stream_for(session_id)
        if stream is None:
            # Backing off. The audio goes nowhere, which is the honest answer
            # while there is nowhere for it to go — and the recording, which
            # is the part that outlives the meeting, was banked before this
            # lane ever saw the bytes.
            return
        stream.recent.extend(pcm)
        if len(stream.recent) > self.RECENT_BYTES:
            del stream.recent[: len(stream.recent) - self.RECENT_BYTES]
        try:
            await stream.socket.send(pcm)
        except Exception:  # noqa: BLE001 — every socket failure is the same here
            # Dropped rather than buffered, and reopened on the next chunk.
            # Holding audio against a vendor that may not come back grows
            # without bound in the one process that must not.
            logger.warning("the live stream for %s dropped; reopening", session_id)
            await self.close(session_id)

    def backing_off(self, session_id: str) -> bool:
        """Whether this meeting currently has no socket and is waiting to
        retry.

        Asked by the panel's lane frame. Without it a vendor that has stopped
        answering is indistinguishable on screen from a quiet room: the lane
        reports itself ready — a credential *is* configured — audio keeps
        arriving, and no line ever appears. That is the failure this product
        keeps finding, and it is the one an operator can least afford to
        discover afterwards.
        """

        return time.monotonic() < self._retry_after.get(session_id, 0.0)

    async def close(self, session_id: str) -> None:
        """End one meeting's stream, if it has one."""

        stream = self._streams.pop(session_id, None)
        if stream is None:
            return
        stream.reader.cancel()
        with contextlib.suppress(Exception):
            await stream.socket.close()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await stream.reader

    async def aclose(self) -> None:
        """End every stream. For a service shutting down."""

        for session_id in list(self._streams):
            await self.close(session_id)

    async def _stream_for(self, session_id: str) -> _Stream | None:
        existing = self._streams.get(session_id)
        if existing is not None:
            return existing
        if time.monotonic() < self._retry_after.get(session_id, 0.0):
            return None
        lock = self._opening.setdefault(session_id, asyncio.Lock())
        async with lock:
            # Re-checked inside the lock: the whole point of the lock is that
            # two chunks raced here, and the loser must take the winner's
            # socket rather than opening a second.
            existing = self._streams.get(session_id)
            if existing is not None:
                return existing
            try:
                stream = await self._open(session_id)
            except Exception:
                failures = self._failures.get(session_id, 0) + 1
                self._failures[session_id] = failures
                wait = min(self.BACKOFF_CEILING, self.BACKOFF_FLOOR * 2 ** (failures - 1))
                self._retry_after[session_id] = time.monotonic() + wait
                # Logged here rather than left to the caller: above this the
                # exception is swallowed to protect the recording, so this is
                # the last place it can be said at all.
                logger.warning(
                    "could not open the live stream for %s (attempt %d); "
                    "waiting %.0fs before trying again",
                    session_id,
                    failures,
                    wait,
                )
                raise
            self._failures.pop(session_id, None)
            self._retry_after.pop(session_id, None)
            self._streams[session_id] = stream
            return stream

    async def _open(self, session_id: str) -> _Stream:
        key = resolve_speech_key(self._store, SpeechVendor.DEEPGRAM)
        if key is None:
            raise DeepgramUnavailable("no Deepgram credential is configured")
        connectors = self._store.read().connectors
        url = flux_listen_url(
            self._model,
            opt_out_of_retention=connectors.disable_vendor_retention,
        )
        connect = self._connect or websocket_connect
        socket = await connect(url, additional_headers={"Authorization": f"Token {key}"})
        reader = asyncio.create_task(self._read(session_id, socket))
        return _Stream(socket, reader)

    async def _read(self, session_id: str, socket: Any) -> None:
        """Turn every finished turn into an utterance, until the socket ends.

        Its own task rather than read inside `feed`, because turns do not
        arrive on the same schedule as chunks: a speaker who talks through
        three chunks produces one turn, and one who stops mid-chunk produces a
        turn with no chunk to carry it out on.
        """

        try:
            async for raw in socket:
                turn = turn_of(_parsed(raw))
                if turn is None or not turn.text:
                    continue
                # Only asked for a finished turn. Verification is 200ms of
                # pure Python against a window of audio, and running it on
                # every interim update would spend it several times a sentence
                # to answer a question nobody has asked yet — the line is not
                # attributed until it is a line.
                speaker = await self._speaker(session_id) if turn.final else None
                await self._observe(
                    session_id, turn.text, speaker, turn=turn.index, final=turn.final
                )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("the live stream for %s ended", session_id)
        finally:
            # **Dropped, so the next chunk opens a new one.** This said it was
            # "left closed. The next chunk reopens" and nothing closed it, so
            # the reader ending left a socket in place that `feed` went on
            # sending into and nobody read. The meeting transcribed two or
            # three turns and then went silent for good — no error, no
            # reconnection, and audio still arriving at the service the whole
            # time. Everything upstream reported success.
            #
            # This runs for *any* end, not just an exception: the vendor
            # closing the socket is the ordinary case, and it left the same
            # deaf stream behind.
            #
            # Identity-checked, because `close()` cancels this task and has
            # already taken the entry — without the check this would drop a
            # stream that a later chunk had legitimately opened.
            stream = self._streams.get(session_id)
            if stream is not None and stream.reader is asyncio.current_task():
                del self._streams[session_id]
                with contextlib.suppress(Exception):
                    await stream.socket.close()

    async def _speaker(self, session_id: str) -> str | None:
        if self._identify is None:
            return None
        stream = self._streams.get(session_id)
        if stream is None or not stream.recent:
            return None
        return await self._identify(session_id, bytes(stream.recent))


def _parsed(raw: Any) -> Any:
    """The message as JSON, or `None` for anything that is not.

    Flux sends text frames; a binary frame or malformed JSON is not a turn and
    must not stop the reader — one bad frame would otherwise end the
    transcript for the rest of the meeting.
    """

    if isinstance(raw, bytes | bytearray):
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None
