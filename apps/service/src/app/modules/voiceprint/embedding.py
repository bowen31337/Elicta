"""Turn a sample of speech into a voiceprint, using nothing but the stdlib.

**This is a baseline, and calling it anything else would be a lie.** The
architecture (section 3.3) specifies an ECAPA-TDNN-class speaker embedding
model. There is no such model in this tree, and no numpy, torch or ONNX to run
one with. What this module computes instead is the classical thing that comes
before a learned embedding: mel-frequency cepstral statistics, which describe
the shape of a speaker's vocal tract and are reasonably stable across what
they happen to be saying. On a clean wired or loopback feed that separates one
enrolled operator from everyone else in the room well enough to be worth
having. Under cross-talk, or on a room microphone, it is materially worse than
the model the architecture asks for, and the operator is told so on screen.

The pipeline is the textbook one, and every step is here because leaving it
out breaks something specific:

- **Pre-emphasis** lifts the high frequencies that carry speaker identity and
  that a microphone's response rolls off.
- **25ms frames at a 10ms hop** are short enough that the vocal tract is
  approximately fixed across one and overlapped enough that nothing falls
  between two.
- **A Hamming window** stops each frame's abrupt ends from smearing energy
  across the whole spectrum, which would drown the formants being measured.
- **A mel filterbank** spaces the bands the way hearing does, so the bands
  that distinguish two voices get the resolution and the ones that do not are
  not wasted on.
- **The DCT** decorrelates those bands into cepstral coefficients, and
  **dropping the first** is what makes the result independent of how loud the
  speaker was — otherwise leaning closer to the microphone would read as a
  different person.
- **The silence gate** is the one that is easy to skip and expensive to skip.
  A 60-second enrolment is mostly pauses, and statistics taken over silence
  describe the room rather than the speaker: two different people enrolled in
  the same office would look alike.

No I/O, no persistence, no vendor: every branch here is reachable from a plain
function call, which is the only reason a DSP path like this stays honest.
"""

from __future__ import annotations

import array
import cmath
import math
import struct

#: What the whole system moves audio as. Matches `capture::ring::TARGET_SAMPLE_RATE`
#: and the panel's `pcm.ts`, so a sample that reached here needs no conversion.
SAMPLE_RATE = 16_000

#: Stamped onto every print this module produces, and checked before any
#: comparison. A print made by a different embedder holds bytes that mean
#: something else; scoring them against these would return a number that looks
#: like a similarity and is not one.
MODEL_NAME = "mfcc-stats-v1"

#: PRD FR-1.5: "at most 60 seconds". Enforced here as well as at the API edge,
#: because this is the chokepoint every path reaches.
MAX_ENROLMENT_MS = 60_000

#: Below this there is not enough speech to characterise a voice, and a print
#: built from it would verify badly for the length of every meeting after.
MIN_ENROLMENT_MS = 3_000

_FRAME_SAMPLES = 400  # 25ms
_HOP_SAMPLES = 160  # 10ms
_FFT_SIZE = 512
_MEL_BANDS = 26
_CEPSTRA = 13  # c0..c12; c0 is discarded, leaving 12 kept coefficients
_PRE_EMPHASIS = 0.97
_LOW_HZ = 20.0
_HIGH_HZ = 7_600.0

#: A frame carrying less than this share of the sample's loudest frame energy
#: is treated as silence and excluded from the statistics.
_SILENCE_FLOOR = 0.02

#: How many frames are actually transformed, however long the sample is.
#:
#: The FFT is what this costs, and it is paid per frame: a 60-second enrolment
#: is 6,000 frames and took 7.6 seconds to embed before this cap, while a
#: 4-second live window took 423ms — against the ~15ms per utterance the
#: architecture budgets for verification. Mean and standard deviation over
#: evenly spaced frames converge on the same values as over every frame, so
#: sampling the timeline rather than exhausting it costs accuracy that is hard
#: to measure and buys an order of magnitude. The spacing is even rather than
#: taken from the front, so a print describes the whole sample and not its
#: opening seconds.
_MAX_ANALYSIS_FRAMES = 300

#: The gap, in log-energy units, that has to exist between the loudest frame
#: and the median one before a sample is accepted as speech at all.
#:
#: A purely relative silence gate cannot see silence: digital zeroes give every
#: frame the same floored energy, so "quieter than the loudest frame" excludes
#: nothing and a muted microphone enrols as a voice. What actually separates
#: speech from both silence and a steady hum is that speech has syllables — it
#: goes loud and quiet several times a second, and nothing else on a meeting
#: room input does. Measured here, that gap is exactly 0 for silence and
#: between 4.7 and 6.9 for synthesised speech at every gain from 0.02 to 0.3,
#: so this sits well below the quietest real sample and well above a flat one.
_MIN_ENERGY_SPREAD = 1.5


