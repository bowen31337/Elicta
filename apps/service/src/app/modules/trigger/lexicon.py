"""The English ambiguity lexicon (PRD FR-5.2).

Ported term-for-term from `core/crates/trigger-gate/src/lexicon/curated.rs`,
which is the build's curated English list. Two copies of a lexicon is a poor
thing, and this is the smaller evil: the Rust crate is not reachable from this
process, and the alternative on offer was no live trigger at all. They must be
changed together, and the test beside this file asserts they still agree.

Curated for English rather than translated into it. The Chinese list in that
crate is not represented here: an English-derived detector fires on a large
fraction of ordinary Chinese sentences (the PRD is explicit about pro-drop),
which breaches FR-5.7 immediately. A language gets its own list or none.
"""

from __future__ import annotations

#: Amounts stated without a number.
UNQUANTIFIED_AMOUNT = "unquantified_amount"
#: Adjectives asserting a property without a threshold.
UNQUANTIFIED_PROPERTY = "unquantified_property"
#: Time stated without a date.
UNQUANTIFIED_TIME = "unquantified_time"
#: Agreement withdrawn by the qualifier attached to it.
QUALIFIED_AGREEMENT = "qualified_agreement"

#: How each category is described to the operator (FR-5.11). Phrased as the
#: thing that was noticed, not as the rule that noticed it: "unquantified
#: adjective" tells an operator what to ask about, "lexicon match on term 14"
#: tells them nothing they can act on mid-sentence.
CATEGORY_REASONS: dict[str, str] = {
    UNQUANTIFIED_AMOUNT: "vague quantifier",
    UNQUANTIFIED_PROPERTY: "unquantified adjective",
    UNQUANTIFIED_TIME: "time without a date",
    QUALIFIED_AGREEMENT: "hedged commitment",
}

#: The lexicon itself, term to category.
TERMS: dict[str, str] = {
    # -- amounts ----------------------------------------------------------
    "several": UNQUANTIFIED_AMOUNT,
    "a lot": UNQUANTIFIED_AMOUNT,
    "a couple": UNQUANTIFIED_AMOUNT,
    "a few": UNQUANTIFIED_AMOUNT,
    "a handful": UNQUANTIFIED_AMOUNT,
    "some": UNQUANTIFIED_AMOUNT,
    "many": UNQUANTIFIED_AMOUNT,
    "quite a few": UNQUANTIFIED_AMOUNT,
    "a bunch of": UNQUANTIFIED_AMOUNT,
    "reasonable amount": UNQUANTIFIED_AMOUNT,
    # -- properties -------------------------------------------------------
    "fast": UNQUANTIFIED_PROPERTY,
    "robust": UNQUANTIFIED_PROPERTY,
    "scalable": UNQUANTIFIED_PROPERTY,
    "flexible": UNQUANTIFIED_PROPERTY,
    "efficient": UNQUANTIFIED_PROPERTY,
    "user-friendly": UNQUANTIFIED_PROPERTY,
    "significant": UNQUANTIFIED_PROPERTY,
    # -- time -------------------------------------------------------------
    "quickly": UNQUANTIFIED_TIME,
    "soon": UNQUANTIFIED_TIME,
    "recently": UNQUANTIFIED_TIME,
    "as soon as possible": UNQUANTIFIED_TIME,
    # -- hedges -----------------------------------------------------------
    "as needed": QUALIFIED_AGREEMENT,
    "if possible": QUALIFIED_AGREEMENT,
    "typically": QUALIFIED_AGREEMENT,
    "generally": QUALIFIED_AGREEMENT,
}
