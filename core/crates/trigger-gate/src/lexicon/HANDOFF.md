# lexicon module — handoff

## Update: Aho-Corasick lexicon matching, returning the matched span (PRD FR-5.2)

Implements "System detects unquantified adjectives and vague quantifiers by
Aho-Corasick match over a curated lexicon, returning the matched span (PRD
FR-5.2). Done when a match emits the offending span on the trigger event."
Both `terms.rs`'s and the crate-root `HANDOFF.md`'s own prior "what's not
done" sections named this explicitly: `Lexicon::scan` was "a correct but not
performance-optimised substring scan; it exists to prove and test the
routing/isolation contract, not to be the final matching algorithm," with
"the Aho-Corasick engine (FR-5.2)... a drop-in performance replacement over
the same `scan` contract and `LexiconMatch` shape." This change is that
replacement — plus the part neither prior "what's not done" note called out:
`LexiconMatch` never actually carried a matched span at all, only a whole
token's `matched_text`, so "returning the matched span" needed a real new
field, not just a faster scan.

### What's here

- `ahocorasick.rs` — a small `AhoCorasick` automaton: a byte-level trie with
  Aho-Corasick failure links, built once per `Lexicon` (in `Lexicon::new`)
  from its curated term list and reused across every token it scans.
  `AhoCorasick::find_all` walks a haystack once and returns every occurrence
  of every pattern — including overlapping patterns and repeat occurrences of
  the same term — as `(pattern_index, byte_range)`. No new Cargo dependency:
  this is a from-scratch implementation kept inside `lexicon/`, the same
  choice `grouping.rs` made for `TaggedToken` and the crate-root `HANDOFF.md`
  made for not creating `Cargo.toml`/`lib.rs` — adding a real `aho-corasick`
  crate dependency would mean editing `core/crates/trigger-gate/Cargo.toml`,
  outside this change's own `lexicon/**` footprint and, per this crate's own
  established pattern, "crate scaffold, owned by whoever wires up the
  crate." (Confirmed `cargo add aho-corasick --dry-run` resolves fine if a
  future change decides to swap this for the published crate instead —
  network access to crates.io was available when this change was made — but
  swapping is a Cargo.toml-touching change this one deliberately did not
  make.)
- `terms.rs` — `Lexicon` now holds a built `AhoCorasick` automaton alongside
  its term list, and `Lexicon::scan` calls `automaton.find_all` once per
  token instead of looping `str::contains` once per curated term. `Lexicon`
  and `LexiconRouter`'s public contracts are otherwise unchanged — this really
  is the "drop-in" replacement the prior HANDOFF predicted. `LexiconMatch`
  gained one new field, `span: Range<usize>` — the matched phrase's own byte
  range within the token's (lower-cased) text, exactly what FR-5.2 asks the
  gate to return. `matched_text` changed meaning to match: it used to be the
  *whole* token's original-case text regardless of how much of it actually
  matched; it is now the exact matched substring, sliced from the same
  lower-cased haystack `span` was computed against (never the original-case
  text at the same offsets — lower-casing can change a character's byte
  length for a handful of Unicode code points, so slicing the original text
  at a lower-cased haystack's offsets risks a byte-boundary panic; slicing
  the same string the span came from cannot).