class NotEnoughSpeech(Exception):
    """The sample held too little audible speech to build a print from."""


def _hamming(size: int) -> list[float]:
    return [0.54 - 0.46 * math.cos(2 * math.pi * n / (size - 1)) for n in range(size)]


_WINDOW = _hamming(_FRAME_SAMPLES)


def _hz_to_mel(hz: float) -> float:
    return 2595.0 * math.log10(1.0 + hz / 700.0)


def _mel_to_hz(mel: float) -> float:
    return 700.0 * (10.0 ** (mel / 2595.0) - 1.0)


def _filterbank() -> list[list[tuple[int, float]]]:
    """Triangular mel filters as sparse (bin, weight) lists.

    Sparse rather than a dense matrix because this is pure Python: a dense
    26x257 multiply per frame is roughly 6,700 multiplications where the
    sparse form is about 500, and a 60-second sample is 6,000 frames.
    """

    low_mel, high_mel = _hz_to_mel(_LOW_HZ), _hz_to_mel(_HIGH_HZ)
    edges = [
        _mel_to_hz(low_mel + (high_mel - low_mel) * i / (_MEL_BANDS + 1))
        for i in range(_MEL_BANDS + 2)
    ]
    bins = [int(math.floor((_FFT_SIZE + 1) * hz / SAMPLE_RATE)) for hz in edges]

    filters: list[list[tuple[int, float]]] = []
    for band in range(1, _MEL_BANDS + 1):
        left, centre, right = bins[band - 1], bins[band], bins[band + 1]
        # Degenerate bands happen at the low end where consecutive mel edges
        # land in the same FFT bin. Widening beats dropping: a band with no
        # taps contributes a constant to every print and stops separating
        # anything.
        centre = max(centre, left + 1)
        right = max(right, centre + 1)
        taps: list[tuple[int, float]] = []
        for bin_index in range(left, centre):
            taps.append((bin_index, (bin_index - left) / (centre - left)))
        for bin_index in range(centre, right):
            taps.append((bin_index, (right - bin_index) / (right - centre)))
        filters.append([(b, w) for b, w in taps if 0 <= b <= _FFT_SIZE // 2 and w > 0])
    return filters


_FILTERS = _filterbank()

_DCT = [
    [math.cos(math.pi * k * (2 * b + 1) / (2 * _MEL_BANDS)) for b in range(_MEL_BANDS)]
    for k in range(_CEPSTRA)
]


def _fft(frame: list[float]) -> list[complex]:
    """Iterative radix-2 FFT over a power-of-two buffer.

    Written out rather than reached for, because Python's stdlib has no FFT
    and the alternative is a dependency the rest of this service does not
    have. The naive O(n^2) transform is 262,144 operations per frame against
    this one's 2,304 — on a 60-second sample that is the difference between
    an enrolment that returns and one that appears to hang.
    """

    n = len(frame)
    values = [complex(x, 0.0) for x in frame]

    # Bit-reversal permutation, in place.
    j = 0
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j |= bit
        if i < j:
            values[i], values[j] = values[j], values[i]

    length = 2
    while length <= n:
        step = cmath.exp(-2j * cmath.pi / length)
        for start in range(0, n, length):
            twiddle = 1 + 0j
            for offset in range(length // 2):
                even = values[start + offset]
                odd = values[start + offset + length // 2] * twiddle
                values[start + offset] = even + odd
                values[start + offset + length // 2] = even - odd
                twiddle *= step
        length <<= 1
    return values


def _frames(samples: array.array) -> list[tuple[list[float], float]]:
    """Pre-emphasised, windowed, zero-padded frames with their log energy.

    The energy is measured here, in the time domain, rather than read off the
    spectrum afterwards. It is the same quantity either way, but this side of
    the FFT it costs one multiply-add per sample — which is what lets the
    silence gate run over every frame while the transform runs over only the
    frames that survive it.
    """

    out: list[tuple[list[float], float]] = []
    position = 0
    limit = len(samples) - _FRAME_SAMPLES
    while position <= limit:
        frame = [0.0] * _FFT_SIZE
        energy = 0.0
        previous = samples[position - 1] if position > 0 else 0
        for i in range(_FRAME_SAMPLES):
            current = samples[position + i]
            value = (current - _PRE_EMPHASIS * previous) * _WINDOW[i] / 32768.0
            frame[i] = value
            energy += value * value
            previous = current
        out.append((frame, math.log(max(energy / _FRAME_SAMPLES, 1e-12))))
        position += _HOP_SAMPLES
    return out


def _cepstra(frame: list[float]) -> list[float]:
    """One frame's kept cepstral coefficients."""

    spectrum = _fft(frame)
    power = [abs(spectrum[i]) ** 2 / _FFT_SIZE for i in range(_FFT_SIZE // 2 + 1)]

    band_energies = []
    for taps in _FILTERS:
        total = 0.0
        for bin_index, weight in taps:
            total += power[bin_index] * weight
        # Floored rather than guarded: a silent band is a real input, and
        # log(0) would put a NaN into the statistics that never comes out.
        band_energies.append(math.log(max(total, 1e-12)))

    # c0 is the frame's overall log energy, which is how close the speaker sat
    # to the microphone. Never computed, so the print describes the voice and
    # not the seating; the silence gate measures energy in the time domain.
    return [
        sum(band_energies[b] * _DCT[k][b] for b in range(_MEL_BANDS)) for k in range(1, _CEPSTRA)
    ]


def samples_from_pcm(pcm: bytes) -> array.array:
    """Little-endian linear16 bytes as signed 16-bit samples.

    Raises on an odd length rather than dropping the trailing byte: a
    half-sample means the caller framed the upload wrongly, and silently
    truncating turns that into a print that is quietly a little wrong.
    """

    if len(pcm) % 2:
        raise ValueError("linear16 audio must have an even number of bytes")
    samples = array.array("h")
    samples.frombytes(pcm)
    if struct.pack("=h", 1) != b"\x01\x00":  # pragma: no cover - big-endian host
        samples.byteswap()
    return samples


def duration_ms(sample_count: int) -> int:
    return int(sample_count * 1000 / SAMPLE_RATE)


def embed(samples: array.array) -> bytes:
    """A voiceprint for one sample of 16kHz mono speech.

    The mean and standard deviation of each kept cepstral coefficient across
    the audible frames, L2-normalised and packed as little-endian float32.
    Normalising is what lets the comparison be a plain dot product and what
    keeps a 60-second print comparable with a four-second one.
    """

    frames = _frames(samples)
    if not frames:
        raise NotEnoughSpeech("sample is shorter than one analysis frame")

    ranked = sorted(energy for _, energy in frames)
    loudest = ranked[-1]
    median = ranked[len(ranked) // 2]
    if loudest - median < _MIN_ENERGY_SPREAD:
        raise NotEnoughSpeech("sample holds no audible speech to characterise")

    # Energies are logs, so the ratio the floor describes is a difference here.
    threshold = loudest + math.log(_SILENCE_FLOOR)
    speech = [frame for frame, energy in frames if energy >= threshold]
    if len(speech) < 2:
        raise NotEnoughSpeech("sample holds no audible speech to characterise")

    if len(speech) > _MAX_ANALYSIS_FRAMES:
        stride = len(speech) / _MAX_ANALYSIS_FRAMES
        speech = [speech[int(i * stride)] for i in range(_MAX_ANALYSIS_FRAMES)]

    audible = [_cepstra(frame) for frame in speech]
    dimensions = len(audible[0])
    means = [sum(frame[d] for frame in audible) / len(audible) for d in range(dimensions)]
    deviations = [
        math.sqrt(sum((frame[d] - means[d]) ** 2 for frame in audible) / len(audible))
        for d in range(dimensions)
    ]

    vector = means + deviations
    magnitude = math.sqrt(sum(value * value for value in vector))
    if magnitude == 0.0:  # pragma: no cover - requires perfectly constant cepstra
        raise NotEnoughSpeech("sample produced a degenerate voiceprint")
    return struct.pack(f"<{len(vector)}f", *(value / magnitude for value in vector))


def similarity(left: bytes, right: bytes) -> float:
    """Cosine similarity between two prints this module produced.

    Both are unit vectors, so this is their dot product. Prints of different
    lengths are refused rather than compared over the shorter one — that would
    answer a question nobody asked with a number that looks like an answer.
    """

    if len(left) != len(right) or len(left) % 4:
        raise ValueError("voiceprints are not comparable")
    count = len(left) // 4
    a = struct.unpack(f"<{count}f", left)
    b = struct.unpack(f"<{count}f", right)
    return max(-1.0, min(1.0, sum(x * y for x, y in zip(a, b, strict=True))))
