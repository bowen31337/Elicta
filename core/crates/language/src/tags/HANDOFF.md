# tags module — handoff (detected_languages)

Implements PRD FR-2.20 ("Display detected language(s) live in the panel",
rationale at architecture §8.2 "silent misdetection failure"), FR-2.21
("User can override the detected language with a single tap", done when the
override persists for the rest of the meeting), FR-2.19 ("Retain the
original-language utterance alongside any translation, permanently and
inseparably" — see the dedicated section below), and FR-2.16 ("System learns
per-attendee language preference across an engagement, biasing that stream
on later meetings" — see the dedicated section below). Self-contained under
this directory, same as `numerals/` and `segment/`; deliberately does not
touch `core/crates/language/Cargo.toml` or `core/crates/language/src/lib.rs`.
Those now exist in this worktree (created by the FR-2.18 segmentation
feature, commit `b1516f0`) but `lib.rs` only wires `pub mod segment;` so far
— `tags` (and `numerals`) are still unwired, matching what the sibling
HANDOFF.md files already flag as pending. Verified locally by temporarily
adding `pub mod tags;` to `lib.rs`, running `cargo test`/`cargo clippy`, then
reverting `lib.rs` to its committed state (`git checkout -- src/lib.rs`) so
this change stays scoped to `tags/`.

## FR-2.16: learn per-attendee language preference across an engagement (this update)

New file, `attendee_preference.rs`. FR-2.16 operates on a timescale no
existing sibling covers: `ParticipantLanguageTags` (FR-2.15) deliberately
starts from nothing at the top of every meeting, since it exists to catch
code-switching *within* one session — a fresh instance per meeting is
correct for that job, not a gap to fix. FR-2.16 is the opposite: it is
exactly that per-meeting memory, carried across every meeting in an
engagement, so a returning attendee's later meeting starts already biased
toward what previous meetings established instead of re-learning it from
zero.

- `AttendeeId` — a plain `String` alias for the `attendees.id` row, kept
  local for the same reason `ParticipantId` is: this crate has no dependency
  on the service's storage layer yet. Deliberately distinct from
  `ParticipantId` (`participant.rs`) — that id names a per-meeting vendor
  stream and is not guaranteed stable across meetings, so a real caller must
  resolve `ParticipantId -> AttendeeId` itself (see "Wiring needed" below).
- `AttendeeLanguagePreferences::observe_meeting(attendee_id, language,
  confidence)` — records one confident meeting-level observation, gated by
  `min_confidence` (0.6 default, matching every other confidence gate in
  this directory) so one noisy meeting can never seed or shift a learned
  preference. Tracks a per-language meeting count per attendee rather than
  every raw observation, and recomputes `preferred_language` as whichever
  language has the most confident meetings behind it. Ties keep whichever
  language already had the lead — concretely, this means a single later
  meeting in a different language never overwrites an established
  preference; only a language observed strictly *more often* takes over.
  This is the "learns ... across an engagement" half of FR-2.16, and is what
  makes `preferred_language` the value that persists per attendee.
- `AttendeeLanguagePreferences::bias_confidence(attendee_id, language,
  confidence)` — the "biasing that stream on later meetings" half. Boosts
  `confidence` by `bias_boost` (0.15 default, an uncalibrated placeholder
  like `AccuracyBar`'s thresholds) when `language` agrees with the
  attendee's learned preference, so a borderline later-meeting detection
  that matches history clears a downstream confidence gate (e.g.
  `ParticipantLanguageTags`'s) that it would otherwise miss. A `language`
  that disagrees with the learned preference — or an attendee with no
  learned preference yet — is returned unchanged: never suppress a
  confident contradicting signal, since a guest or a genuine language
  switch in one meeting is a real event, not noise, matching every other
  silent-misdetection guard in this directory.
- `preferred_language` / `preference_for` — read-only accessors; the latter
  returns the full `AttendeeLanguagePreference` (attendee id, learned
  language, total confident meetings observed).
- BCP-47 primary-subtag matching throughout, same convention as every
  sibling in this directory.

Tests added: 17 (no preference before any observation; a single confident
observation becomes the preference; low-confidence observations dropped and
never shift an existing preference; repeat observations of the same
language accumulate `meetings_observed`; a single later meeting in a
different language does not override an established preference; a language
observed more often than the incumbent does take over; a tie keeps the
earlier-established language; independent tracking per attendee; BCP-47
subtag collapsing for both `observe_meeting` and `bias_confidence`; custom
confidence threshold; `bias_confidence` boosts a matching observation,
leaves a contradicting one and an unknown attendee unchanged, never exceeds
1.0, and respects a custom `bias_boost`).

Deliberately out of scope here, same boundary already drawn for
`RetainedUtterance` persistence below: the `attendees.preferred_language`
column already exists in the schema (`app_spec.txt` feature 10) — writing a
learned `AttendeeLanguagePreference` there, and resolving which `AttendeeId`
a given meeting's `ParticipantId` stream actually belongs to (a calendar
invite / enrolment concern, not a language-tagging one), both belong to
whichever crate owns the live pipeline loop and the engagement's storage
layer. This crate has no storage layer and shouldn't grow one.

## FR-2.19: retain the original-language utterance alongside any translation (this update)

New file, `retention.rs`, rather than extending an existing one — FR-2.19
answers a different question than every other file in this directory. The
others all decide *which language* is in play (detected, per-participant,
tiered, overridden); this one guards what happens to the *text* of an
utterance once a language decision has already been made and a translation
gets produced from it. Nothing else here models an utterance's text at all.

- `RetainedUtterance::new(original_language, original_text)` — the only way
  to construct one, and the only place `original_language`/`original_text`
  are ever written. No method anywhere on the type mutates or clears them
  afterward; there is no setter, and no way to build one without an
  original. This mirrors the architecture doc's framing of the sibling
  citation-integrity and inference-marking invariants (§4): the guarantee is
  structural (an invalid state is impossible to construct/reach), not a rule
  callers must remember to follow.
- `set_translation(language, text)` — purely additive: adds a new
  language's translation or updates that language's existing translation
  text (e.g. a corrected re-translation), matched on BCP-47 primary subtag
  same as every sibling in this directory. Never reads or writes
  `original_language`/`original_text`, and never touches a different
  language's translation. There is deliberately no method to remove a
  translation or to remove/replace the original — "permanently and
  inseparably" means both stay reachable together for the life of the value.
- `translation_for` / `translations()` / `has_translation` /
  `translation_count` — read-only accessors, first-translated order for the
  list (matches `DetectedLanguagePanel::languages()`'s ordering convention).
- `paired_with(language)` — returns `(original_text, &Translation)` together
  when a translation exists, `None` otherwise. This is the FR-8.7a
  rendering shape ("a citation across a language boundary renders both") —
  the accessor makes it structurally impossible to hand a caller a
  translation without also handing them the original it came from.

Tests added: 11 (original retained at construction; adding a translation
leaves the original untouched; multiple translations coexist alongside one
original; re-translating the same language updates its text without
touching the original or any other language's translation; missing
translation returns `None`; first-translated ordering, including that a
re-translation doesn't reorder; BCP-47 subtag collapsing for both the
original language and translation languages; `paired_with` returns both
texts together or `None`; an untranslated utterance still reports its
original).

Deliberately out of scope here (belongs to other, already-planned work):
persisting a `RetainedUtterance` to storage is the DB-migration task that
adds `original_utterance_id`/`translated_text` columns to the `citations`
table (PRD FR-2.19, FR-8.7a; `app_spec.txt` feature 20) — this crate has no
storage layer and shouldn't grow one. This type is the in-process shape that
migration's persistence needs to preserve; wiring live ASR output and
translation calls into `RetainedUtterance::new`/`set_translation` belongs to
whichever crate owns the live pipeline loop, same caveat as
`DetectedLanguagePanel::observe` below.

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

- `attendee_preference.rs` — `AttendeeLanguagePreferences` (FR-2.16, see
  above): learns each attendee's preferred language across an engagement
  from confident per-meeting observations, and biases a later meeting's
  observation confidence toward that learned preference.
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
- `retention.rs` — `RetainedUtterance` and `Translation` (FR-2.19, see
  above): pairs an utterance's original-language text with every
  translation produced from it, structurally preventing the original from
  ever being replaced or discarded once set.
- `mod.rs` — declares `pub mod attendee_preference;`,
  `pub mod detected_languages;`, and `pub mod retention;`, and re-exports
  `AttendeeId`, `AttendeeLanguagePreference`, `AttendeeLanguagePreferences`,
  `DetectedLanguage`, `DetectedLanguagePanel`, `RetainedUtterance`,
  `Translation`.

## Wiring needed

`core/crates/language/src/lib.rs` exists but currently only has
`pub mod segment;`. It needs:

```rust
pub mod numerals;
pub mod segment;
pub mod tags;
```

No other integration required here — `detected_languages` only depends on
`tags::tier` (already in this directory), and `retention` and
`attendee_preference` have no dependencies on any other file in this
directory at all.

## What's not done here

- Wiring live ASR/tag observations (single-stream token tags or
  `ParticipantLanguageTags` updates) into calls to `observe` — that belongs
  to whichever crate owns the live pipeline loop once `tags` is wired into
  `lib.rs` and can depend on this crate.
- Resolving a meeting's `ParticipantId` streams to the engagement's
  `AttendeeId`s, calling `AttendeeLanguagePreferences::observe_meeting` with
  each meeting's confident final tag, feeding `bias_confidence` back into a
  later meeting's detection, and persisting the resulting
  `AttendeeLanguagePreference` to the `attendees.preferred_language` column
  — all belong to whichever crate owns the live pipeline loop and the
  engagement's storage layer, same as the `observe()` wiring above.
- Wiring the actual UI tap gesture (`apps/desktop`) to call
  `override_language` — out of this crate's footprint; this module only
  exposes the state machine the tap should drive.
- The actual panel UI rendering (`apps/desktop`) — out of this crate's
  footprint; `languages()`/`active_language()` return plain data for that
  layer to render.
- Constructing `RetainedUtterance` from live ASR output and feeding
  translation results into `set_translation` — belongs to whichever crate
  owns the live pipeline loop, same as the `observe()` wiring above.
- Persisting `RetainedUtterance` to the `citations` table
  (`original_utterance_id`/`translated_text` columns) — a separate,
  already-planned DB-migration task (`app_spec.txt` feature 20); out of this
  crate's footprint entirely.

Verified locally (temporarily wiring `pub mod tags;` into `lib.rs`, then
reverting it — see top of this file): `cargo test` — 106/106 pass (17 new
for FR-2.16); `cargo clippy --all-targets -- -D warnings` — clean;
pre-existing rustfmt drift across sibling `tags` files (struct-literal
wrapping) predates this feature and was left untouched, matching
`numerals/HANDOFF.md`'s prior note.