- `evaluation.rs` — `token_span` (private) now takes the match's own `span`
  and adds it to the token's start offset in the space-joined utterance
  string, instead of returning the whole token's span. This is the other
  half of "a match emits the offending span on the trigger event": before
  this change, `TriggerEvent.span` covered the entire token a match was
  found in, even when the curated term was only part of that token's text
  (e.g. `hold.rs`'s own tests already use tokens like `"we need several"`).
  After this change it covers exactly the offending phrase.
- `hold.rs` — one existing test's hand-built `LexiconMatch` literal
  (`endpoint_revising_the_matched_text_away_discards_the_held_candidate`)
  updated for the new `span` field and narrowed `matched_text` — the token
  text used there, `"we need several"`, matches against the term
  `"several"`, so the real value coming out of `scan` is now `"several"`
  at `8..15`, not the whole token text FR-5.9's tests never actually
  asserted on for its own sake.

### Why this satisfies "a match emits the offending span on the trigger
event"

`LexiconMatch::span` is populated directly from `AhoCorasick::find_all`'s own
return value — there is no path through `Lexicon::scan` that fabricates a
placeholder span or falls back to the whole token. `terms.rs`'s
`scan_reports_the_matched_terms_own_span_within_the_token` proves the span is
exactly the matched substring's own range, not the token's.
`scan_finds_every_occurrence_of_a_term_repeated_in_one_token` and
`scan_finds_every_distinct_curated_term_in_one_pass_over_a_token` prove the
Aho-Corasick property this scan is actually named for: one left-to-right
pass finds every occurrence of every curated term, rather than one
`str::contains` call per term (a repeat occurrence of the same term is two
matches with two distinct spans, not one). `ahocorasick.rs`'s own
`overlapping_patterns_sharing_a_prefix_are_both_reported` test is the
textbook Aho-Corasick correctness case (`"he"`/`"she"`/`"his"`/`"hers"`),
proving the failure-link construction doesn't drop a shorter, overlapping
match the way a naive trie walk without failure links would.
`evaluation.rs`'s new
`event_span_narrows_to_the_matched_phrase_not_the_whole_token` proves the
final `TriggerEvent.span` a caller actually receives reflects the same
narrowing, not just `LexiconMatch.span` in isolation — a token carrying extra
words around the matched term produces an event span that covers only the
term.

### What's not done here

- Swapping this hand-rolled automaton for the published `aho-corasick` crate
  — as noted above, that requires editing `Cargo.toml`, outside this
  change's `lexicon/**` footprint. The two have the same asymptotic behavior
  over a fixed curated lexicon; the published crate would add SIMD-accelerated
  scanning and Unicode-aware options this change's byte-level trie does not
  attempt, which matters for feature 143's <20ms latency budget under a much
  larger lexicon than this crate's tests exercise — worth revisiting if that
  budget is ever measured against this scan and found wanting.
- Deduplicating an occurrence that both an exact node and a fail-link suffix
  would otherwise double-report — this cannot actually happen with the
  current curated lexicons (no two curated terms are one a suffix of the
  other in the test lexicons), but a future lexicon that curated, say, both
  `"a lot"` and `"lot"` would get two separate `LexiconMatch`es for one
  occurrence of `"a lot"`, each with its own correct-but-overlapping span.
  Nothing here decides whether that's the right behavior (arguably it is —
  both are independently curated ambiguity terms) or something a caller
  should collapse.

Verified with `cargo test -p trigger-gate` (72/72 pass — 60 prior tests
untouched except the one `hold.rs` literal above, 12 new tests across
`ahocorasick.rs`, `terms.rs`, and `evaluation.rs`), `cargo clippy -p
trigger-gate --all-targets -- -D warnings` (clean), `cargo fmt -p
trigger-gate -- --check` (clean for every file this change touched;
`ratelimit/regulation.rs` and `ratelimit/storm.rs` still carry the same
pre-existing, unrelated formatting diffs every prior update in this file has
already noted and left alone), and `cargo build --workspace` (still
succeeds).

## Update: the gate evaluation loop (PRD FR-5.1)

Implements "System evaluates every finalised utterance whose speaker tag is
not operator against the trigger gate (PRD FR-5.1). Done when every
non-operator utterance emits a gate decision." This is "feature 141" —
"the overall gate evaluation loop that decides which utterances reach this
module at all" — that every prior HANDOFF in this crate (`lexicon`'s own
feature-145 and FR-5.9 sections below, `parse/HANDOFF.md`,
`ratelimit/HANDOFF.md`) named and explicitly deferred. Architecture §3.5
states it plainly: "FR-5.1 requires every finalised utterance to be
evaluated; the gate refines this by evaluating only utterances whose
`speaker` is not `Operator`, since a nudge prompting the operator to
interrogate their own sentence is never useful."

### What's here

- `evaluation.rs` — `SpeakerTag` (`Operator` / `Participant(String)` /
  `Unknown`, mirroring `asr-live::backend::event::SpeakerTag` field-for-field
  for the same no-Cargo-dependency-yet reason `grouping::TaggedToken`
  mirrors `language::segment`'s type), `FinalisedUtterance` (`id`,
  `speaker`, `tokens`), `GateDecision` (`utterance_id`, `events`), and
  `evaluate_utterance`. `evaluate_utterance` is the first place a `speaker`
  tag and a lexicon match ever meet in this crate: it returns `None` for an
  `Operator`-tagged utterance without touching the router at all, and
  `Some(GateDecision)` for every other utterance — routing its tokens
  through an existing `LexiconRouter` (feature 145), then running each
  resulting match through `parse::gate_span_confidence` (NFR-5.6) to produce
  one `TriggerEvent` per match. A `GateDecision` is returned even when
  `events` is empty: "nothing matched" is itself the gate's decision for
  that utterance, not the absence of one.
