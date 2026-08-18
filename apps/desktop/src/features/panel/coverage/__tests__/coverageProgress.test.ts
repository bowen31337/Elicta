import { describe, expect, it } from 'vitest';
import { countFilledSlots, formatTimeRemaining } from '../coverageProgress';
import type { CoverageSummary } from '../types';

describe('countFilledSlots', () => {
  it('counts filled sections against the template total', () => {
    const summary: CoverageSummary = {
      slots: [
        { id: 'a', label: 'A', filled: true },
        { id: 'b', label: 'B', filled: false },
        { id: 'c', label: 'C', filled: true },
      ],
      timeRemainingMs: null,
    };

    expect(countFilledSlots(summary)).toEqual({ filled: 2, total: 3 });
  });

  it('returns zero over zero when there are no tracked sections yet', () => {
    expect(countFilledSlots({ slots: [], timeRemainingMs: null })).toEqual({ filled: 0, total: 0 });
  });
});

describe('formatTimeRemaining', () => {
  it('formats whole minutes', () => {
    expect(formatTimeRemaining(120_000)).toBe('2:00');
  });

  it('pads seconds under ten', () => {
    expect(formatTimeRemaining(65_000)).toBe('1:05');
  });

  it('rounds to the nearest second', () => {
    expect(formatTimeRemaining(59_600)).toBe('1:00');
  });

  it('clamps negative durations to zero', () => {
    expect(formatTimeRemaining(-5_000)).toBe('0:00');
  });
});
