import { describe, expect, it } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { useNudgeRateGate } from '../useNudgeRateGate';

function withClock(times: number[]): () => number {
  let i = 0;
  return () => times[Math.min(i++, times.length - 1)];
}

describe('useNudgeRateGate', () => {
  it('admits the first candidate', () => {
    const { result } = renderHook(() => useNudgeRateGate<string>({ now: withClock([0]) }));

    let admitted: string | null = null;
    act(() => {
      admitted = result.current.admit('a');
    });

    expect(admitted).toBe('a');
  });

  it('surfaces at most one candidate per 60s window regardless of how many are offered', () => {
    const { result } = renderHook(() =>
      useNudgeRateGate<string>({ now: withClock([0, 1_000, 2_000, 59_999]) }),
    );

    const results: (string | null)[] = [];
    act(() => {
      results.push(result.current.admit('a'));
      results.push(result.current.admit('b'));
      results.push(result.current.admit('c'));
      results.push(result.current.admit('d'));
    });

    expect(results).toEqual(['a', null, null, null]);
  });

  it('admits again once the window has elapsed', () => {
    const { result } = renderHook(() =>
      useNudgeRateGate<string>({ now: withClock([0, 60_000]) }),
    );

    const results: (string | null)[] = [];
    act(() => {
      results.push(result.current.admit('a'));
      results.push(result.current.admit('b'));
    });

    expect(results).toEqual(['a', 'b']);
  });

  it('exposes the timestamp of the last surfaced nudge', () => {
    const { result } = renderHook(() => useNudgeRateGate<string>({ now: withClock([42]) }));

    act(() => {
      result.current.admit('a');
    });

    expect(result.current.lastSurfacedAt()).toBe(42);
  });

  it('does not advance the window on a suppressed candidate', () => {
    const { result } = renderHook(() =>
      useNudgeRateGate<string>({ now: withClock([0, 1_000]) }),
    );

    act(() => {
      result.current.admit('a');
      result.current.admit('b');
    });

    expect(result.current.lastSurfacedAt()).toBe(0);
  });

  it('honors a custom window', () => {
    const { result } = renderHook(() =>
      useNudgeRateGate<string>({ now: withClock([0, 4_999, 5_000]), windowMs: 5_000 }),
    );

    const results: (string | null)[] = [];
    act(() => {
      results.push(result.current.admit('a'));
      results.push(result.current.admit('b'));
      results.push(result.current.admit('c'));
    });

    expect(results).toEqual(['a', null, 'c']);
  });
});