- `mod.rs` — re-exports `evaluate_utterance`, `FinalisedUtterance`,
  `GateDecision`, `SpeakerTag` alongside the existing exports.

A private `token_span` helper turns a `LexiconMatch`'s `token_index` into
the `Range<usize>` `gate_span_confidence` needs, by reconstructing the
utterance's tokens as one ASCII-space-joined string and locating that
token's own slice within it. This is a genuinely new answer to a question
`parse/HANDOFF.md` left open ("Turning a `lexicon::LexiconMatch` plus the
`TaggedToken`s it was matched from into the `(span, word_confidences)`
`gate_span_confidence` takes ... not decided here") — neither `TaggedToken`
nor `asr-live`'s own `Token` carry a byte offset into the source utterance
text at all, so there is no byte-perfect ground truth to reconstruct against
regardless of which crate this landed in. Space-joining is a simplifying
assumption, documented on `token_span` itself, not a guarantee that it
matches a vendor's original spacing/punctuation byte-for-byte.

### Why this satisfies "every non-operator utterance emits a gate decision"

`evaluate_utterance`'s two-branch shape makes the contract structural:
speaker is checked exactly once, before anything else runs, and the only
two possible returns are `None` (never evaluated, `Operator` only) or
`Some(GateDecision)` (evaluated, always carrying a decision even with zero
events). There is no third path that evaluates a non-operator utterance and
returns nothing.
`an_operator_utterance_is_never_evaluated_even_with_a_matching_term` proves
the exclusion holds even when the lexicon would otherwise fire.
`an_unknown_speaker_utterance_is_also_evaluated` proves the exclusion is
exactly `Operator`, not "any speaker tag short of a confirmed participant" —
FR-5.1's own "not operator" phrasing, taken literally.
`a_participant_utterance_with_no_lexicon_match_still_emits_a_decision`
proves the "decision" is the `GateDecision` wrapper itself, not contingent
on at least one match.
`a_match_below_span_confidence_is_suppressed_not_dropped` and
`a_code_switched_utterance_emits_one_event_per_language_match` prove the
loop actually threads a real match through `gate_span_confidence` and the
per-language router respectively, rather than short-circuiting either.

### What's not done here

- FR-5.7's rolling pass-rate self-regulation and FR-5.8's storm absorption
  (`ratelimit/`) are not consumed by `evaluate_utterance` — it produces
  `TriggerEvent`s but does not feed them into a `PassRateCounter` or
  `ThresholdRegulator`. Both HANDOFFs already named this as "the caller's
  decision, made at the same integration point" as this loop; wiring it in
  is a natural next step but changes files outside this directory
  (`ratelimit/`), out of scope for a change scoped to `lexicon/`.
- FR-5.9's interim-hypothesis holding (`hold.rs`, above) is not threaded
  through `evaluate_utterance` — this loop only evaluates a *finalised*
  utterance's already-final token vector, matching FR-5.1's own wording. A
  caller wanting interim-hold behavior for a given stream still calls
  `CandidateHold` directly against that stream's interim/endpoint sequence.
- Sourcing a real `FinalisedUtterance` from `asr-live`'s
  `FinalUtteranceEvent` — this module proves the evaluation contract over
  its own local `SpeakerTag`/`FinalisedUtterance` types, not a live
  conversion from the ASR crate's event stream (no Cargo dependency exists
  yet, same gap `grouping.rs` already flags for `TaggedToken`).

Verified with `cargo test -p trigger-gate` (60/60 pass — 51 prior tests
untouched, 9 new `evaluation` tests), `cargo clippy -p trigger-gate
--all-targets -- -D warnings` (clean), `cargo fmt -p trigger-gate -- --check`
on `evaluation.rs` and `mod.rs` (clean; `ratelimit/regulation.rs` and
`ratelimit/storm.rs` still carry the same pre-existing, unrelated formatting
diffs the FR-5.9 update above already noted and left alone), and
`cargo build --workspace` (still succeeds).

## Update: interim-hypothesis holding (PRD FR-5.9)

