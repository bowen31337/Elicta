import { describe, expect, it, vi } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { useWhatAmIMissingChip } from '../useWhatAmIMissingChip';
import type { CoverageSummary } from '../../coverage/types';

const summary: CoverageSummary = {
  slots: [
    { id: 'scope', label: 'Scope boundary', filled: true },
    { id: 'budget', label: 'Budget', filled: false },
    { id: 'risks', label: 'Risks', filled: false },
  ],
  timeRemainingMs: 60_000,
};

describe('useWhatAmIMissingChip', () => {
  it('has no result before the first tap', () => {
    const { result } = renderHook(() => useWhatAmIMissingChip(summary));
    expect(result.current.result).toBeNull();
  });

  it('surfaces the highest-urgency unfilled section on tap', () => {
    const { result } = renderHook(() => useWhatAmIMissingChip(summary));

    act(() => result.current.tap());

    expect(result.current.result).toEqual({
      type: 'slot',
      slot: { id: 'budget', label: 'Budget', filled: false },
    });
  });

  it('calls onSurfaced with the surfaced slot, without needing to be awaited', () => {
    const onSurfaced = vi.fn();
    const { result } = renderHook(() => useWhatAmIMissingChip(summary, { onSurfaced }));

    act(() => result.current.tap());

    expect(onSurfaced).toHaveBeenCalledWith({ id: 'budget', label: 'Budget', filled: false });
  });

  it('reports clear when every section is already filled, without calling onSurfaced', () => {
    const onSurfaced = vi.fn();
    const allFilled: CoverageSummary = {
      slots: [{ id: 'scope', label: 'Scope boundary', filled: true }],
      timeRemainingMs: 30_000,
    };
    const { result } = renderHook(() => useWhatAmIMissingChip(allFilled, { onSurfaced }));

    act(() => result.current.tap());

    expect(result.current.result).toEqual({ type: 'clear' });
    expect(onSurfaced).not.toHaveBeenCalled();
  });
});
