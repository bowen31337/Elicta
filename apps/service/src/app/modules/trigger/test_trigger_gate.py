"""The deterministic half of the trigger gate (PRD FR-5.1, FR-5.2, FR-5.11).

This is the path with no model call in it. The PRD is explicit that it will
carry more weight than expected, and that its precision is the whole game:
FR-5.7 caps the gate at about one utterance in ten, because an operator who
is interrupted more often than that stops reading the panel — and a panel
nobody reads is worse than no panel, having cost the attention anyway.

Every hit carries the term that caused it (FR-5.11). Without that the
operator cannot tell in half a second whether the product understood the room
or misheard it, which is the judgement the whole interface rests on.
"""

from __future__ import annotations

from app.modules.trigger.gate import evaluate


def test_an_unquantified_adjective_is_a_hit() -> None:
    """FR-5.2's headline case, and the PRD's own worked example."""

    hit = evaluate("The dashboard just has to be fast.")

    assert hit is not None
    assert hit.term == "fast"
    assert hit.category == "unquantified_property"


def test_the_hit_names_the_term_that_caused_it() -> None:
    """FR-5.11. A reason the operator cannot read is not a reason."""

    hit = evaluate("The dashboard just has to be fast.")

    assert hit is not None
    assert '"fast"' in hit.reason
    assert "adjective" in hit.reason


def test_a_term_inside_a_longer_word_is_not_a_hit() -> None:
    """The precision rule that decides whether FR-5.7 is met or missed.

    A substring match fires on "fastener", "somebody", "manyfold" and a long
    tail of ordinary speech. Each one costs an interruption in a client
    meeting, so the boundary is not a nicety.
    """

    assert evaluate("Tighten the fastener on the loading bay door.") is None
    assert evaluate("Somebody from the depot signs it off.") is None


def test_a_multi_word_quantifier_is_a_hit() -> None:
    """"a lot" is two words and one term; matching only single words misses it."""

    hit = evaluate("We move a lot of pallets through Derby.")

    assert hit is not None
    assert hit.term == "a lot"
    assert hit.category == "unquantified_amount"


def test_a_time_without_a_date_is_a_hit() -> None:
    hit = evaluate("We need the depot cut over soon.")

    assert hit is not None
    assert hit.category == "unquantified_time"


def test_an_utterance_with_nothing_vague_in_it_is_not_a_hit() -> None:
    """The common case by a wide margin, and the one FR-5.7 is about."""

    assert evaluate("We run three hundred and fifty consignments a day.") is None
