"""What is not configured, and what it costs.

Every fact needed to answer that already sits on the settings screen: each
secret reports whether it is configured. What none of them says is which ones
*matter* and what stops without them, and that knowledge lived only in the
composition root — in early returns and fail-closed engines that a running
service never mentions again.

The cost of leaving it there was measured. A meeting recorded cleanly, the
transcript arrived, and the live panel showed no nudge, because
`deepgram_api_key` was unset: the chunk upload forks into the live lane, and
that fork returns early without a recogniser. Nothing anywhere said so. The
screen showed `configured: false` beside a key whose absence had no stated
consequence, which is a fact rather than a warning.

So the rules are stated once, here, as data an operator can read: for each
capability, the secrets it needs *given the modes actually selected*, and the
sentence describing what does not happen without them. Selected modes matter —
an OAuth token does not stand in for an API key when the mode says key, and a
Deepgram key does not make an AssemblyAI live lane work. Reporting "some
credential exists" would pass exactly the deployments this exists to catch.
"""

from __future__ import annotations

from .models import (
    AuthMode,
    Capability,
    CapabilityReadiness,
    SecretKey,
    SpeechVendor,
)
from .speech_credentials import SpeechCredentialPool

#: The providers this build has a live recogniser for. A pool may hold keys
#: for others — a credential can be stored and labelled before there is a
#: client for it — and a report ignoring the difference would tell an operator
#: holding a Gemini key that they have no key at all.
LIVE_DRIVABLE: frozenset[SpeechVendor] = frozenset({SpeechVendor.DEEPGRAM})


def readiness_of(
    *,
    configured: set[SecretKey],
    auth_mode: AuthMode,
    pool: SpeechCredentialPool | None = None,
) -> list[CapabilityReadiness]:
    """Each capability, whether it can run, and what it costs if it cannot.

    The pool decides which providers are configured, so there is no separate
    vendor setting to consult: choosing a credential is choosing a provider.
    """

    inference_key = (
        SecretKey.ANTHROPIC_API_KEY
        if auth_mode is AuthMode.API_KEY
        else SecretKey.ANTHROPIC_OAUTH_TOKEN
    )
    pool = pool if pool is not None else SpeechCredentialPool()
    live_key = SecretKey.DEEPGRAM_API_KEY

    entries: list[CapabilityReadiness] = []

    entries.append(
        CapabilityReadiness(
            capability=Capability.INFERENCE,
            ready=inference_key in configured,
            missing=() if inference_key in configured else (inference_key,),
            consequence=(
                "The question bank cannot be compiled and the debrief cannot be "
                "written up. Every stage that needs a model will fail and say so."
            ),
        )
    )

    # Either a pooled credential this build can drive, or the fixed key a
    # deployment predating the pool still has.
    live_ready = pool.has_any_for(LIVE_DRIVABLE) or live_key in configured
    # A pool holding only keys for providers with no client is a third state,
    # and reporting it as "no key" sends an operator to buy a credential they
    # already have.
    has_undrivable = not live_ready and bool(
        [c for c in pool.credentials if c.enabled and c.vendor not in LIVE_DRIVABLE]
    )
    drivable = ", ".join(sorted(v.value for v in LIVE_DRIVABLE))
    entries.append(
        CapabilityReadiness(
            capability=Capability.LIVE_NUDGES,
            ready=live_ready,
            missing=() if live_ready else (live_key,),
            consequence=(
                (
                    "Meetings still record and the audio is still kept, but the "
                    "speech credentials configured are for providers this build "
                    "cannot drive yet, so nothing is transcribed while people "
                    f"are talking and no nudge reaches the panel. Live "
                    f"transcription runs on: {drivable}."
                )
                if has_undrivable
                else (
                    "Meetings still record and the audio is still kept, but "
                    "nothing is transcribed while people are talking, so no "
                    "nudge ever reaches the panel. The panel looks like it has "
                    f"nothing to say. Live transcription runs on: {drivable}."
                )
            ),
        )
    )

    # Both, deliberately: FR-2.6 runs two independent engines over the record
    # path and T3 warns the pair is only worth running if they fail
    # differently. One key gives a transcript and no reconciliation signal,
    # which is a quieter failure than none at all.
    record_keys = (SecretKey.DEEPGRAM_API_KEY, SecretKey.ASSEMBLYAI_API_KEY)
    record_missing = tuple(key for key in record_keys if key not in configured)
    entries.append(
        CapabilityReadiness(
            capability=Capability.RECORD_TRANSCRIPTION,
            ready=not record_missing,
            missing=record_missing,
            consequence=(
                "A finished meeting cannot be transcribed, so there is no "
                "transcript to write a debrief from. Both engines are named "
                "because the pair is what makes the reconciliation worth having."
            ),
        )
    )

    graph_ready = SecretKey.MICROSOFT_GRAPH_CLIENT_SECRET in configured
    entries.append(
        CapabilityReadiness(
            capability=Capability.DOCUMENT_LINKS,
            ready=graph_ready,
            missing=() if graph_ready else (SecretKey.MICROSOFT_GRAPH_CLIENT_SECRET,),
            consequence=(
                "Documents can still be uploaded; only attaching one by "
                "SharePoint or OneDrive link needs this."
            ),
            optional=True,
        )
    )

    return entries


__all__ = ["Capability", "CapabilityReadiness", "readiness_of"]
