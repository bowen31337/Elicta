"""Turning uploaded audio into utterances the gate can read (PRD FR-5.1).

The capture screen already uploads linear16 in small chunks; each one on its
own is a fraction of a second and contains no sentence. Something has to
decide when enough has arrived to be worth asking a recogniser about, and that
decision costs money in both directions: too eager and every meeting is
charged for silence, too patient and the nudge misses the conversational
window it exists to land in.

Deliberately a fixed window rather than endpointing. Real endpointing needs
voice-activity detection -- `core/crates/capture` has it, and this process
cannot reach it -- so a sentence that straddles two windows is seen as two
halves. That is a real limitation of this path, written down rather than
hidden: the seam is shaped so a streaming backend that does its own
endpointing can replace the whole thing without the gate noticing.
"""

from __future__ import annotations

import pytest

from app.modules.trigger.listener import (
    BYTES_PER_SECOND,
    WINDOW_BYTES,
    WINDOW_SECONDS_ENV,
    LiveUtterances,
    window_bytes_from_env,
)


class _Recogniser:
    """A transcriber that answers from a script, and counts what it was asked."""

    def __init__(self, *answers: str) -> None:
        self.answers = list(answers)
        self.windows: list[bytes] = []
        self.sessions: list[str] = []

    async def __call__(self, session_id: str, pcm: bytes) -> str:
        self.sessions.append(session_id)
        self.windows.append(pcm)
        return self.answers.pop(0) if self.answers else ""


class _Observed:
    def __init__(self) -> None:
        self.seen: list[tuple[str, str]] = []
        #: Who the verifier said was speaking, per utterance, kept apart from
        #: `seen` so the existing assertions stay about the words.
        self.speakers: list[str | None] = []

    async def __call__(self, session_id: str, text: str, speaker: str | None = None) -> None:
        self.seen.append((session_id, text))
        self.speakers.append(speaker)


@pytest.mark.asyncio
async def test_a_part_window_is_not_sent_to_the_recogniser() -> None:
    """Every call is billed. A quarter-second of audio is not worth one."""

    recogniser = _Recogniser("never asked")
    observed = _Observed()
    listener = LiveUtterances(recogniser, observed, window_bytes=100)

    await listener.feed("meeting-1", b"\x00" * 40)

    assert recogniser.windows == []
    assert observed.seen == []


@pytest.mark.asyncio
async def test_a_full_window_reaches_the_gate_as_an_utterance() -> None:
    recogniser = _Recogniser("The dashboard has to be fast.")
    observed = _Observed()
    listener = LiveUtterances(recogniser, observed, window_bytes=100)

    await listener.feed("meeting-1", b"\x00" * 100)

    assert observed.seen == [("meeting-1", "The dashboard has to be fast.")]


@pytest.mark.asyncio
async def test_silence_produces_no_utterance() -> None:
    """A recogniser given a quiet window answers with nothing, and nothing is what it means.

    An empty utterance would reach the gate, match no term, and cost a round
    trip -- but a whitespace-only one would be worse, because `text` is
    required to be non-empty at the intake and this would start raising.
    """

    listener = LiveUtterances(_Recogniser("   "), (observed := _Observed()), window_bytes=100)

    await listener.feed("meeting-1", b"\x00" * 100)

    assert observed.seen == []


@pytest.mark.asyncio
async def test_audio_left_over_from_a_window_is_kept_for_the_next_one() -> None:
    """Dropping the remainder loses speech, and loses it silently."""

    recogniser = _Recogniser("first", "second")
    observed = _Observed()
    listener = LiveUtterances(recogniser, observed, window_bytes=100)

    await listener.feed("meeting-1", b"a" * 150)
    await listener.feed("meeting-1", b"b" * 50)

    assert [text for _, text in observed.seen] == ["first", "second"]
    assert recogniser.windows[0] == b"a" * 100
    # The 50 bytes left over from the first feed lead the second window.
    assert recogniser.windows[1] == b"a" * 50 + b"b" * 50


@pytest.mark.asyncio
async def test_two_meetings_do_not_share_a_buffer() -> None:
    """Mixing two rooms' audio into one window is the worst failure available here."""

    recogniser = _Recogniser("only one window")
    observed = _Observed()
    listener = LiveUtterances(recogniser, observed, window_bytes=100)

    await listener.feed("meeting-1", b"\x00" * 60)
    await listener.feed("meeting-2", b"\x00" * 60)

    assert recogniser.windows == []


@pytest.mark.asyncio
async def test_the_recogniser_is_told_which_session_it_is_hearing() -> None:
    """FR-2.9: the engagement's vocabulary reaches the recogniser, or it mis-hears the nouns."""

    recogniser = _Recogniser("anything")
    listener = LiveUtterances(recogniser, _Observed(), window_bytes=100)

    await listener.feed("meeting-7", b"\x00" * 100)

    assert recogniser.sessions == ["meeting-7"]


class _Verifier:
    """Stands in for speaker verification, and records what it was asked."""

    def __init__(self, answer: str | None) -> None:
        self.answer = answer
        self.windows: list[tuple[str, bytes]] = []

    async def __call__(self, session_id: str, window: bytes) -> str | None:
        self.windows.append((session_id, window))
        return self.answer


