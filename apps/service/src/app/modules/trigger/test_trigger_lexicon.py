"""The English lexicon here and the one in the Rust crate must stay the same list.

Two copies of a curated list drift, and the drift is silent: the live gate
starts firing on terms the replay harness never scores, and the replay numbers
stop describing the product. Comparing them costs one test.

Parsed out of the Rust source rather than shelled out to `cargo`, because this
suite runs where no Rust toolchain is required and a test that skips itself on
CI is not a gate.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.modules.trigger.lexicon import TERMS

CURATED = (
    Path(__file__).resolve().parents[6]
    / "core"
    / "crates"
    / "trigger-gate"
    / "src"
    / "lexicon"
    / "curated.rs"
)


def _rust_english_terms() -> set[str]:
    source = CURATED.read_text(encoding="utf-8")
    body = source.split("pub fn en_ambiguity_lexicon()", 1)[1].split("pub fn ", 1)[0]
    # Skips the identifier and language arguments on the first line, which are
    # quoted the same way the terms are.
    quoted = re.findall(r'"([^"]+)"', body)
    return {term for term in quoted if term not in {"en-ambiguity-v1", "en"}}


def test_the_rust_source_is_where_this_test_thinks_it_is() -> None:
    """Assert the file, not just the parse: a moved file would empty the set below."""

    assert CURATED.is_file(), f"the curated lexicon is not at {CURATED}"


def test_the_python_lexicon_carries_every_english_term_the_rust_one_does() -> None:
    rust = _rust_english_terms()

    assert rust, "parsed no terms out of the Rust lexicon — the parse, not the list, is wrong"
    assert set(TERMS) == rust, (
        "the two English lexicons have drifted; change both together.\n"
        f"only in Rust: {sorted(rust - set(TERMS))}\n"
        f"only in Python: {sorted(set(TERMS) - rust)}"
    )
