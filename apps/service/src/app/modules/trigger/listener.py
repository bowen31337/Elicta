"""Buffer uploaded audio until there is enough of it to be worth recognising.

Sits between the chunk upload the capture screen already performs and the
trigger gate. Knows nothing about either vendor or gate: it is handed a
recogniser and somewhere to put what comes back, which is what lets the whole
live path be exercised without spending a speech credit.

See this module's tests for why the window is fixed rather than endpointed,
and what that costs.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

#: linear16 at 16kHz mono is 32000 bytes a second, which the capture screen's
#: uploader states as the format. Four seconds is long enough to hold a clause
#: worth asking about and short enough to leave most of the conversational
#: window intact for everything downstream.
WINDOW_BYTES = 32_000 * 4

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
