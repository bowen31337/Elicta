"""Credential probes for the speech vendors.

Each probe answers one question — does this key work — by making the cheapest
authenticated call the vendor offers, never by transcribing anything. A probe
that cost money or uploaded audio would be a probe nobody runs.

Both vendors authenticate on a plain header, and both reject a bad key with
401. The probe therefore treats *any* successful response as proof and lets the
vendor's own error text explain a failure, rather than trying to interpret
status codes it has no stake in.
"""

from __future__ import annotations

import httpx

DEEPGRAM_URL = "https://api.deepgram.com/v1/projects"
ASSEMBLYAI_URL = "https://api.assemblyai.com/v2/transcript?limit=1"
TIMEOUT = 10.0


class ProbeFailed(RuntimeError):
    """The vendor rejected the credential, or could not be reached."""


async def _check(url: str, headers: dict[str, str], vendor: str) -> None:
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        # Unreachable is a different problem from unauthorised, and an operator
        # acts on it differently — one is a key, the other is a network.
        raise ProbeFailed(f"{vendor} could not be reached: {type(exc).__name__}") from exc

    if response.status_code in (401, 403):
        raise ProbeFailed(f"{vendor} rejected the credential ({response.status_code})")
    if response.status_code >= 400:
        raise ProbeFailed(f"{vendor} returned {response.status_code}")


async def probe_deepgram(api_key: str, *, base_url: str | None = None) -> None:
    """Verify a Deepgram key by listing projects — no audio, no cost."""

    await _check(
        base_url or DEEPGRAM_URL,
        {"Authorization": f"Token {api_key}"},
        "Deepgram",
    )


async def probe_assemblyai(api_key: str, *, base_url: str | None = None) -> None:
    """Verify an AssemblyAI key by listing one transcript — no audio, no cost."""

    await _check(
        base_url or ASSEMBLYAI_URL,
        {"authorization": api_key},
        "AssemblyAI",
    )


def probe_for_vendor(vendor: str):
    """The probe for a configured speech vendor, or `None` if there isn't one.

    A custom vendor has no probe by definition — we do not know its API — and
    returning `None` is what makes the settings screen say "configured, not
    verified" rather than inventing a reachability signal.
    """

    return {"deepgram": probe_deepgram, "assemblyai": probe_assemblyai}.get(vendor)
