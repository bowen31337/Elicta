"""Turning a gate hit into the one question the operator sees (FR-5.8, FR-6.1).

Selection, not reasoning. The bank was drafted before the meeting; what
happens here is a choice between things already written, which is what keeps
the live path inside the conversational window.

The rate limit is the requirement with the sharpest teeth. A gate that fires
five times in one exchange is not five times as useful -- it is a panel the
operator stops looking at, and they stop for the rest of the meeting.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.modules.trigger.gate import evaluate
from app.modules.trigger.lexicon import UNQUANTIFIED_AMOUNT, UNQUANTIFIED_TIME
from app.modules.trigger.selection import select

NOW = datetime(2026, 8, 23, 9, 0, 0, tzinfo=UTC)


class _Candidate:
    """The shape the compiled bank hands over."""

    def __init__(self, identifier: str, section: str, phrasing: str, priority: int) -> None:
        self.id = identifier
        self.template_section = section
        self.phrasing = phrasing
        self.priority = priority


#: Both drafted against the same ambiguity, so these exercise ranking rather
#: than relevance -- the relevance rule has its own tests at the foot of this
#: file, and a fixture that conflated the two would pass for the wrong reason.
BANK = [
    _Candidate("cand-2", "Performance", "What would make the dashboard fast enough to sign off?", 2),
    _Candidate("cand-1", "Performance", "How fast does the dashboard have to be, in seconds?", 1),
]


def _hit():
    hit = evaluate("The dashboard just has to be fast.")
    assert hit is not None
    return hit


def test_the_question_comes_from_the_bank_rather_than_being_written_now() -> None:
    """The one architectural idea: reason before the meeting, select during it."""

    nudge = select(_hit(), BANK, now=NOW)

    assert nudge is not None
    assert nudge.question == "How fast does the dashboard have to be, in seconds?"
    assert nudge.candidate_id == "cand-1"


def test_the_highest_priority_candidate_wins() -> None:
    """Lower `priority` ranks higher, the ascending convention used elsewhere."""

    nudge = select(_hit(), BANK, now=NOW)

    assert nudge is not None
    assert nudge.candidate_id == "cand-1"


def test_the_trigger_reason_travels_with_the_nudge() -> None:
    """FR-5.11 again, at the boundary where it would be easiest to drop."""

    nudge = select(_hit(), BANK, now=NOW)

    assert nudge is not None
    assert nudge.trigger_reason == 'unquantified adjective — "fast"'


def test_a_second_nudge_inside_a_minute_is_refused() -> None:
    """FR-5.8. One per sixty seconds, however many passed the gate."""

    nudge = select(_hit(), BANK, now=NOW, last_surfaced_at=NOW - timedelta(seconds=30))

    assert nudge is None


def test_a_nudge_after_the_minute_is_allowed() -> None:
    nudge = select(_hit(), BANK, now=NOW, last_surfaced_at=NOW - timedelta(seconds=61))

    assert nudge is not None


def test_a_candidate_already_surfaced_is_not_surfaced_again() -> None:
    """Asking the same question twice reads as not having listened the first time."""

    nudge = select(_hit(), BANK, now=NOW, already_surfaced={"cand-1"})

    assert nudge is not None
    assert nudge.candidate_id == "cand-2"


def test_an_empty_bank_still_produces_a_question() -> None:
    """Degraded mode's promise, kept.

    The panel tells the operator that wording triggers still fire when the
    model cannot be reached. A bank is compiled by a model, so if an empty
    bank meant silence, that promise would be false exactly when it is being
    displayed. The question is then built from the term rather than drafted.
    """

    nudge = select(_hit(), [], now=NOW)

    assert nudge is not None
    assert nudge.candidate_id is None
    assert "fast" in nudge.question
    assert nudge.trigger_reason == 'unquantified adjective — "fast"'


def test_the_nudge_is_short_enough_to_read_without_breaking_eye_contact() -> None:
    """FR-6.1 caps nudge text at 25 words. The stub is the glanceable half."""

    nudge = select(_hit(), [], now=NOW)

    assert nudge is not None
    assert len(nudge.question.split()) <= 25
    assert len(nudge.stub.split()) <= 8


def test_a_bank_question_about_something_else_is_not_preferred_to_a_relevant_one() -> None:
    """The M2 embarrassment case, and the one that costs the most trust.

    A nudge carries its trigger reason, so the operator reads the reason and
    the question together. Pairing 'unquantified adjective — "flexible"' with
    a drafted question about response times tells them the product mistook
    what was just said. One of those is worse than a quiet panel: they stop
    reading the panel, and the reason line is what they stop believing.

    Ranking by priority alone does exactly that, because priority describes
    how much a question matters to the engagement, not whether it is about
    the sentence that just triggered it.
    """

    unrelated = [
        _Candidate("cand-9", "Performance", "What response time counts as a failure?", 1),
    ]
    hit = evaluate("The marshalling area has to be flexible.")
    assert hit is not None

    nudge = select(hit, unrelated, now=NOW)

    assert nudge is not None
    assert nudge.candidate_id is None, (
        f"an unrelated bank question was surfaced against 'flexible': {nudge.question}"
    )
    assert "flexible" in nudge.question


def test_a_bank_question_about_the_term_that_fired_is_preferred() -> None:
    """The case the bank exists for: a question drafted for this exact ambiguity."""

    bank = [
        _Candidate("cand-9", "Performance", "What response time counts as a failure?", 1),
        _Candidate(
            "cand-4",
            "Operations",
            "What has to stay flexible about the marshalling area, and within what limits?",
            5,
        ),
    ]
    hit = evaluate("The marshalling area has to be flexible.")
    assert hit is not None

    nudge = select(hit, bank, now=NOW)

    assert nudge is not None
    assert nudge.candidate_id == "cand-4", "the drafted question about this term should win"


class TestTheStubTellsOneNudgeFromAnother:
    """Reported from a live meeting: "why do I just see one nudge?"

    Three had fired, the panel was rendering all three, and every one carried
    the same headline — because the stub was looked up by trigger *category*
    and there are four categories. Same category, same words, however
    different the questions underneath.

    The glanceable half is the largest thing on the panel and was the only
    part carrying no information at all.
    """

    def test_two_hits_on_one_category_do_not_share_a_headline(self):
        """The exact shape of the report: "many", then "several"."""

        first = select(_hit_on("We move many pallets a day."), [], now=NOW)
        second = select(
            _hit_on("There are several bays."), [], now=NOW + timedelta(minutes=5)
        )

        assert first is not None and second is not None
        assert first.stub != second.stub

    def test_the_headline_names_what_the_client_actually_said(self):
        """Which is the fact worth the biggest text on the screen.

        It tells the operator which sentence the panel reacted to, so they can
        decide whether it read the room before they read the question.
        """

        nudge = select(_hit_on("There are several bays."), [], now=NOW)

        assert nudge is not None
        assert "several" in nudge.stub

    def test_it_stays_glanceable(self):
        """FR-6.1's cap is the whole reason the stub exists."""

        for utterance in (
            "We move many pallets a day.",
            "It needs to be fast.",
            "We need it soon.",
            "Typically that works.",
        ):
            nudge = select(_hit_on(utterance), [], now=NOW)
            if nudge is not None:
                assert len(nudge.stub.split()) <= 8, nudge.stub

    def test_a_chosen_bank_question_gets_the_same_treatment(self):
        """Not only the templated fallback — the reported case had a bank."""

        first = select(_hit_on("The dashboard must be fast."), BANK, now=NOW)
        second = select(
            _hit_on("Reporting should be flexible."),
            BANK,
            now=NOW + timedelta(minutes=5),
        )

        assert first is not None and second is not None
        assert first.stub != second.stub


