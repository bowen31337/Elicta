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

from enum import Enum

from pydantic import BaseModel, Field

from .models import AuthMode, SecretKey, SpeechVendor


class Capability(str, Enum):
    """The things an operator would notice not working."""

    INFERENCE = "inference"
    LIVE_NUDGES = "live_nudges"
    RECORD_TRANSCRIPTION = "record_transcription"
    DOCUMENT_LINKS = "document_links"


class CapabilityReadiness(BaseModel):
    """One capability, and why it is or is not available."""

    capability: Capability
    ready: bool
    missing: tuple[SecretKey, ...] = Field(
        default=(),
        description="The secrets that would make it ready, in the modes currently selected.",
    )
    consequence: str = Field(
        description=(
            "What does not happen without them, in the operator's terms — what "
            "stops, not which field is blank. The screen already shows which "
            "field is blank."
        )
    )
    optional: bool = Field(
        default=False,
        description=(
            "Whether the deployment is usable without it. An optional "
            "capability is an extra somebody may not want; a required one "
            "missing means a core promise of the product silently does not "
            "happen."
        ),
    )


def _vendor_key(vendor: SpeechVendor) -> SecretKey | None:
    """The secret a speech vendor authenticates with.

    `CUSTOM` names a vendor this service has no client for, so no key of ours
    would help — reported as nothing missing rather than as a key to go and
    find.
    """

    if vendor is SpeechVendor.DEEPGRAM:
        return SecretKey.DEEPGRAM_API_KEY
    if vendor is SpeechVendor.ASSEMBLYAI:
        return SecretKey.ASSEMBLYAI_API_KEY
    return None


def readiness_of(
    *,
    configured: set[SecretKey],
    auth_mode: AuthMode,
    live_vendor: SpeechVendor,
) -> list[CapabilityReadiness]:
    """Each capability, whether it can run, and what it costs if it cannot."""

    inference_key = (
        SecretKey.ANTHROPIC_API_KEY
        if auth_mode is AuthMode.API_KEY
        else SecretKey.ANTHROPIC_OAUTH_TOKEN
    )
    live_key = _vendor_key(live_vendor)

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
                "reaches the panel. The panel looks like it has nothing to say."
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
