# tags module — handoff (detected_languages)

Implements PRD FR-2.20 ("Display detected language(s) live in the panel",
rationale at architecture §8.2 "silent misdetection failure") and FR-2.21
("User can override the detected language with a single tap", done when the
override persists for the rest of the meeting). Self-contained under this
directory, same as `numerals/` and `segment/`; deliberately does not touch
`core/crates/language/Cargo.toml` or `core/crates/language/src/lib.rs`. Those
now exist in this worktree (created by the FR-2.18 segmentation feature,
commit `b1516f0`) but `lib.rs` only wires `pub mod segment;` so far — `tags`
(and `numerals`) are still unwired, matching what the sibling HANDOFF.md
files already flag as pending. Verified locally by temporarily adding
`pub mod tags;` to `lib.rs`, running `cargo test`/`cargo clippy`, then
reverting `lib.rs` to its committed state (`git checkout -- src/lib.rs`) so
this change stays scoped to `tags/`.

## FR-2.21: override the detected language (this update)

Added directly to `DetectedLanguagePanel` (`detected_languages.rs`) rather
than as a new file, because FR-2.21 is explicitly about overriding *the
same* "detected language" concept FR-2.20 already displays — a separate
override tracker would just be a second source of truth for what the panel
should show as active.

- New `active` field: the BCP-47 primary subtag currently active for the
  meeting. `observe()` keeps setting it to the latest confident auto-detected
  language, exactly as before, *unless* `overridden` is set.
- New `overridden` flag, set once `override_language()` is called. From that
  point on, `observe()` still updates the visible language list and each
  entry's confidence/tier as always (a misdetected language must stay
  visible, not vanish — same rationale as FR-2.20), but never moves `active`
  away from the override again. This is the actual "persists for the rest of
  the meeting" requirement: nothing resets `overridden` back to `false`
  within a `DetectedLanguagePanel` instance, so the caller owning one
  instance per meeting gets that persistence for free.
- `override_language()` adds the language to the panel first if it wasn't
  already detected (at confidence 1.0, since the user is asserting it
  directly) so `active_language()` and `languages()` never disagree about
  what's in play. Calling it again with a different language moves the
  override (last tap wins) — nothing in FR-2.21 restricts the user to one
  override for the whole meeting, only that whichever one is in force
  survives auto-detection.
- New `active_language()` / `is_overridden()` accessors for the panel UI.

Tests added: 9 new (before either signal, auto-detection driving `active`
absent an override, immediate effect of a tap, persistence against further
`observe()` calls, adding a not-yet-detected language, coexistence with
other detected languages, re-tapping a different language, BCP-47 subtag
collapsing, and auto-detection continuing to update the list post-override).

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
  - `active_language()` / `override_language()` / `is_overridden()` (FR-2.21,
    see above) — the single "what language is active right now" signal for
    the panel, defaulting to auto-detection until the user taps an override.
- `mod.rs` — declares `pub mod detected_languages;` and re-exports
  `DetectedLanguage`, `DetectedLanguagePanel`.

## Wiring needed

`core/crates/language/src/lib.rs` exists but currently only has
`pub mod segment;`. It needs:

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
  to whichever crate owns the live pipeline loop once `tags` is wired into
  `lib.rs` and can depend on this crate.
- Wiring the actual UI tap gesture (`apps/desktop`) to call
  `override_language` — out of this crate's footprint; this module only
  exposes the state machine the tap should drive.
- The actual panel UI rendering (`apps/desktop`) — out of this crate's
  footprint; `languages()`/`active_language()` return plain data for that
  layer to render.

Verified locally (temporarily wiring `pub mod tags;` into `lib.rs`, then
reverting it — see top of this file): `cargo test` — 104/104 pass (9 new for
FR-2.21); `cargo clippy --all-targets -- -D warnings` — clean; pre-existing
rustfmt drift across sibling `tags` files (struct-literal wrapping) predates
this feature and was left untouched, matching `numerals/HANDOFF.md`'s prior
note.
