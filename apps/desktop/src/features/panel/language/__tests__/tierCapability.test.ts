import { describe, expect, it } from 'vitest';
import { TIER_CAPABILITY_SUMMARY, TIER_LABEL, tierRank } from '../tierCapability';

describe('tierRank', () => {
  it('ranks tier-1 as more capable than tier-2 and tier-3', () => {
    expect(tierRank('tier-1')).toBeLessThan(tierRank('tier-2'));
    expect(tierRank('tier-2')).toBeLessThan(tierRank('tier-3'));
  });
});

describe('tier metadata', () => {
  it('provides a label and capability summary for every tier', () => {
    (['tier-1', 'tier-2', 'tier-3'] as const).forEach((tier) => {
      expect(TIER_LABEL[tier]).toBeTruthy();
      expect(TIER_CAPABILITY_SUMMARY[tier]).toBeTruthy();
    });
  });
});
