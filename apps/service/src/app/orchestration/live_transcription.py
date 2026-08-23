"""The live path's recogniser: one window of PCM in, the words in it out.

Separate from `deepgram_engines` because the two answer different questions.
The record path transcribes a finished meeting once, accurately, and can take
its time (NFR-5.4 asks 3% entity-weighted WER of it). This runs while people
are still talking, on four seconds at a time, and what it is measured against
is whether a question reaches the operator inside the conversational window.

It reuses that module's URL builder rather than assembling its own, because
that URL carries the vendor-retention opt-out (NFR-2.3) and a second copy is a
second place for it to be forgotten. The URL already declares linear16 at
16kHz mono, which is exactly what the capture screen uploads.

What this is not is streaming. Deepgram has a websocket that does its own
endpointing; this posts fixed windows to the batch endpoint, so a sentence
that straddles two windows arrives as two halves. The seam is one async
callable, so replacing it with the streaming client changes nothing above it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from app.modules.settings.models import SecretKey

from .deepgram_engines import DeepgramUnavailable, deepgram_listen_url


def transcript_of(payload: Any) -> str:
    """The words Deepgram heard, or "" for a window with no speech in it.

    A quiet window is the common case in a real meeting -- people pause -- and
    it comes back as a present-but-empty transcript rather than as an error.
    """

    channels = (payload or {}).get("results", {}).get("channels", [])
    if not channels:
        return ""
    alternatives = channels[0].get("alternatives", [])
    if not alternatives:
        return ""
    return str(alternatives[0].get("transcript", "") or "")


def deepgram_live_recogniser(
    store: Any,
    get_vocabulary: Callable[[str], Awaitable[list[str]]],
    *,
    model: str = "nova-3",
    timeout: float = 8.0,
    transport: Any = None,
) -> Callable[[str, bytes], Awaitable[str]]:
    """A recogniser for the live lane, or one that refuses honestly.

    The credential and the operator's switches are read per call, so a key
    entered on the Settings screen takes effect without a restart -- the same
    rule the record path follows.
    """

    async def recognise(session_id: str, pcm: bytes) -> str:
        secret = store.get_secret(SecretKey.DEEPGRAM_API_KEY)
        if secret is None:
            raise DeepgramUnavailable("no Deepgram credential is configured")

        connectors = store.read().connectors
        keyterms = await get_vocabulary(session_id) if connectors.keyterm_prompting else []

        async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
            response = await client.post(
                deepgram_listen_url(
                    model,
                    list(keyterms),
                    opt_out_of_retention=connectors.disable_vendor_retention,
                ),
                headers={
                    "Authorization": f"Token {secret.reveal()}",
                    "Content-Type": "application/octet-stream",
                },
                content=pcm,
            )

        if response.status_code != 200:
            raise DeepgramUnavailable(f"Deepgram answered {response.status_code}")
        return transcript_of(response.json())

    return recognise
