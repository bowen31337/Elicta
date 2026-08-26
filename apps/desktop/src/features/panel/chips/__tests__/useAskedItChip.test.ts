import { describe, expect, it, vi } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { useAskedItChip } from '../useAskedItChip';

/**
 * The hook used to own a `CoverageSlot` and flip it to `filled`, which made
 * the coverage meter a record of taps rather than a measurement. What a tap
 * means for coverage is the service's to decide now; what is left here is
 * making the tap idempotent within one nudge.
 */
describe('useAskedItChip', () => {
  it('starts un-asked', () => {
    const { result } = renderHook(() => useAskedItChip());
    expect(result.current.asked).toBe(false);
  });

  it('confirms on tap, synchronously', () => {
    const { result } = renderHook(() => useAskedItChip());

    act(() => result.current.tap());

    expect(result.current.asked).toBe(true);
  });

  it('calls onAsked without needing to be awaited', () => {
    const onAsked = vi.fn();
    const { result } = renderHook(() => useAskedItChip({ onAsked }));

    act(() => result.current.tap());

    expect(onAsked).toHaveBeenCalledTimes(1);
  });

  it('is a no-op on a second tap once already asked', () => {
    const onAsked = vi.fn();
    const { result } = renderHook(() => useAskedItChip({ onAsked }));

    act(() => result.current.tap());
    act(() => result.current.tap());

    expect(onAsked).toHaveBeenCalledTimes(1);
    expect(result.current.asked).toBe(true);
  });
});
