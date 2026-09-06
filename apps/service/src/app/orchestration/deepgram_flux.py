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
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlencode

from app.modules.settings.models import SpeechVendor
from app.modules.settings.speech_resolution import resolve_speech_key

from .deepgram_engines import DeepgramUnavailable

logger = logging.getLogger(__name__)

LISTEN_URL = "wss://api.deepgram.com/v2/listen"

#: The models this client can drive. Flux is `/v2/listen` only — a Nova model
#: named here would connect and never produce a turn, so the set is closed and
#: the caller checks it rather than discovering the mistake mid-meeting.
FLUX_MODELS = frozenset({"flux-general-en", "flux-general-multi"})


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
    ]
    return f"{LISTEN_URL}?{urlencode(params)}"


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
        #: One lock per meeting, so two chunks arriving together open one
        #: socket rather than two. A second socket is a second bill and a
        #: transcript interleaved from two halves of the same room.
        self._opening: dict[str, asyncio.Lock] = {}

    async def feed(self, session_id: str, pcm: bytes) -> None:
        """Forward one chunk, opening the socket if this is the first."""

        stream = await self._stream_for(session_id)
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

    async def _stream_for(self, session_id: str) -> _Stream:
        existing = self._streams.get(session_id)
        if existing is not None:
            return existing
        lock = self._opening.setdefault(session_id, asyncio.Lock())
        async with lock:
            # Re-checked inside the lock: the whole point of the lock is that
            # two chunks raced here, and the loser must take the winner's
            # socket rather than opening a second.
            existing = self._streams.get(session_id)
            if existing is not None:
                return existing
            stream = await self._open(session_id)
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
        connect = self._connect
        if connect is None:  # pragma: no cover — the real client, not a test
            from websockets.asyncio.client import connect as ws_connect

            connect = ws_connect
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
                text = transcript_of(_parsed(raw))
                if not text:
                    continue
                speaker = await self._speaker(session_id)
                await self._observe(session_id, text, speaker)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            # Reported and left closed. The next chunk reopens, which is the
            # one recovery that does not involve holding a client's audio.
            logger.exception("the live stream for %s ended", session_id)

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
