"""Buffer uploaded audio until there is enough of it to be worth recognising.

Sits between the chunk upload the capture screen already performs and the
trigger gate. Knows nothing about either vendor or gate: it is handed a
recogniser and somewhere to put what comes back, which is what lets the whole
live path be exercised without spending a speech credit.

See this module's tests for why the window is fixed rather than endpointed,
and what that costs.
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable

#: linear16 at 16kHz mono is 32000 bytes a second, which the capture screen's
#: uploader states as the format.
BYTES_PER_SECOND = 32_000

#: How much audio is recognised at a time.
#:
#: **This is the live path's latency floor, and it was four seconds.** Nothing
#: is recognised until the window holding it is full, so a clause spoken at the
#: start of one waited the whole window before the recogniser saw a byte of it
#: — against 0.2s to actually recognise it, measured on this system. Together
#: with a five-second upload chunk it put five to nine seconds between somebody
#: speaking and a question reaching the operator, of which the model was about
#: four per cent. Swapping models could not have fixed that; this is what did.
#:
#: **Four seconds, and it was briefly one.** Shortening it was the obvious
#: move against the latency above and it was measured afterwards rather than
#: before, which was the mistake. The same 2.4 seconds of speech — "So how are
#: arrivals booked in today at the depot" — through Nova-3:
#:
#:     0.5s   'How are' / '' / 'In today.' / 'The death'
#:     1.0s   'How are arrivals' / 'Today at the death'
#:     2.0s   'How are arrivals booked in today at the'
#:
#: A short window does not merely split a sentence; it *mis-hears* it, because
#: the recogniser has no context either side of the cut — "depot" came back as
#: "death". A trigger gate reading that is worse than one reading nothing, and
#: it arrives faster only in the sense that a wrong answer always does.
#:
#: So the window is what it always was, and **the latency is not solved here
#: any more**. It is solved by not having a window: `deepgram_flux` streams and
#: ends a turn where the speaker does, which is the right shape for speech and
#: is now the default. This path is the accurate one, for a model that cannot
#: stream, and it keeps the context that makes it accurate.
#:
#: The upload chunk no longer has to match: unequal lengths only mattered when
#: a 5s chunk against a 4s window left a second behind each time, growing the
#: remainder until two windows fired at once. A chunk *smaller* than the
#: window simply fills it in pieces.
WINDOW_SECONDS = 4.0
WINDOW_SECONDS_ENV = "ELICTA_LIVE_WINDOW_SECONDS"

WINDOW_BYTES = int(BYTES_PER_SECOND * WINDOW_SECONDS)


def window_bytes_from_env() -> int:
    """The configured window, in bytes, or the default.

    Tunable without a rebuild because the right value is a judgement about a
    room rather than a constant: a meeting of two people finishing each
    other's sentences wants it short, a formal walkthrough wants the context.

    A value that cannot be read as a positive number falls back rather than
    raising, for the same reason the abandoned-recording sweep does: refusing
    to start the whole service over a malformed tuning knob trades a
    slightly-wrong window for no service at all.
    """

    raw = os.environ.get(WINDOW_SECONDS_ENV, "").strip()
    if not raw:
        return WINDOW_BYTES
    try:
        configured = float(raw)
    except ValueError:
        return WINDOW_BYTES
    if configured <= 0:
        return WINDOW_BYTES
    # Whole samples, and at least one: a window shorter than a single 16-bit
    # sample would spin the drain loop forever on a buffer it can never empty.
    return max(2, int(BYTES_PER_SECOND * configured) // 2 * 2)

#: Given one window of PCM, the text in it -- empty when there was no speech.
#: Told which session it is hearing, so the engagement's own vocabulary can
#: reach the recogniser. That handshake is the one preparation step with teeth
#: (FR-2.9), and a live path that quietly dropped it would mis-hear exactly the
#: proper nouns a requirements meeting turns on.
Recognise = Callable[[str, bytes], Awaitable[str]]
#: Where a finalised utterance goes, with whoever the verifier believes said
#: it -- `None` when nothing could tell, which is the ordinary case on a
#: deployment where nobody has enrolled.
Observe = Callable[[str, str, str | None], Awaitable[None]]
#: Whose voice is in this window, or `None` if the question cannot be answered
#: (PRD FR-1.6). Awaitable because the answer is real signal processing rather
#: than a lookup: it must not run on the event loop the meeting's own event
#: stream is being served from.
Identify = Callable[[str, bytes], Awaitable[str | None]]


class LiveUtterances:
    """One buffer per session, drained a window at a time."""

    def __init__(
        self,
        recognise: Recognise,
        observe: Observe,
        *,
        identify: Identify | None = None,
        window_bytes: int = WINDOW_BYTES,
    ) -> None:
        self._recognise = recognise
        self._observe = observe
        self._identify = identify
        self._window = window_bytes
        self._buffers: dict[str, bytes] = {}

    async def feed(self, session_id: str, pcm: bytes) -> None:
        """Take one uploaded chunk, and recognise whatever whole windows it completes.

        A chunk may complete more than one window -- a client that batched its
        uploads, or one reconnecting after a stall -- so this drains rather
        than handling a single window and returning.
        """

        buffered = self._buffers.get(session_id, b"") + pcm

        while len(buffered) >= self._window:
            window, buffered = buffered[: self._window], buffered[self._window :]
            heard = await self._recognise(session_id, window)
            # Whitespace counts as silence. The intake requires non-empty
            # text, so passing a blank line on would turn a quiet room into a
            # stream of 422s.
            if not heard.strip():
                continue

            # Verified against the same window the words came from, and only
            # once there are words in it. This is the audio segment FR-1.6
            # asks about, it is already in hand, and asking about a window
            # that turned out to be silence would spend the whole cost of the
            # comparison to learn nothing.
            speaker = None if self._identify is None else await self._identify(session_id, window)
            await self._observe(session_id, heard.strip(), speaker)

        # Written back even when nothing was recognised: the remainder is the
        # start of the next window, and dropping it loses speech silently.
        self._buffers[session_id] = buffered
