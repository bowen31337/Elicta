import { describe, expect, it } from 'vitest';
import { pickHighestUrgencySlot } from '../pickHighestUrgencySlot';
import type { CoverageSummary } from '../../coverage/types';

describe('pickHighestUrgencySlot', () => {
  it('picks the first unfilled slot as the highest-urgency one', () => {
    const summary: CoverageSummary = {
      slots: [
        { id: 'scope', label: 'Scope boundary', filled: true },
        { id: 'budget', label: 'Budget', filled: false },
        { id: 'risks', label: 'Risks', filled: false },
      ],
      timeRemainingMs: 60_000,
    };

    expect(pickHighestUrgencySlot(summary)).toEqual({
      id: 'budget',
      label: 'Budget',
      filled: false,
    });
  });

  it('returns null when every section is already filled', () => {
    const summary: CoverageSummary = {
      slots: [{ id: 'scope', label: 'Scope boundary', filled: true }],
      timeRemainingMs: 30_000,
    };

    expect(pickHighestUrgencySlot(summary)).toBeNull();
  });

  it('returns null when there are no tracked sections', () => {
    expect(pickHighestUrgencySlot({ slots: [], timeRemainingMs: null })).toBeNull();
  });
});
