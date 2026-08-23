"""Evaluate one finalised utterance against the lexicon (PRD FR-5.1, FR-5.2).

No model call happens here, and that is the point: this is the path the
architecture calls the highest-value one, answering in microseconds while a
model answers in seconds. The meeting only does selection.

What this deliberately does not implement is FR-5.3 (unnamed actors), which
needs a parse rather than a term list, and FR-5.4-5.6, which need the context
pack. A gate that guessed at those would spend its FR-5.7 budget on them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .lexicon import CATEGORY_REASONS, TERMS


@dataclass(frozen=True)
class TriggerHit:
    """Why this utterance is worth interrupting a meeting for."""

    term: str
    category: str
    #: Rendered for the operator, and carried onto the nudge (FR-5.11).
    reason: str


def _pattern() -> re.Pattern[str]:
    """One alternation over the lexicon, longest term first.

    Longest-first matters: "a few" and "quite a few" overlap, and a shortest-
    first alternation reports the wrong term for the second — which reaches
    the operator as a reason that does not match what they heard.

    The boundaries are what keep FR-5.7 reachable. Without them "some" fires
    on "somebody", "many" on "manyfold" and "fast" on "fastener", each one
    costing an interruption in front of a client.
    """

    ordered = sorted(TERMS, key=len, reverse=True)
    alternation = "|".join(re.escape(term) for term in ordered)
    return re.compile(rf"\b(?:{alternation})\b", re.IGNORECASE)


_LEXICON = _pattern()


def evaluate(text: str) -> TriggerHit | None:
    """The first lexicon term in `text`, or `None` if it holds none.

    First rather than every: FR-5.8 surfaces one nudge at a time regardless of
    how many terms passed, so collecting the rest would be work whose only
    consumer discards it.
    """

    found = _LEXICON.search(text)
    if found is None:
        return None
    term = found.group(0).lower()
    category = TERMS[term]
    return TriggerHit(term=term, category=category, reason=f'{CATEGORY_REASONS[category]} — "{term}"')
