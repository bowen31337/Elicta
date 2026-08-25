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


def readiness_of(
    *,
    configured: set[SecretKey],
    auth_mode: AuthMode,
    live_vendor: SpeechVendor,
) -> list[CapabilityReadiness]:
    """Each capability, whether it can run, and what it costs if it cannot.

    `live_vendor` is taken and deliberately not used for the live lane — see
    the comment there. It stays in the signature because the day a second live
    recogniser exists, this is the argument that decides, and a caller already
    passing it is one less thing to remember then.
    """

    inference_key = (
        SecretKey.ANTHROPIC_API_KEY
        if auth_mode is AuthMode.API_KEY
        else SecretKey.ANTHROPIC_OAUTH_TOKEN
    )
    # Deliberately not `live_vendor`'s key. The live path has one
    # implementation — `composition.py` builds `deepgram_live_recogniser` and
    # gates the fork on `DEEPGRAM_API_KEY` — and the vendor selector has no
    # second recogniser behind it. Following the setting here sent an operator
    # whose vendor read AssemblyAI to set an AssemblyAI key, which is stored,
    # reported configured, and transcribes nothing: the same silence they came
    # here to fix. This report is only worth reading if it names the key the
    # code actually reads.
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

    live_ready = live_key is None or live_key in configured
    entries.append(
        CapabilityReadiness(
            capability=Capability.LIVE_NUDGES,
            ready=live_ready,
            missing=() if live_ready or live_key is None else (live_key,),
            consequence=(
                "Meetings still record and the audio is still kept, but nothing "
                "is transcribed while people are talking, so no nudge ever "
                "reaches the panel. The panel looks like it has nothing to say. "
                "The live path uses Deepgram whichever vendor is selected."
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
