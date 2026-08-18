# tags module — handoff (detected_languages)

Implements PRD FR-2.20 ("Display detected language(s) live in the panel",
rationale at architecture §8.2 "silent misdetection failure"). Self-contained
under this directory, same as `numerals/` and `segment/`; deliberately does
not touch `core/crates/language/Cargo.toml` or `core/crates/language/src/lib.rs`,
which still do not exist in this worktree (confirmed via `find`, matching
what the sibling HANDOFF.md files already flag as pending).

## What's here

- `detected_languages.rs` — `DetectedLanguagePanel`, the live, panel-facing
  registry of every language detected so far in the meeting:
  - `observe(language, confidence)` adds or refreshes a language's entry
    (BCP-47 primary subtag, current tier, latest confidence) once confidence
    clears the same 0.6 default gate used by `ParticipantLanguageTags` and
    `TierDriftMonitor` (FR-2.22's tag-confidence philosophy applied here too:
    one noisy observation must not flash a phantom language onto the panel).
  - `languages()` returns every detected language in first-detected order,
    for the panel to render live.
  - Once a language clears the bar it is never removed by observing a
    *different* language — this is the module's actual job. Existing
    siblings each answer a narrower question: `TierDriftMonitor` tracks one
    dominant language to decide whether the *meeting* tier dropped, and
    `ParticipantLanguageTags` tracks one tag per participant stream to
    decide per-stream routing. Neither exposes "every language detected
    this meeting" as a set, which is what FR-2.20 needs the panel to show —
    a code-switched meeting with English and Mandarin both in play must show
    both continuously, not just whichever dominates or whoever spoke last.
- `mod.rs` — declares `pub mod detected_languages;` and re-exports
  `DetectedLanguage`, `DetectedLanguagePanel`.

## Wiring needed (same one line the sibling HANDOFF.md files already ask for)

Whoever creates `core/crates/language/src/lib.rs` needs:

```rust
pub mod numerals;
pub mod segment;
pub mod tags;
```

No other integration required here — `detected_languages` only depends on
`tags::tier` (already in this directory).

## What's not done here

- Wiring live ASR/tag observations (single-stream token tags or
  `ParticipantLanguageTags` updates) into calls to `observe` — that belongs
  to whichever crate owns the live pipeline loop once `lib.rs` exists and
  can depend on this crate.
- The actual panel UI rendering (`apps/desktop`) — out of this crate's
  footprint; `languages()` returns plain data for that layer to render.

Verified standalone (copied into a scratch crate mirroring this module tree,
same approach as `numerals`/`segment`, since the crate-level
`Cargo.toml`/`lib.rs` don't exist here yet): `cargo test` — 37/37 pass (13
new); `cargo clippy --all-targets -- -D warnings` — clean; pre-existing
rustfmt drift across sibling `tags` files (struct-literal wrapping) predates
this feature and was left untouched, matching `numerals/HANDOFF.md`'s prior
note.
