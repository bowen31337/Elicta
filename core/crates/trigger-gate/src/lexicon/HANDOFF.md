# lexicon module — handoff

Implements feature 145: "System runs each language lexicon only over the
tokens tagged as that language" (PRD section 8.2a). This is the first
feature to land in `core/crates/trigger-gate` in this worktree — the crate
directory did not exist before this change (confirmed via `find`).

Self-contained under this directory, following the same convention as
`language/src/segment` and `language/src/numerals`: deliberately does not
create `core/crates/trigger-gate/Cargo.toml` or
`core/crates/trigger-gate/src/lib.rs`. Those are crate scaffold, owned by
whoever wires up the crate, and shared with sibling plugin submodules
(`parse/`, `ratelimit/`) that other trigger-gate features touch.

## What's here

- `grouping.rs` — `TaggedToken` / `PositionedToken` / `LanguageGroup` /
  `group_by_language`. Mirrors `language::segment`'s types of the same name
  field-for-field. Duplicated locally rather than imported: `trigger-gate`
  and `language` are separate crates with no `Cargo.toml` linking them yet
  (neither crate has one in this worktree), so there is no way to depend on
  the other crate today. Re-point at the shared types once crate wiring
  lands.
- `terms.rs` — `Lexicon` (a curated, per-language term list) and
  `LexiconMatch`. `Lexicon::scan` takes a slice of already-grouped
  `PositionedToken`s and has no visibility into any token outside that
  slice — it stamps every match with its own `language`, not the token's.
  Matching is a plain case-insensitive substring scan; the Aho-Corasick
  engine (FR-5.2, presumably a sibling feature in this same directory) is a
  drop-in performance replacement over the same `scan` contract and
  `LexiconMatch` shape — it does not need to change how routing works.
- `router.rs` — `LexiconRouter`, holding one `Lexicon` per language.
  `LexiconRouter::run` groups an utterance's tokens by language tag, looks
  up *that group's* language in its lexicon map, and scans only that group
  with only that lexicon. A language present in the utterance with no
  registered lexicon contributes zero matches — it is never scanned by a
  different language's lexicon as a fallback. Matches are returned sorted by
  original token index, restoring utterance order across languages.
- `mod.rs` — module doc laying out the rationale and re-exports.

## Why this satisfies "a token emits matches only from its own language
lexicon"

The isolation is structural, not a convention callers have to honor:
`group_by_language` partitions tokens so each `LanguageGroup` contains only
one language's tokens, and `LexiconRouter::run` looks up the lexicon to scan
a group with *from that group's own `language` field* — there is no code
path that hands a group to any other lexicon. `router.rs`'s
`a_token_never_matches_a_different_languages_lexicon` test proves this
directly: both an `en` and a `zh` lexicon are registered with the identical
literal term `"many"`, and a token tagged `en` still produces exactly one
match, tagged `en` — the `zh` lexicon is never run over it despite
containing a term that would otherwise match.

`code_switched_utterance_matches_both_languages_neither_half_discarded`
covers the other half of the feature description: a mixed-language
utterance (the architecture §3.5 example sentence, "这个 API 的 latency
要求是什么", extended with one ambiguity term per language) produces a match
for *both* languages, not just whichever one a single-lexicon design would
have picked.

## Wiring needed (same one line `numerals/HANDOFF.md` and
`segment/HANDOFF.md` already asked for in `language`)

Whoever creates `core/crates/trigger-gate/src/lib.rs` needs:

```rust
pub mod lexicon;
```

No other integration is required. `lexicon` has no dependency on any other
trigger-gate submodule (`parse/`, `ratelimit/`) that may land alongside it.

## What's not done here

- The Aho-Corasick matching engine itself (FR-5.2) and the <20ms latency
  budget (feature 143) — `Lexicon::scan` is a correct but not
  performance-optimised substring scan; it exists to prove and test the
  routing/isolation contract, not to be the final matching algorithm.
- Loading lexicons from a curated data source per language (feature 144) —
  `Lexicon::new` takes an in-memory term list; nothing here reads lexicon
  files or assigns a persisted lexicon identifier.
- The overall gate evaluation loop that decides which utterances reach this
  module at all (feature 141), interim-hypothesis holding (feature 153), and
  span-confidence suppression (feature 148) — all out of scope per this
  feature's own "Done when" criterion, which is specifically about
  per-language isolation of an already-tagged token stream.

Verified standalone (copied into a scratch crate mirroring this module
tree, matching `numerals`'/`segment`'s verification approach, since
`core/crates/trigger-gate/Cargo.toml`/`lib.rs` don't exist): `cargo test` —
16/16 pass; `cargo clippy --all-targets -- -D warnings` — clean; `rustfmt
--check` on all four files — clean.