def _hit_on(utterance: str):
    hit = evaluate(utterance)
    assert hit is not None, utterance
    return hit


class TestTheBankIsAskedByWhatItWasDraftedFor:
    """The reasoning the compiler did and the runtime threw away.

    Relevance was decided by whether the *question text* happened to contain
    the word the client said. The compiler already records `trigger_types` —
    which kinds of ambiguity each question was drafted to answer — and
    selection never looked at it.

    The cost is a templated question in place of a drafted one. A bank can
    hold twenty questions written for unquantified quantities, and a client
    saying "several" still got the generic fallback, because none of the
    twenty happened to contain the word "several".
    """

    def _candidate(self, identifier, phrasing, priority, *, triggers=(), stub=""):
        candidate = _Candidate(identifier, "Volumes", phrasing, priority)
        candidate.trigger_types = list(triggers)
        candidate.stub = stub
        return candidate

    def test_a_question_drafted_for_this_trigger_beats_the_templated_one(self):
        bank = [
            self._candidate(
                "cand-1",
                "How many consignments cross the dock in a week?",
                1,
                triggers=[UNQUANTIFIED_AMOUNT],
            )
        ]

        nudge = select(_hit_on("We move several pallets a day."), bank, now=NOW)

        assert nudge is not None
        assert nudge.candidate_id == "cand-1", "the bank had one and it was not used"

    def test_a_question_about_the_actual_word_is_still_preferred(self):
        """Category is the fallback for relevance, not a replacement for it.

        A question naming what the client just said is about *that sentence*;
        one merely drafted for the same kind of ambiguity is about the same
        kind of thing. The first is the better pairing with the reason line
        the operator reads beside it.
        """

        bank = [
            self._candidate(
                "by-category", "How many crates in a week?", 1,
                triggers=[UNQUANTIFIED_AMOUNT],
            ),
            self._candidate(
                "by-term", "Several pallets — how many is several?", 9,
                triggers=[UNQUANTIFIED_AMOUNT],
            ),
        ]

        nudge = select(_hit_on("We move several pallets a day."), bank, now=NOW)

        assert nudge is not None
        assert nudge.candidate_id == "by-term"

    def test_a_question_for_a_different_trigger_is_not_offered(self):
        """The embarrassment case: a mismatched pairing costs the reason line
        its credibility for the rest of the meeting."""

        bank = [
            self._candidate(
                "wrong-kind", "What date does that need to be?", 1,
                triggers=[UNQUANTIFIED_TIME],
            )
        ]

        nudge = select(_hit_on("We move several pallets a day."), bank, now=NOW)

        assert nudge is not None
        assert nudge.candidate_id is None, "a time question was offered for a quantity"

    def test_the_bank_supplies_the_headline_when_it_supplies_the_question(self):
        """The compiler drafts a stub per question; it was dropped in transit.

        The term-anchored stub built to work around that is still right for a
        templated question — there is no candidate to take one from — but a
        drafted question has its own, written for it.
        """

        bank = [
            self._candidate(
                "cand-1", "How many consignments cross the dock in a week?", 1,
                triggers=[UNQUANTIFIED_AMOUNT], stub="A week's crossings?",
            )
        ]

        nudge = select(_hit_on("We move several pallets a day."), bank, now=NOW)

        assert nudge is not None
        assert nudge.stub == "A week's crossings?"

    def test_a_templated_question_still_names_what_was_said(self):
        """No candidate means no drafted stub, and the fallback still applies."""

        nudge = select(_hit_on("We move several pallets a day."), [], now=NOW)

        assert nudge is not None
        assert "several" in nudge.stub
