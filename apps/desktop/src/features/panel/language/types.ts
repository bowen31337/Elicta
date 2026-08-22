/**
 * Language support tiers (PRD §8.2a), most to least capable. Mirrors
 * `core/crates/language/src/tags/tier.rs::LanguageTier` — the backend
 * computes tier per language; the panel only ever renders it.
 */
export type SupportTier = 'tier-1' | 'tier-2' | 'tier-3';

/**
 * One language currently shown in the panel chrome (PRD FR-2.20).
 *
 * `heard` is the distinction the strip rests on. A language can be on it for
 * two quite different reasons: the engagement expects it in the room (FR-2.14,
 * derived from the client background before anyone speaks), or it has actually
 * been observed in the audio. Showing an expected language as though it had
 * been detected would put a claim on screen that nothing measured — which is
 * how the strip came to say "No language detected" about a service that
 * already knew which two languages to listen for.
 */
export interface DetectedLanguage {
  /** BCP-47 primary subtag, e.g. `"en"` or `"zh"`. */
  readonly language: string;
  /** `null` until something is observed: tier is assigned per observation. */
  readonly tier: SupportTier | null;
  readonly heard: boolean;
  /** Confidence of the most recent observation, absent until one arrives. */
  readonly confidence?: number;
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
