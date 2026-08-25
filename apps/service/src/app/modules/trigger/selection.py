"""Choose the one question a gate hit earns (PRD FR-5.8, FR-6.1, FR-6.3).

Selection over generation, which is the architecture's central claim: the
bank was reasoned about before the meeting, and the meeting only picks from
it. That is what fits inside the conversational window -- a retrieval in tens
of milliseconds where a model call is seconds.

The fallback wording here is the one thing written at runtime, and it is
templated rather than generated for the same reason: degraded mode promises
the operator that wording triggers still fire when no model can be reached
(architecture section 10), and a promise kept by calling a model is not kept.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

from .gate import TriggerHit
from .lexicon import (
    QUALIFIED_AGREEMENT,
    UNQUANTIFIED_AMOUNT,
    UNQUANTIFIED_PROPERTY,
    UNQUANTIFIED_TIME,
)

#: FR-5.8. Not a tuning knob: the number is in the requirement because the
#: cost of exceeding it is an operator who stops reading the panel, and that
#: cost is not recovered by going quiet again later.
MINIMUM_GAP = timedelta(seconds=60)

#: The ask, per category, in as few words as it can be put.
#:
#: Joined to the term that fired rather than used alone. Alone there are four
#: of these and a meeting raises many more nudges than that, so every nudge
#: from one category carried the identical headline — reported from a live
#: meeting as "why do I just see one nudge?", with three on screen and the
#: largest text on each of them the same four words.
#:
#: The term is what makes them differ, and it is also the more useful half:
#: the stub is the one line an operator reads without turning away from the
#: client, and "which of their words did this react to" is what tells them
#: whether it heard the room — before they read the question.
ASKS: dict[str, str] = {
    UNQUANTIFIED_AMOUNT: "how many?",
    UNQUANTIFIED_PROPERTY: "in numbers?",
    UNQUANTIFIED_TIME: "by when?",
    QUALIFIED_AGREEMENT: "always?",
}


#: The most words a headline may carry and still be read without looking away
#: from the client. FR-6.2 asks for three to five; this is the point at which
#: a stub has stopped being one, not the target — refusing a good six-word
#: headline in favour of a generic four-word one would be the same mistake
#: the candidate-count floor already learned not to make.
GLANCEABLE_WORDS = 8


def glanceable(stub: str) -> str | None:
    """The bank's headline, if it can actually be glanced at.

    `None` where it cannot, so the caller uses the templated one instead.
    Not trimmed: a sentence cut mid-way is worse than a plain headline, and
    the templated stub is a real one.

    Needed because selection began preferring the bank's stub — which is the
    right preference, since it says what *this* question asks — and the
    schema that produces it sets a minimum length and no maximum. The
    headline it replaced came from a four-entry table and was glanceable by
    construction.
    """

    words = stub.split()
    return stub.strip() if 0 < len(words) <= GLANCEABLE_WORDS else None


def stub_for(category: str, term: str) -> str:
    """The glanceable half (FR-6.3), anchored to what was actually said.

    Built here rather than read off the chosen candidate because the bank
    does not carry one: the compiler drafts a stub per question and it is
    dropped before persistence, so recovering it needs a schema change and a
    recompile of every candidate. This costs nothing, works on a bank already
    compiled, and stays a pure function — which the replay parity gates
    require of everything on this path.
    """

    return f"\u201c{term}\u201d \u2014 {ASKS[category]}"

#: Asked when the operator wants to follow a thread further, and the bank has
#: nothing left about it. Deliberately a different question from the first
#: rather than a rephrasing: "go deeper" that returned the same thing in other
#: words would read as the product not having understood the tap.
DEEPER_QUESTIONS: dict[str, str] = {
    UNQUANTIFIED_AMOUNT: 'You said "{term}" — what is that on a bad day, rather than a typical one?',
    UNQUANTIFIED_PROPERTY: 'You said "{term}" — what happens today when it is not?',
    UNQUANTIFIED_TIME: 'You said "{term}" — what is driving that date?',
    QUALIFIED_AGREEMENT: 'You said "{term}" — what are the exceptions, and how often do they happen?',
}

#: Used only when the bank has nothing left to offer.
FALLBACK_QUESTIONS: dict[str, str] = {
    UNQUANTIFIED_AMOUNT: 'You said "{term}" — how many is that, in numbers?',
    UNQUANTIFIED_PROPERTY: 'You said "{term}" — what number would you measure that against?',
    UNQUANTIFIED_TIME: 'You said "{term}" — what date does that need to be?',
    QUALIFIED_AGREEMENT: 'You said "{term}" — is that always, or are there exceptions?',
}


class Candidate(Protocol):
    """The part of a compiled bank candidate selection reads."""

    id: str
    template_section: str
    phrasing: str
    priority: int
    #: What the compiler drafted this question to answer, in the gate's own
    #: vocabulary, and its glanceable form. Both optional: a bank compiled
    #: before they were carried has neither, and must go on working.
    trigger_types: list[str]
    stub: str


@dataclass(frozen=True)
class SelectedNudge:
    """One surfaced question, and why it was surfaced."""

    stub: str
    question: str
    trigger_reason: str
    created_at: datetime
    #: `None` when the wording was templated because the bank had nothing.
    candidate_id: str | None


def mentions_term(term: str, phrasing: str) -> bool:
    """Whether a drafted question is about this term.

    Bounded like the gate's own matching, and for the same reason: "some"
    inside "somebody" is not the question being answered here either.
    """

    return re.search(rf"\b{re.escape(term)}\b", phrasing, re.IGNORECASE) is not None


def select(
    hit: TriggerHit,
    candidates: Any,
    *,
    now: datetime,
    last_surfaced_at: datetime | None = None,
    already_surfaced: Any = frozenset(),
) -> SelectedNudge | None:
    """The nudge this hit earns, or `None` if it earns none.

    Refusing is the common answer and the important one. Most utterances that
    pass the gate arrive inside a minute of the last nudge, and the right
    thing to do with them is nothing at all.
    """

    if last_surfaced_at is not None and now - last_surfaced_at < MINIMUM_GAP:
        return None

    stub = stub_for(hit.category, hit.term)
    unused = [
        candidate for candidate in candidates if candidate.id not in already_surfaced
    ]
    # Relevance before rank. `priority` says how much a question matters to
    # the engagement, not whether it is about the sentence that just fired --
    # so ranking on it alone pairs a drafted question about response times
    # with the reason 'unquantified adjective — "flexible"'. The operator
    # reads those two lines together, and a pair that does not match tells
    # them the product misheard the room. That is the M2 embarrassment case,
    # and it costs the reason line its credibility for the rest of the
    # meeting.
    # Relevance in two tiers, and the order matters.
    #
    # A question naming what the client just said is about *that sentence*.
    # One merely drafted for the same kind of ambiguity is about the same kind
    # of thing — weaker, but far better than the templated fallback, which is
    # what a bank of twenty quantity questions was reduced to whenever none of
    # them happened to contain the word "several".
    #
    # Additive on purpose: the first tier is exactly what this did before, so
    # a bank compiled without `trigger_types` — every bank that exists today —
    # selects precisely as it always has, and gains the second tier when it is
    # next compiled.
    about_this = [
        candidate for candidate in unused if mentions_term(hit.term, candidate.phrasing)
    ] or [
        candidate
        for candidate in unused
        if hit.category in (getattr(candidate, "trigger_types", None) or ())
    ]
    # Lower `priority` ranks higher — the ascending convention `OpenQuestion`
    # and `BankCandidate` already use. Ties keep the order the bank was
    # compiled in, which is the compiler's own ranking.
    chosen = min(about_this, key=lambda candidate: candidate.priority, default=None)

    if chosen is None:
        return SelectedNudge(
            stub=stub,
            question=FALLBACK_QUESTIONS[hit.category].format(term=hit.term),
            trigger_reason=hit.reason,
            created_at=now,
            candidate_id=None,
        )

    return SelectedNudge(
        # The bank's own headline where it has one. The term-anchored stub
        # above was built because the bank carried none, and it is still what
        # a templated question gets — there is no candidate to take one from.
        # A drafted question has a stub written for it, which says what *this*
        # question asks rather than which rule fired.
        stub=glanceable(getattr(chosen, "stub", "") or "") or stub,
        question=chosen.phrasing,
        trigger_reason=hit.reason,
        created_at=now,
        candidate_id=chosen.id,
    )
