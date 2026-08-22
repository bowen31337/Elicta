import type { DetectedLanguage, LanguageObservation, SupportTier } from './types';

/** Mirrors `DetectedLanguagePanel`'s default confidence gate (FR-2.22). */
export const DEFAULT_MIN_CONFIDENCE = 0.6;

/**
 * Panel-chrome state: every language detected so far this meeting (PRD
 * FR-2.20), plus the tier of whichever language was most recently observed
 * confidently — the "active" support tier the chrome badge shows right now.
 */
export interface LanguagePanelState {
  /** First-detected order; a language is never removed once it clears the bar. */
  readonly languages: readonly DetectedLanguage[];
  readonly activeTier: SupportTier | null;
}

export function createLanguagePanelState(): LanguagePanelState {
  return { languages: [], activeTier: null };
}

/**
 * BCP-47 tags are matched on their primary subtag: "en-US" and "en" are the
 * same language for panel purposes. Matches the convention in
 * `core/crates/language/src/tags/detected_languages.rs::primary_subtag`.
 */
function primarySubtag(language: string): string {
  return language.split(/[-_]/)[0]?.toLowerCase() || language;
}

/**
 * Applies one observation to the panel state. Below `minConfidence` the
 * observation is dropped and the state is returned unchanged — a single
 * noisy tag must never flash a phantom language onto the panel nor bump the
 * active tier (PRD FR-2.22's tag-confidence philosophy, applied here as it
 * is in `DetectedLanguagePanel::observe`). At or above threshold, the
 * language's entry is added (if new, at the end, preserving first-detected
 * order) or refreshed in place (if already detected) — an already-detected
 * language is never removed by observing a *different* language — and the
 * active tier always advances to this observation's tier.
 */
export function observeLanguage(
  state: LanguagePanelState,
  observation: LanguageObservation,
  minConfidence: number = DEFAULT_MIN_CONFIDENCE,
): LanguagePanelState {
  if (observation.confidence < minConfidence) {
    return state;
  }

  const subtag = primarySubtag(observation.language);
  const entry: DetectedLanguage = {
    language: subtag,
    tier: observation.tier,
    heard: true,
    confidence: observation.confidence,
  };

  const existingIndex = state.languages.findIndex((l) => l.language === subtag);
  const languages =
    existingIndex === -1
      ? [...state.languages, entry]
      : state.languages.map((l, index) => (index === existingIndex ? entry : l));

  return { languages, activeTier: observation.tier };
}


/**
 * Puts a language on the strip because the engagement expects it in the room
 * (PRD FR-2.14), not because anything has heard it.
 *
 * Deliberately weaker than `observeLanguage`: no tier, no confidence, and no
 * effect on the active tier badge. It says "this is what I am listening for",
 * which is what the service knows before a meeting starts — and never "this is
 * what I heard", which it does not.
 *
 * A language already heard is left alone: expecting something after observing
 * it must not walk the strip backwards.
 */
export function expectLanguage(
  state: LanguagePanelState,
  language: string,
): LanguagePanelState {
  const subtag = primarySubtag(language);
  if (state.languages.some((entry) => entry.language === subtag)) {
    return state;
  }

  return {
    ...state,
    languages: [...state.languages, { language: subtag, tier: null, heard: false }],
  };
}