Implements "System runs the lexicon scan against interim hypotheses,
holding the matched candidate until the endpoint commits or discards it"
(PRD FR-5.9). This is feature 145's own HANDOFF calling out "interim-
hypothesis holding (feature 153)" as explicitly out of scope — this change
is that feature.

`core/crates/trigger-gate/src/lib.rs` already had `pub mod lexicon;` from
feature 145; no scaffold changes needed.

### What's here

- `hold.rs` — `HeldCandidate`, `Resolution` (`Committed`/`Discarded`),
  `DiscardReason`, and `CandidateHold`. `CandidateHold::hold_interim` scans
  an interim hypothesis's tokens through an existing `LexiconRouter` (the
  same isolation-respecting `run` feature 145 built) and holds every
  resulting match under that stream's id — it does not act on the match or
  drop it. `CandidateHold::resolve_endpoint` is what a caller invokes once
  that stream's endpoint fires: it drains every candidate held for the
  stream and re-runs the router over the endpoint's own final token vector.
  A held candidate whose token index/language/term still matches in the
  final vector resolves to `Resolution::Committed`; one that doesn't (the
  vendor revised or dropped the matched word before the utterance closed)
  resolves to `Resolution::Discarded`.
- `mod.rs` — re-exports `CandidateHold`, `DiscardReason`, `HeldCandidate`,
  `Resolution` alongside the existing feature-145 exports.

### Why this satisfies "an interim match emits a held candidate the
endpoint commits or discards"

`hold_interim` never returns anything that has already been committed or
discarded — a `HeldCandidate` is deliberately the only outcome an interim
match can produce, mirroring how `asr-live::stream::frozen_match`'s
`CommittedCandidate` (PRD FR-2.4) is the only outcome a match against
*frozen* text can produce. The difference is the discard path: FR-2.4's
frozen case needs none, because frozen text is guaranteed immutable — an
interim hypothesis's text carries no such guarantee, so `resolve_endpoint`
is the only path that turns a `HeldCandidate` into either a `Committed` or
`Discarded` `Resolution`, and it can only be reached by the same stream's
endpoint supplying its own final tokens.
`endpoint_confirming_the_same_text_commits_the_held_candidate` and
`endpoint_revising_the_matched_text_away_discards_the_held_candidate` prove
both halves directly.
`resolving_drains_the_stream_so_a_later_endpoint_starts_clean` proves a
resolved candidate cannot be resolved twice, and
`resolving_one_streams_endpoint_does_not_touch_another_streams_held_candidates`
proves resolution is scoped to the endpointing stream, not global.

### What's not done here

- Reconciling a match whose token index shifts between interim and final
  vectors (e.g. a vendor correction that inserts/removes an earlier word,
  shifting every later index) is not attempted: `resolve_endpoint` compares
  token index, language, and term exactly, so a shifted-but-otherwise-
  identical match discards rather than commits. Every existing test
  constructs interim/final token vectors with stable indices for the
  matched word, the same simplifying assumption `asr-live::stream::
  reevaluate`'s `HANDOFF.md` documents for its own text-merge logic.
- Deduplicating repeat matches across successive growing interims of the
  same utterance (a vendor re-emitting a longer hypothesis that still
  contains an already-held term) is not attempted: `hold_interim` holds
  whatever the router returns on every call, so the same term appearing in
  two interims of one utterance produces two `HeldCandidate`s, which
  `resolve_endpoint` will independently commit or discard. Whoever wires
  this against a real vendor connection should decide whether the caller
  suppresses duplicate nudges downstream (the same open question feature
  145's frozen-match `HANDOFF.md` leaves for "a stream's later endpoint
  once a `CommittedCandidate` has already fired for it").
- Wiring this into `parse::gate::gate_span_confidence` or an actual
  vendor/endpoint event loop — this module only proves the hold/resolve
  contract over `TaggedToken` vectors, the same "not yet wired" scope
  feature 145's own HANDOFF left for the overall gate evaluation loop
  (feature 141).

Verified with `cargo test -p trigger-gate` (51/51 pass — 45 prior tests
untouched, 6 new `hold` tests), `cargo clippy -p trigger-gate --all-targets
-- -D warnings` (clean), and `cargo fmt -p trigger-gate -- --check` (clean
for every file this change touches; `ratelimit/regulation.rs` and
`ratelimit/storm.rs` already had pre-existing formatting diffs unrelated to
this change, left alone since they're outside this directory).

## Original: per-language isolation (feature 145)

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
