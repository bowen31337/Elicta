# parse module — handoff

Implements "System detects unnamed actors in English through a dependency
parse over passive constructions and agentless clauses" (PRD FR-5.3,
architecture §3.5's deterministic-tier table: "Unnamed actor — Dependency
parse; passive constructions and agentless clauses"). Done when an
agentless clause emits a `TriggerEvent` carrying its span.

This crate has no dependency-parsing library in the workspace (checked the
workspace root `Cargo.toml`: no crate anywhere under `core/crates/*` parses
English syntax trees), so there is no real dependency parse to call. The
new `unnamed_actor` module approximates the one surface pattern FR-5.3 asks
for — passive voice with no `by <agent>` phrase — as a local scan, the same
relationship `lexicon::terms::Lexicon::scan`'s plain substring scan has to
the Aho-Corasick engine FR-5.2 eventually wants: a stand-in over the same
output contract, replaceable later without changing what downstream code
sees.

## What's here

- `unnamed_actor.rs` (new) —
  - `find_agentless_clauses(tokens: &[TaggedToken]) -> Vec<AgentlessClauseMatch>`:
    scans for a finite "to be" form (`BE_FORMS`) immediately followed by a
    past participle (`IRREGULAR_PAST_PARTICIPLES` list, or a regular `-ed`
    suffix), then looks up to `AGENT_LOOKAHEAD` (3) tokens past the
    participle for a `by` token. A pair followed by `by` names its agent and
    is not returned; otherwise it's an `AgentlessClauseMatch { start, end }`
    (be-verb index, participle index, inclusive). Scanning resumes just past
    a matched pair either way, so matches never overlap.
  - `token_range_span(tokens, start, end) -> Range<usize>`: the byte range
    `tokens[start..=end]` would occupy in `tokens` reconstructed as one
    string joined by single spaces — a multi-token generalisation of
    `lexicon::evaluation::token_span`'s same reconstruction assumption (that
    function stays put in `lexicon`, out of this feature's footprint; this
    is a separate, local copy of the same idea for a token *range* rather
    than a single index). Private — not re-exported.
  - `gate_agentless_clauses(utterance_id, tokens, min_span_confidence) -> Vec<TriggerEvent>`:
    runs `find_agentless_clauses`, turns each match into a span (via
    `token_range_span`) and its word confidences (the matched tokens'
    `confidence` fields), and gates each through the existing
    `gate_span_confidence` (NFR-5.6) — reusing the same suppression path
    every other trigger kind in this crate goes through, so a misheard
    agentless clause is suppressed rather than silently dropped or
    silently trusted.
- `mod.rs` — added `pub mod unnamed_actor;` and re-exports
  (`AgentlessClauseMatch`, `find_agentless_clauses`,
  `gate_agentless_clauses`).

Known, documented gaps in the local scan (left for a real parse):
adverbs or negation between the be-verb and participle ("was not
reviewed", "was quickly reviewed") break the required token adjacency and
are not detected; a bare `-ed` adjective ("was interested") can be
mistaken for a passive participle. Both are recall/precision trade-offs
for running with zero NLP dependency, not a design considered final —
see the module's own doc comment.

## Why this satisfies "an agentless clause emits a trigger event with its span"

`gate_agentless_clauses("utt-1", &["the","report","was","reviewed"].., 0.6)`
returns one `TriggerEvent` with `kind: TriggerKind::Fired`,
`utterance_id: "utt-1"`, and `span: Some(11..23)` — the byte range of "was
reviewed" in the space-joined reconstruction (test
`gate_agentless_clauses_emits_a_fired_event_with_its_span`). A clause
naming its agent ("...was reviewed by the team") or in active voice
produces no event at all (`a_passive_clause_naming_its_agent_is_not_a_match`,
`active_voice_is_not_a_match`, `gate_agentless_clauses_emits_nothing_for_an_active_voice_utterance`).
A low-confidence agentless clause still emits an event, just
`Suppressed` rather than dropped (`gate_agentless_clauses_suppresses_a_low_confidence_span`) —
the same "every candidate becomes exactly one `TriggerEvent`" contract
`gate_span_confidence` already upholds for lexicon-sourced spans.

## Wiring needed

Not wired into `lexicon::evaluation::evaluate_utterance` (FR-5.1's gate
loop) — that function currently only calls `LexiconRouter::run` +
`gate_span_confidence` per lexicon match; it has no call to
`gate_agentless_clauses` yet, so unnamed-actor triggers do not yet reach a
`GateDecision` in the live evaluation path. Left for whoever integrates the
full deterministic tier (feature 141's loop, or a follow-up): each
utterance's English-tagged token group (`lexicon::group_by_language`'s "en"
group) would need to run through `gate_agentless_clauses` alongside the
lexicon scan, and the two event vectors merged.

`TriggerKind` still only distinguishes `Fired` vs `Suppressed(reason)`, not
*which* trigger rule matched (unquantified adjective vs. unnamed actor,
etc.) — the taxonomy gap `event.rs`'s doc comment already flagged before
this feature landed, still unresolved. A caller cannot yet tell an
agentless-clause `Fired` event apart from a lexicon-match `Fired` event
except by which function produced it.

Per-language dispatch is not addressed here either: `find_agentless_clauses`
runs over whatever tokens it's handed with no language check of its own.
Architecture §3.5 is explicit that this rule "does not transfer to pro-drop
languages" (Chinese, Japanese, Korean) — calling it on non-English tokens
was never validated and is expected to misfire. Restricting it to the "en"
language group (via `lexicon::group_by_language`) is part of the wiring
work above, not done in this feature.

Verified standalone: `cargo test -p trigger-gate` — 72/72 pass (59 prior
tests untouched, 13 new `unnamed_actor` tests); `cargo clippy -p
trigger-gate --all-targets -- -D warnings` — clean; `rustfmt --check` on
both changed files (`unnamed_actor.rs`, `mod.rs`) — clean. (Note:
`cargo fmt -p trigger-gate -- --check` alone reports pre-existing diffs in
`ratelimit/regulation.rs` and `ratelimit/storm.rs` — outside this feature's
footprint and untouched by it.)
