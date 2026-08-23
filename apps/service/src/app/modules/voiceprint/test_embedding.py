"""What the baseline embedder has to get right to be worth shipping.

The bar is not "is this ECAPA" — it is not, and the module says so. The bar is
that two samples of the same synthetic voice score higher against each other
than either does against a different one, that loudness and content do not
decide the answer, and that silence does not.

The voices here are synthesised rather than recorded because a fixture of real
speech cannot live in this repo, and because a synthesiser lets a test hold one
property fixed while varying another — which is the only way to show that the
print follows the vocal tract and not the microphone gain.
"""

from __future__ import annotations

import array
import math
import random

import pytest

from .embedding import (
    MAX_ENROLMENT_MS,
    SAMPLE_RATE,
    NotEnoughSpeech,
    duration_ms,
    embed,
    samples_from_pcm,
    similarity,
)

# Two vocal tracts, as formant triples in Hz. Far enough apart to be different
# people, close enough to be human.
TRACT_A = (730.0, 1090.0, 2440.0)
TRACT_B = (390.0, 1990.0, 2550.0)


def voice(
    tract: tuple[float, float, float],
    *,
    f0: float = 120.0,
    seconds: float = 6.0,
    gain: float = 0.3,
    seed: int = 1,
) -> array.array:
    """A crude vowel synthesiser: a harmonic source shaped by three formants.

    Syllables come from an amplitude envelope with real gaps in it, so the
    silence gate has something to gate and a sample is not one continuous tone.
    """

    rng = random.Random(seed)
    samples = array.array("h")
    total = int(SAMPLE_RATE * seconds)
    harmonics = int(SAMPLE_RATE / 2 / f0)
    for n in range(total):
        t = n / SAMPLE_RATE
        # Roughly four syllables a second, with a closed gap between them.
        envelope = max(0.0, math.sin(2 * math.pi * 4.0 * t)) ** 2
        value = 0.0
        if envelope > 0.01:
            for harmonic in range(1, harmonics):
                frequency = f0 * harmonic
                shaping = 0.0
                for formant in tract:
                    bandwidth = 90.0
                    shaping += 1.0 / (1.0 + ((frequency - formant) / bandwidth) ** 2)
                value += shaping * math.sin(2 * math.pi * frequency * t) / harmonic
        value = value * envelope / 8.0 + rng.uniform(-0.001, 0.001)
        samples.append(max(-32768, min(32767, int(value * gain * 32767))))
    return samples


def test_the_same_voice_scores_higher_against_itself_than_against_another() -> None:
    enrolled = embed(voice(TRACT_A, seed=1))
    same_speaker = embed(voice(TRACT_A, f0=126.0, seed=2))
    other_speaker = embed(voice(TRACT_B, f0=118.0, seed=3))

    assert similarity(enrolled, same_speaker) > similarity(enrolled, other_speaker)


def test_a_voice_matches_itself_exactly() -> None:
    print_of = embed(voice(TRACT_A))

    assert similarity(print_of, print_of) == pytest.approx(1.0, abs=1e-6)


def test_loudness_does_not_decide_who_is_speaking() -> None:
    """Leaning closer to the microphone must not read as a different person.

    This is what dropping the zeroth cepstral coefficient buys, and it is the
    single most likely way a naive version of this would fail in a real room.
    """

    quiet = embed(voice(TRACT_A, gain=0.08))
    loud = embed(voice(TRACT_A, gain=0.6))
    other = embed(voice(TRACT_B, gain=0.08))

    assert similarity(quiet, loud) > similarity(quiet, other)


def test_the_print_is_deterministic() -> None:
    """A print that varies per call cannot be compared with a stored one."""

    sample = voice(TRACT_A)

    assert embed(sample) == embed(sample)


def test_silence_is_not_characterised_as_a_voice() -> None:
    with pytest.raises(NotEnoughSpeech):
        embed(array.array("h", [0] * SAMPLE_RATE * 4))


def test_a_sample_shorter_than_one_frame_is_refused() -> None:
    with pytest.raises(NotEnoughSpeech):
        embed(array.array("h", [1000] * 100))


def test_prints_of_different_shapes_refuse_to_be_compared() -> None:
    """A print from another embedder holds bytes that mean something else."""

    with pytest.raises(ValueError):
        similarity(embed(voice(TRACT_A)), b"\x00\x00\x00\x00")


def test_pcm_round_trips_through_the_byte_form_the_api_receives() -> None:
    sample = voice(TRACT_A, seconds=4.0)

    assert samples_from_pcm(sample.tobytes()) == sample


def test_a_half_sample_is_refused_rather_than_truncated() -> None:
    with pytest.raises(ValueError):
        samples_from_pcm(b"\x01\x02\x03")


def test_duration_is_reported_in_the_units_the_table_stores() -> None:
    assert duration_ms(SAMPLE_RATE * 60) == MAX_ENROLMENT_MS
