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

from app.modules.trigger.listener import LiveUtterances


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
