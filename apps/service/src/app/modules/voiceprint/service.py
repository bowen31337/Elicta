"""Enrolling an operator's voice, and deciding who is speaking (FR-1.5, FR-1.6).

Takes its persistence and its clock as injected callables, like every other
service module here. The embedder is imported rather than injected, which is
the one departure and a deliberate one: enrolment and verification have to use
the *same* algorithm or the comparison is meaningless, so there is no useful
configuration where they differ. What is guarded instead is the case that
actually happens — a print made by an earlier embedder, which is refused by
name rather than compared.
"""

from __future__ import annotations

import base64
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from .embedding import (
    MAX_ENROLMENT_MS,
    MIN_ENROLMENT_MS,
    MODEL_NAME,
    SAMPLE_RATE,
    NotEnoughSpeech,
    duration_ms,
    embed,
    samples_from_pcm,
    similarity,
)
from .models import OperatorVoiceprint

#: There is no operator identity in this service — no accounts, no auth, one
#: desktop app in front of one person. Enrolment is keyed to this constant so
#: the table's shape stays right for the day that changes, without inventing an
#: identity subsystem that nothing else would use.
DEFAULT_OPERATOR_ID = "local-operator"

OPERATOR = "operator"
OTHER = "other"

#: Cosine similarity at or above which a window is called the operator's.
#:
#: **Deliberately high, and the direction matters more than the number.** The
#: consumer is the trigger gate, which skips utterances tagged `operator`. Tag
#: a client as the operator and their requirement is silently never evaluated —
#: a failure nobody in the room can see. Tag the operator as a client and the
#: gate spends one nudge on the operator's own sentence, which is visible and
#: dismissed in a tap. So the threshold is set where an unsure answer comes
#: back `other`, and the worst case is the behaviour this system already has.
#:
#: It has **not** been calibrated against real speech — there is no corpus here
#: to calibrate against. What is known is measured in this module's tests: two
#: similar vocal tracts score above 0.95 against each other, so this separates
#: distinct voices and does not promise to separate close ones.
MATCH_THRESHOLD = 0.97

GetVoiceprint = Callable[[str], Awaitable[OperatorVoiceprint | None]]
SaveVoiceprint = Callable[[OperatorVoiceprint], Awaitable[None]]
ForgetVoiceprint = Callable[[str], Awaitable[bool]]
Now = Callable[[], datetime]


class EnrolmentRefused(Exception):
    """The sample cannot become a voiceprint, in the operator's own terms."""


def _now() -> datetime:
    return datetime.now(UTC)


def decode_sample(pcm: str) -> bytes:
    """The base64 the API receives, as audio bytes.

    Refuses rather than salvages. Base64 that does not decode is a client bug,
    and accepting the prefix that happened to parse would enrol a voiceprint
    from a fragment of somebody's upload.
    """

    try:
        return base64.b64decode(pcm, validate=True)
    except (ValueError, TypeError) as exc:
        raise EnrolmentRefused("The audio could not be read.") from exc


async def enrol_operator(
    operator_id: str,
    pcm: bytes,
    save: SaveVoiceprint,
    *,
    now: Now = _now,
) -> OperatorVoiceprint:
    """Turn one sample into the operator's print, replacing any earlier one.

    The 60-second cap is applied by truncation rather than refusal (FR-1.5).
    A caller streaming live microphone frames has no clean way to stop on the
    boundary, and refusing a 61-second sample would throw away a good enrolment
    over a rounding error — so the extra is dropped and the rest is kept, which
    is what the Rust recorder does with the same cap.
    """

    try:
        samples = samples_from_pcm(pcm)
    except ValueError as exc:
        raise EnrolmentRefused("The audio was not in the expected format.") from exc

    cap = SAMPLE_RATE * MAX_ENROLMENT_MS // 1000
    if len(samples) > cap:
        samples = samples[:cap]

    if duration_ms(len(samples)) < MIN_ENROLMENT_MS:
        raise EnrolmentRefused(
            f"Record at least {MIN_ENROLMENT_MS // 1000} seconds so there is enough "
            "speech to tell your voice apart."
        )

    try:
        embedding = embed(samples)
    except NotEnoughSpeech as exc:
        raise EnrolmentRefused(
            "That recording held no speech the microphone could hear. Check the "
            "input is the one you are speaking into, and try again."
        ) from exc

    voiceprint = OperatorVoiceprint(
        operator_id=operator_id,
        embedding=base64.b64encode(embedding).decode("ascii"),
        embedding_model=MODEL_NAME,
        sample_duration_ms=duration_ms(len(samples)),
        enrolled_at=now(),
    )
    await save(voiceprint)
    return voiceprint


def is_usable(voiceprint: OperatorVoiceprint | None) -> bool:
    """Whether this print can still be compared against live audio."""

    return voiceprint is not None and voiceprint.embedding_model == MODEL_NAME


def identify_speaker(pcm: bytes, voiceprint: OperatorVoiceprint | None) -> str | None:
    """Whether this window of audio is the operator, or `None` if unanswerable.

    `None` is a first-class answer and most of the value of this function.
    There is no enrolled print, or it came from another embedder, or the window
    holds no speech to compare — in every one of those the honest answer is
    "unknown", and the caller leaves the utterance untagged so the gate behaves
    exactly as it does with no verification at all. Guessing `other` instead
    would be indistinguishable on screen and would quietly become the reason a
    future bug in this path went unnoticed.
    """

    if not is_usable(voiceprint):
        return None
    assert voiceprint is not None  # narrowed by is_usable

    try:
        samples = samples_from_pcm(pcm)
        heard = embed(samples)
        enrolled = base64.b64decode(voiceprint.embedding, validate=True)
        score = similarity(enrolled, heard)
    except (NotEnoughSpeech, ValueError):
        return None

    return OPERATOR if score >= MATCH_THRESHOLD else OTHER
