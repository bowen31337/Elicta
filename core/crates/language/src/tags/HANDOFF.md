# tags module — handoff (detected_languages)

Implements PRD FR-2.20 ("Display detected language(s) live in the panel",
rationale at architecture §8.2 "silent misdetection failure"), FR-2.21
("User can override the detected language with a single tap", done when the
override persists for the rest of the meeting), FR-2.19 ("Retain the
original-language utterance alongside any translation, permanently and
inseparably" — see the dedicated section below), FR-2.16 ("System learns
per-attendee language preference across an engagement, biasing that stream
on later meetings" — see the dedicated section below), FR-2.12 ("System
uses an end-to-end multilingual engine so no language decision gates the
audio path" — see the dedicated section below), and FR-2.11 ("System never
presents a pre-meeting language selection, because language detection is
automatic" — see the dedicated section below). Self-contained under
this directory, same as `numerals/` and `segment/`.

`core/crates/language/Cargo.toml` and `src/lib.rs` were created by the
FR-2.18 segmentation feature (commit `b1516f0`); at that point, and when the
FR-2.12/2.16/2.19/2.21 sections below were first written, `lib.rs` only
wired `pub mod segment;` and this directory verified itself by temporarily
adding `pub mod tags;`, testing, then reverting. That is no longer the case:
the workspace-scaffolding feature (commit `c602003`) rewired `lib.rs` to
`pub mod numerals; pub mod segment; pub mod tags;` for real, so `tags` has
been genuinely compiled into the crate since that commit — the "Wiring
needed" section below is kept only as a record of that history, not as a
pending action.

## FR-2.12: no language decision gates the audio path (this update)

New file, `end_to_end.rs`. Every existing tracker in this directory
(`ParticipantLanguageTags`, `DetectedLanguagePanel`, `TierDriftMonitor`,
`AccuracyFallbackWatcher`) takes a `language: &str, confidence: f32`
observation as an opaque input — none of them show where that value comes
from, and nothing in this directory demonstrated that it is derived from
already-transcribed text rather than decided before transcription. FR-2.12
("Handle intra-sentential code-switching without language-ID routing — an
end-to-end multilingual model, not a detect-then-route pipeline") is
architecture §3.5's explicit prohibition on the audio path: routing and
aggregation must happen strictly *after* transcription, over tags the model
emits as a by-product. `segment::group_by_language` already embodies this at
the token-routing layer, but that lives in a different module with a
different footprint (`segment/**`); nothing analogous existed at the
`tags/**` layer that feeds this directory's trackers.

- `EndToEndToken` — text plus its per-token BCP-47 language tag and
  confidence, mirroring `segment::TaggedToken`'s fields. Duplicated locally
  rather than imported, same reasoning as every other cross-file
  duplication in this directory (e.g. `primary_subtag`): `tags` and
  `segment` are independent modules, each wired into `lib.rs` on its own.
- `transcript_text(tokens: &[EndToEndToken]) -> String` — the structural
  proof itself. It reconstructs the utterance's text by joining `tokens` in
  order and never reads `language` or `lang_confidence` at all, so a token
  with an absent, unknown, or low-confidence language tag contributes its
  text exactly as readily as a confidently-tagged one. There is no function
  anywhere in this crate that requires a language to be known, chosen, or
  confident before text is available — language identification is strictly
  a downstream, optional annotation on text that already exists, never a
  gate on producing it.
- `DominantLanguageResolver::resolve(tokens: &[EndToEndToken]) ->
  Option<DominantLanguage>` — the derivation those opaque
  `language`/`confidence` observations actually need: aggregates confident
  per-token tags (gated by the same 0.6 `min_confidence` default as every
  sibling in this directory) into the single BCP-47 language with the
  highest total confidence, reporting its mean confidence across the tokens
  that counted toward it. A tie in total confidence keeps whichever
  language was seen first in `tokens`, matching
  `AttendeeLanguagePreferences`'s tie-breaking convention. Its input type is
  what makes the "no preceding language decision" guarantee load-bearing
  rather than aspirational: an `EndToEndToken` cannot exist until the ASR
  model has already produced `text`, so there is no call site in this crate
  that could hand this function a language before transcription has run.
- `DominantLanguage` — the resulting `{ language, confidence }` pair, shaped
  to pass directly into `ParticipantLanguageTags::observe`,
  `DetectedLanguagePanel::observe`, or `TierDriftMonitor::observe`.

Tests added: 12 (text reconstruction preserves order, including a
code-switched utterance's exact interleaving; text reconstruction ignores
language and confidence entirely, including empty/negative/absent values;
empty input produces empty text; resolving with no tokens or all tokens
below threshold returns `None`; a single language reports its mean
confidence; a code-switched utterance picks the language with more
confidence weight behind it; low-confidence tokens are dropped before
aggregating rather than merely down-weighted; a tie keeps the first-seen
language; BCP-47 subtag collapsing; custom confidence threshold).

Deliberately out of scope here, same boundary already drawn throughout this
directory: wiring live ASR output into `EndToEndToken` and calling
`DominantLanguageResolver::resolve` to actually drive
`ParticipantLanguageTags`/`DetectedLanguagePanel`/`TierDriftMonitor` belongs
to whichever crate owns the live pipeline loop, once `tags` is wired into
`lib.rs` and can depend on this crate. This crate has no ASR adapter and
shouldn't grow one — the audio path itself (architecture §3.2's
`TranscriptionBackend`) lives elsewhere entirely; this directory's job stops
at proving nothing here would require it to make a language decision first.

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

## FR-2.11: no pre-meeting language selection (this update)

New file, `pre_meeting.rs`. Every existing tracker in this directory
requires a `language: &str` argument to `observe`/`resolve` — that is
correct for all of them, because they all sit downstream of transcription
(the record/live paths), which is exactly where FR-2.12 says a language is
allowed to fall out of the model's output. Nothing in this directory
modeled the *other* side of that boundary: the pre-meeting flow, before
anything has been transcribed, where FR-2.11 says no language decision may
be asked for or made at all. Without a type for that flow, "no language
picker" was only true by omission — there was no pre-meeting concept here
for a language field to have been added to in the first place, so nothing
demonstrated the absence was deliberate.

- `PreMeetingSetup` — the operator-facing configuration collected before a
  meeting starts: a title and a participant roster, built via `new()` and
  the additive `with_participant()`. This is FR-2.11's structural proof, the
  same way `EndToEndToken`/`transcript_text` are FR-2.12's: there is no
  field on this type for a language, no constructor parameter that accepts
  one, and no method that sets one, so a caller cannot construct a
  pre-meeting setup that carries a language choice — the guarantee holds
  because the type has nowhere to put it, not because callers remember a
  rule.
- `MeetingSession` — the result of starting a meeting: the setup's title and
  roster carried through unchanged, plus a freshly constructed
  `DetectedLanguagePanel` (`tags::tier::LanguageTierTable::launch_default()`)
  with nothing detected and no active language yet.
- `start_meeting(setup: PreMeetingSetup) -> MeetingSession` — the transition
  from pre-meeting to in-meeting. Its signature is the rest of the proof:
  there is no parameter here through which a caller could hand it a
  language, so every meeting this crate can construct starts with its
  language panel empty, ready for automatic detection (FR-2.20) to populate
  from the first transcribed utterance onward. This function's job stops
  there — it does not itself call ASR or `DominantLanguageResolver`, same
  boundary as `EndToEndToken` construction below.

Tests added: 9 (a new setup starts with no participants; `with_participant`
appends to the roster in order; `PreMeetingSetup::default()` is an empty
title and roster; starting a meeting carries the title and roster through
unchanged; a started meeting's language panel has no detected languages, no
active language, and is not overridden; a meeting with no roster still
starts; a started session's panel still auto-detects normally once
`observe()` is called on it; two sessions started from the same setup have
independent panels).

Deliberately out of scope here, same boundary as `EndToEndToken` below:
wiring an actual pre-meeting UI screen (`apps/desktop`) that collects a
title and roster and calls `start_meeting` — out of this crate's footprint,
which only exposes the data shape and the transition function for that
screen to drive. Likewise, constraining detection to an engagement's
expected-language set (PRD FR-2.14) is a separate, already-planned feature;
`PreMeetingSetup` deliberately does not grow an expected-language field for
it, since FR-2.14 is explicit that constraint is *derived* from engagement
context, never asked of the operator — adding such a field here would look
identical to the language picker FR-2.11 exists to rule out.

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
- `end_to_end.rs` — `EndToEndToken`, `transcript_text`,
  `DominantLanguageResolver`, and `DominantLanguage` (FR-2.12, see above):
  proves transcript text is never gated on a language decision, and derives
  the aggregate `(language, confidence)` observation every other tracker in
  this directory consumes from already-transcribed per-token tags.
- `pre_meeting.rs` — `PreMeetingSetup`, `MeetingSession`, and
  `start_meeting` (FR-2.11, see above): proves the pre-meeting flow has no
  language field or parameter anywhere in it, and that starting a meeting
  hands off directly to an empty, auto-detection-driven language panel.
- `mod.rs` — declares `pub mod attendee_preference;`,
  `pub mod detected_languages;`, `pub mod end_to_end;`, `pub mod
  pre_meeting;`, and `pub mod retention;`, and re-exports `AttendeeId`,
  `AttendeeLanguagePreference`, `AttendeeLanguagePreferences`,
  `DetectedLanguage`, `DetectedLanguagePanel`, `DominantLanguage`,
  `DominantLanguageResolver`, `EndToEndToken`, `MeetingSession`,
  `PreMeetingSetup`, `RetainedUtterance`, `Translation`, `start_meeting`.

## Wiring needed

None. `core/crates/language/src/lib.rs` already wires `pub mod tags;` (see
the wiring-history note at the top of this file) — `detected_languages`
depends on `tags::tier` and `pre_meeting` depends on both `tags::tier` and
`tags::detected_languages` (all already in this directory), and
`retention`, `attendee_preference`, and `end_to_end` have no dependencies on
any other file in this directory at all.

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
- Constructing `EndToEndToken`s from live ASR output and calling
  `DominantLanguageResolver::resolve` to actually drive the other trackers
  in this directory, plus the `TranscriptionBackend`/ASR adapter itself
  (architecture §3.2) that must genuinely be end-to-end multilingual for
  FR-2.12's audio-path guarantee to hold in production — this crate has no
  ASR adapter and shouldn't grow one; it can only prove that nothing on its
  side would require a language decision before text exists.
- Wiring an actual pre-meeting UI screen (`apps/desktop`) that collects a
  title/roster and calls `start_meeting`, and feeding its resulting
  `MeetingSession` into the live pipeline loop that then drives
  `DetectedLanguagePanel::observe` — both belong to whichever crate/app
  layer owns that flow; out of this crate's footprint.

Verified locally: `cargo test` — 153/153 pass (9 new for FR-2.11);
`cargo clippy --all-targets -- -D warnings` — clean; pre-existing rustfmt
drift across sibling `tags` files (struct-literal wrapping, method-chain
wrapping) predates this feature and was left untouched on the new file too,
matching `numerals/HANDOFF.md`'s prior note.
