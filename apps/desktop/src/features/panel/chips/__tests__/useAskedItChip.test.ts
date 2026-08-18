import { describe, expect, it, vi } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { useAskedItChip } from '../useAskedItChip';
import type { CoverageSlot } from '../../coverage/types';

const unfilledSlot: CoverageSlot = { id: 'budget', label: 'Budget', filled: false };

describe('useAskedItChip', () => {
  it('starts reflecting the slot passed in', () => {
    const { result } = renderHook(() => useAskedItChip(unfilledSlot));
    expect(result.current.asked).toBe(false);
    expect(result.current.slot).toEqual(unfilledSlot);
  });

  it('marks the slot filled locally on tap, synchronously', () => {
    const { result } = renderHook(() => useAskedItChip(unfilledSlot));

    act(() => result.current.tap());

    expect(result.current.asked).toBe(true);
    expect(result.current.slot).toEqual({ ...unfilledSlot, filled: true });
  });

  it('calls onAsked with the mutated slot, without needing to be awaited', () => {
    const onAsked = vi.fn();
    const { result } = renderHook(() => useAskedItChip(unfilledSlot, { onAsked }));

    act(() => result.current.tap());

    expect(onAsked).toHaveBeenCalledWith({ ...unfilledSlot, filled: true });
  });

  it('is a no-op on a second tap once already asked', () => {
    const onAsked = vi.fn();
    const { result } = renderHook(() => useAskedItChip(unfilledSlot, { onAsked }));

    act(() => result.current.tap());
    act(() => result.current.tap());

    expect(onAsked).toHaveBeenCalledTimes(1);
    expect(result.current.asked).toBe(true);
  });

  it('starts already-asked when given a slot that is already filled', () => {
    const filledSlot: CoverageSlot = { id: 'timeline', label: 'Timeline', filled: true };
    const onAsked = vi.fn();
    const { result } = renderHook(() => useAskedItChip(filledSlot, { onAsked }));

    expect(result.current.asked).toBe(true);

    act(() => result.current.tap());
    expect(onAsked).not.toHaveBeenCalled();
  });
});
