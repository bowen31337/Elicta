# segment module — handoff

Implements the "merge spans" box of the architecture §3.5 pipeline: after
`group_by_language` splits an utterance's tokens by language and each
group's `Segmenter` turns its tokens into lexicon-matchable spans, those
per-language span lists need to come back together into one ordered list per
utterance. This directory's own module doc (`mod.rs`) previously flagged
that step as explicitly out of scope ("it does not own merging spans back
into utterance order") — this feature implements it.

Self-contained under this directory, same as `numerals/` — deliberately does
not touch `core/crates/language/Cargo.toml` or `core/crates/language/src/lib.rs`,
which do not exist yet in this worktree (confirmed via `find`; `numerals/HANDOFF.md`
already flags this as pending from another concurrent task).

## What's here

- `merge.rs` — `merge_spans(routed: Vec<(String, Vec<Span>)>) -> Vec<Span>`.
  Flattens the `(language, spans)` pairs `SegmenterRouter::route` returns and
  sorts by `(start_index, end_index)`, restoring original utterance token
  order across language groups. The sort is stable, so spans sharing a
  `start_index` (e.g. `CharSegmenter`'s per-character spans, all built from
  one token) keep their segmenter's relative order rather than being
  shuffled against each other.
- `segmenter.rs` — added `SegmenterRouter::route_merged`, chaining `route`
  then `merge_spans` for callers that only want the final per-utterance span
  list.
- `mod.rs` — declares `pub mod merge;`, re-exports `merge_spans`, and
  corrects the module doc's now-outdated claim that this module doesn't own
  the merge step.

## Wiring needed (same one line `numerals/HANDOFF.md` already asked for)

Whoever creates `core/crates/language/src/lib.rs` needs:

```rust
pub mod numerals;
pub mod segment;
pub mod tags;
```

No other integration is required. `merge_spans` has no dependency on
`numerals` or `tags`; it only consumes this module's own `Span` type.

## What's not done here

- Downstream consumption of the merged span list (lexicon matching, trigger
  gate assembly) — out of scope per the architecture §3.5 diagram, which
  places "merge spans" before lexicon matching, not as part of it.
- Dropping spans below tag-confidence threshold (FR-2.22) already happens
  earlier, inside `group_by_language` (a token is dropped before it ever
  reaches a segmenter), so there is nothing left to filter at merge time.

Verified standalone (copied into a scratch crate mirroring this module tree,
mirroring `numerals`' verification approach, since the crate-level
`Cargo.toml`/`lib.rs` don't exist here yet): `cargo test` — 62/62 pass (5
new); `cargo clippy --all-targets -- -D warnings` — clean; `rustfmt --check`
on `merge.rs`, `mod.rs`, `segmenter.rs` — clean (pre-existing formatting
drift in sibling `numerals`/`tags` files predates this feature and was left
untouched).
