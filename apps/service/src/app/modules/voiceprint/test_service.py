"""Enrolment and verification behaviour, including the parts that must fail."""

from __future__ import annotations

import base64
from datetime import UTC, datetime

import pytest

from .embedding import MODEL_NAME, SAMPLE_RATE, embed
from .models import OperatorVoiceprint
from .service import (
    MATCH_THRESHOLD,
    OPERATOR,
    OTHER,
    EnrolmentRefused,
    decode_sample,
    enrol_operator,
    identify_speaker,
    is_usable,
)
from .test_embedding import TRACT_A, TRACT_B, voice

FIXED_NOW = datetime(2026, 8, 23, 10, 30, tzinfo=UTC)


class Recorder:
    """Somewhere for a print to be saved, and a record of what was."""

    def __init__(self) -> None:
        self.saved: list[OperatorVoiceprint] = []

    async def __call__(self, voiceprint: OperatorVoiceprint) -> None:
        self.saved.append(voiceprint)


def enrolled_print(seed: int = 1) -> OperatorVoiceprint:
    return OperatorVoiceprint(
        operator_id="local-operator",
        embedding=base64.b64encode(embed(voice(TRACT_A, seed=seed))).decode("ascii"),
        embedding_model=MODEL_NAME,
        sample_duration_ms=6_000,
        enrolled_at=FIXED_NOW,
    )


async def test_enrolling_saves_a_print_shaped_for_the_table() -> None:
    save = Recorder()

    result = await enrol_operator(
        "local-operator", voice(TRACT_A).tobytes(), save, now=lambda: FIXED_NOW
    )

    assert save.saved == [result]
    assert result.embedding_model == MODEL_NAME
    assert result.sample_duration_ms == 6_000
    assert result.enrolled_at == FIXED_NOW


async def test_a_sample_past_sixty_seconds_is_truncated_not_refused() -> None:
    """FR-1.5 caps the sample. A caller streaming live frames cannot stop on
    the boundary, so the extra is dropped rather than the enrolment lost."""

    save = Recorder()
    long_sample = voice(TRACT_A, seconds=65.0)

    result = await enrol_operator("local-operator", long_sample.tobytes(), save)

    assert result.sample_duration_ms == 60_000


async def test_a_sample_too_short_to_characterise_is_refused() -> None:
    with pytest.raises(EnrolmentRefused, match="at least"):
        await enrol_operator("local-operator", voice(TRACT_A, seconds=1.0).tobytes(), Recorder())


async def test_a_silent_recording_is_refused_in_the_operators_terms() -> None:
    silence = bytes(SAMPLE_RATE * 2 * 6)

    with pytest.raises(EnrolmentRefused, match="no speech"):
        await enrol_operator("local-operator", silence, Recorder())


async def test_a_half_sample_is_refused_rather_than_enrolled() -> None:
    with pytest.raises(EnrolmentRefused, match="expected format"):
        await enrol_operator("local-operator", b"\x01\x02\x03", Recorder())


async def test_nothing_is_saved_when_a_sample_is_refused() -> None:
    """A refused enrolment must not replace a good print with nothing."""

    save = Recorder()

    with pytest.raises(EnrolmentRefused):
        await enrol_operator("local-operator", bytes(SAMPLE_RATE * 2 * 6), save)

    assert save.saved == []


def test_base64_that_does_not_decode_is_refused() -> None:
    with pytest.raises(EnrolmentRefused, match="could not be read"):
        decode_sample("not base64 at all!!")


def test_the_operators_own_voice_is_recognised() -> None:
    window = voice(TRACT_A, f0=124.0, seconds=4.0, seed=7).tobytes()

    assert identify_speaker(window, enrolled_print()) == OPERATOR


def test_a_clearly_different_voice_is_not() -> None:
    window = voice(TRACT_B, seconds=4.0, seed=7).tobytes()

    assert identify_speaker(window, enrolled_print()) == OTHER


def test_with_nobody_enrolled_the_answer_is_unknown_not_other() -> None:
    """`None` leaves the utterance untagged and the gate behaving as it does
    today. Answering `other` would look identical and hide a broken path."""

    assert identify_speaker(voice(TRACT_A, seconds=4.0).tobytes(), None) is None


def test_a_print_from_another_embedder_refuses_to_be_compared() -> None:
    stale = enrolled_print().model_copy(update={"embedding_model": "ecapa-tdnn-v2"})

    assert not is_usable(stale)
    assert identify_speaker(voice(TRACT_A, seconds=4.0).tobytes(), stale) is None


def test_a_silent_window_is_unknown_rather_than_somebody() -> None:
    assert identify_speaker(bytes(SAMPLE_RATE * 2 * 4), enrolled_print()) is None


def test_similar_voices_are_the_known_limit_of_this_embedder() -> None:
    """The honest bound on the baseline, pinned so it cannot quietly worsen.

    Two nearby vocal tracts score high enough against each other to be
    confusable, which is exactly what an ECAPA-class model would fix and this
    one does not. The module says so in prose; this is the number behind it.
    If a future embedder separates them, this test should fail and be replaced
    with the stronger claim.
    """

    from .embedding import similarity

    nearby = (640.0, 1190.0, 2390.0)
    score = similarity(
        base64.b64decode(enrolled_print().embedding),
        embed(voice(nearby, f0=118.0, seconds=4.0, seed=9)),
    )

    assert 0.9 < score < MATCH_THRESHOLD
