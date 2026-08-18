# numerals module — handoff

Implements PRD FR-2.17 (spoken-number normalisation, including Chinese 万/亿
magnitude grouping per architecture §14.1). Self-contained under this
directory; deliberately does not touch `core/crates/language/Cargo.toml` or
`core/crates/language/src/lib.rs`, since those are owned by the crate
scaffold and shared with sibling plugin submodules (`tags/`, `segment/`).

## Wiring needed (one line, in the shared `lib.rs`)

Whoever owns `core/crates/language/src/lib.rs` needs to add:

```rust
pub mod numerals;
```

No other integration is required — `numerals` has no dependency on `tags` or
`segment` and exposes a plain pure-text function:

```rust
pub use numerals::{normalize, Language};
```

## What's here

- `mod.rs` — public API: `normalize(text, Language) -> String`, plus the
  guaranteed-correct phrase converters `english_words_to_number` and
  `chinese_to_number` for callers that already know a span is a numeral
  (e.g. once the `segment`/`tags` pipeline lands and can hand this module a
  pre-identified numeral token span instead of raw text).
- `english.rs` — spelled-out English numbers (units, teens, tens, hundred,
  thousand/million/billion, `and`-bridging) → numerals.
- `chinese.rs` — Chinese digit + 十/百/千/万/亿 (incl. traditional 萬/億)
  magnitude parsing, via recursive split-on-largest-unit. Covers the
  specific FR-2.17 gap no ASR vendor's ITN closes: `三百五十万` → `3500000`.

## Known limitation (by design, documented in code)

Whole-text scanning for Chinese only converts runs of 2+ numeral
characters, because a single numeral-shaped hanzi is frequently part of an
ordinary word with no numeral meaning (十分 "extremely", 一起 "together").
This trades away converting a genuine solo numeral like standalone 十
("ten") for not corrupting ordinary prose. The real fix is for the
segmentation/tagging pipeline (features 120-122) to hand this module an
already-identified numeral span; `chinese_to_number` is exposed publicly for
exactly that integration.

Verified with `cargo test` (26 passing tests) in a scratch crate mirroring
this module tree, since the crate-level `Cargo.toml`/`lib.rs` are being
created concurrently by another task in a separate worktree and weren't
available here to build against directly.