@pytest.mark.asyncio
async def test_an_utterance_carries_whoever_the_verifier_heard() -> None:
    """FR-1.6. The tag rides with the words to the gate, which skips its own."""

    observed = _Observed()
    listener = LiveUtterances(
        _Recogniser("We need it by March."),
        observed,
        identify=_Verifier("operator"),
        window_bytes=100,
    )

    await listener.feed("meeting-1", b"\x00" * 100)

    assert observed.speakers == ["operator"]


@pytest.mark.asyncio
async def test_the_verifier_is_asked_about_the_window_the_words_came_from() -> None:
    """Not a different slice, and not the whole buffer: FR-1.6 asks about the
    audio segment behind the utterance, and that is this window exactly."""

    verifier = _Verifier("other")
    listener = LiveUtterances(
        _Recogniser("Roughly a few thousand."), _Observed(), identify=verifier, window_bytes=100
    )

    await listener.feed("meeting-1", b"\x01" * 100)

    assert verifier.windows == [("meeting-1", b"\x01" * 100)]


@pytest.mark.asyncio
async def test_a_quiet_window_is_never_sent_for_verification() -> None:
    """Verification is the expensive step here. Spending it on a window the
    recogniser already found no words in buys nothing."""

    verifier = _Verifier("operator")
    listener = LiveUtterances(_Recogniser("   "), _Observed(), identify=verifier, window_bytes=100)

    await listener.feed("meeting-1", b"\x00" * 100)

    assert verifier.windows == []


@pytest.mark.asyncio
async def test_with_no_verifier_the_utterance_is_untagged_and_still_arrives() -> None:
    """The path every deployment that never enrols stays on."""

    observed = _Observed()
    listener = LiveUtterances(_Recogniser("It should be quick."), observed, window_bytes=100)

    await listener.feed("meeting-1", b"\x00" * 100)

    assert observed.seen == [("meeting-1", "It should be quick.")]
    assert observed.speakers == [None]


# --- the window, which is the live path's latency floor ------------------


def test_the_window_is_long_enough_to_hold_a_clause() -> None:
    """It was briefly one second, and that was measured afterwards.

    Shortening the window is the obvious move against latency and it makes
    this path *worse*, not merely coarser: the same 2.4 seconds of speech came
    back from Nova-3 as `'How are arrivals' / 'Today at the death'` at one
    second and `'How are arrivals booked in today at the'` at two — "depot"
    mis-heard as "death", because the recogniser had no context either side of
    the cut. A gate reading that is worse than a gate reading nothing.

    Latency is not solved here any more. It is solved by not having a window:
    the streamed lane ends a turn where the speaker does.
    """

    assert WINDOW_BYTES == BYTES_PER_SECOND * 4


@pytest.mark.asyncio
async def test_a_chunk_the_size_of_the_window_leaves_no_remainder() -> None:
    """The flat-lag property, as behaviour rather than arithmetic.

    Stated in windows rather than in chunks, because the uploader's chunk is
    smaller than this now and simply fills a window in pieces. What must never
    return is the *unequal* case that oscillated: a remainder that grows until
    two windows fire at once.
    """

    heard: list[str] = []
    sizes: list[int] = []

    async def recognise(session_id: str, window: bytes) -> str:
        sizes.append(len(window))
        return "a clause"

    async def observe(session_id: str, text: str, speaker: str | None) -> None:
        heard.append(text)

    utterances = LiveUtterances(recognise, observe)
    for _ in range(5):
        await utterances.feed("session-1", b"\x01\x02" * (WINDOW_BYTES // 2))

    # One window per chunk, every time — never none, never two at once.
    assert len(heard) == 5
    assert sizes == [WINDOW_BYTES] * 5


@pytest.mark.parametrize(
    ("configured", "expected_seconds"),
    [("", 4.0), ("2.5", 2.5), ("nonsense", 4.0), ("-1", 4.0), ("0", 4.0)],
)
def test_the_window_is_tunable_and_refuses_to_be_broken(
    monkeypatch: pytest.MonkeyPatch, configured: str, expected_seconds: float
) -> None:
    """The right window is a judgement about a room rather than a constant, so
    it is tunable without a rebuild — a pair finishing each other's sentences
    wants it short, a formal walkthrough wants the context.

    A value that cannot be read falls back rather than raising: refusing to
    start the whole service over a malformed tuning knob trades a
    slightly-wrong window for no service at all.
    """

    monkeypatch.setenv(WINDOW_SECONDS_ENV, configured)

    assert window_bytes_from_env() == BYTES_PER_SECOND * expected_seconds


def test_a_window_can_never_be_shorter_than_one_sample(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A window shorter than a single 16-bit sample would spin the drain loop
    forever on a buffer it can never empty — a hung request per chunk, for
    every meeting, out of one mistyped environment variable."""

    monkeypatch.setenv(WINDOW_SECONDS_ENV, "0.00001")

    assert window_bytes_from_env() >= 2
    # Whole samples, so a window never splits one down the middle.
    assert window_bytes_from_env() % 2 == 0
