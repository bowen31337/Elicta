import type { SupportTier } from './types';

/** Operator-facing short label for the tier badge in the panel chrome. */
export const TIER_LABEL: Record<SupportTier, string> = {
  'tier-1': 'Tier 1',
  'tier-2': 'Tier 2',
  'tier-3': 'Tier 3',
};

/**
 * Operator-facing summary of what each tier keeps and loses (PRD §8.2a tier
 * table), mirroring `LanguageTier::capability_summary` in
 * `core/crates/language/src/tags/tier.rs`. Used as the tier badge's tooltip
 * so the chrome stays glanceable while the detail is still one hover away.
 */
export const TIER_CAPABILITY_SUMMARY: Record<SupportTier, string> = {
  'tier-1': 'Full support: sub-second nudges, model-assisted nudges, coverage and artifacts',
  'tier-2': 'Model-assisted nudges only, arriving in tens of seconds — no sub-second nudges',
  'tier-3': 'Transcript and artifacts only — no live nudges',
};

const TIER_RANK: Record<SupportTier, number> = {
  'tier-1': 0,
  'tier-2': 1,
  'tier-3': 2,
};

/** Lower rank means more capable, so `Ord`-style comparisons read directly. */
export function tierRank(tier: SupportTier): number {
  return TIER_RANK[tier];
}
