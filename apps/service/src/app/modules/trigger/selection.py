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

#: The glanceable half (FR-6.3): what an operator can take in without turning
#: away from the client. Deliberately not the question itself.
STUBS: dict[str, str] = {
    UNQUANTIFIED_AMOUNT: "How many, exactly?",
    UNQUANTIFIED_PROPERTY: "In numbers?",
    UNQUANTIFIED_TIME: "By when, exactly?",
    QUALIFIED_AGREEMENT: "Always, or sometimes?",
}

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

    stub = STUBS[hit.category]
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
    about_this = [
        candidate for candidate in unused if mentions_term(hit.term, candidate.phrasing)
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
        stub=stub,
        question=chosen.phrasing,
        trigger_reason=hit.reason,
        created_at=now,
        candidate_id=chosen.id,
    )
