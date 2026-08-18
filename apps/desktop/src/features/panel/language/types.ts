/**
 * Language support tiers (PRD §8.2a), most to least capable. Mirrors
 * `core/crates/language/src/tags/tier.rs::LanguageTier` — the backend
 * computes tier per language; the panel only ever renders it.
 */
export type SupportTier = 'tier-1' | 'tier-2' | 'tier-3';

/** One language currently shown in the panel chrome (PRD FR-2.20). */
export interface DetectedLanguage {
  /** BCP-47 primary subtag, e.g. `"en"` or `"zh"`. */
  readonly language: string;
  readonly tier: SupportTier;
  /** Confidence of the most recent observation that updated this entry. */
  readonly confidence: number;
}

/**
 * A single language observation as it arrives from the live pipeline. The
 * tier travels with the observation rather than being derived here, since
 * tier assignment (including NFR-5.8 automatic fallback) is the backend's
 * responsibility.
 */
export interface LanguageObservation {
  readonly language: string;
  readonly tier: SupportTier;
  readonly confidence: number;
}
