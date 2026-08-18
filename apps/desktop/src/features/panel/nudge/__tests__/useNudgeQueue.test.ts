import { describe, expect, it } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { useNudgeQueue } from '../useNudgeQueue';

/**
 * Must be created once per test and passed by reference into the hook.
 * `renderHook`'s callback re-runs on every state update the hook makes
 * internally, so a `withClock(...)` call written inline in that callback
 * would be re-invoked on each re-render, silently resetting the clock.
 */
function withClock(times: number[]): () => number {
  let i = 0;
  return () => times[Math.min(i++, times.length - 1)];
}

describe('useNudgeQueue', () => {
  it('does not surface anything just from enqueueing', () => {
    const now = withClock([0]);
    const { result } = renderHook(() => useNudgeQueue<string>({ now }));

    act(() => {
      result.current.enqueue('a');
    });

    expect(result.current.displayed).toBeNull();
    expect(result.current.pendingCount()).toBe(1);
  });

  it('surfaces on render, not on generation', () => {
    const now = withClock([0]);
    const { result } = renderHook(() => useNudgeQueue<string>({ now }));

    act(() => {
      result.current.enqueue('a');
    });
    let surfaced: string | null = null;
    act(() => {
      surfaced = result.current.render();
    });

    expect(surfaced).toBe('a');
    expect(result.current.displayed).toBe('a');
    expect(result.current.pendingCount()).toBe(0);
  });

  it('retains a burst of candidates instead of dropping them, surfacing one per window', () => {
    const now = withClock([0, 1_000, 60_000]);
    const { result } = renderHook(() => useNudgeQueue<string>({ now }));

    act(() => {
      // All four candidates pass the trigger gate within the same instant (a burst).
      result.current.enqueue('a');
      result.current.enqueue('b');
      result.current.enqueue('c');
      result.current.enqueue('d');
    });

    let firstRender: string | null = null;
    act(() => {
      firstRender = result.current.render();
    });
    expect(firstRender).toBe('a');
    expect(result.current.pendingCount()).toBe(3);

    let gatedRender: string | null = null;
    act(() => {
      gatedRender = result.current.render();
    });
    expect(gatedRender).toBeNull();
    // b, c, d were never dropped — they are still queued for a later render.
    expect(result.current.pendingCount()).toBe(3);
    expect(result.current.displayed).toBe('a');

    let laterRender: string | null = null;
    act(() => {
      laterRender = result.current.render();
    });
    expect(laterRender).toBe('b');
    expect(result.current.displayed).toBe('b');
    expect(result.current.pendingCount()).toBe(2);
  });

  it('keeps displaying the last surfaced nudge across renders that do not surface a new one', () => {
    const now = withClock([0, 100]);
    const { result } = renderHook(() => useNudgeQueue<string>({ now }));

    act(() => {
      result.current.enqueue('a');
      result.current.render();
    });
    act(() => {
      result.current.render();
    });

    expect(result.current.displayed).toBe('a');
  });

  it('exposes the timestamp of the last surfaced nudge', () => {
    const now = withClock([42]);
    const { result } = renderHook(() => useNudgeQueue<string>({ now }));

    act(() => {
      result.current.enqueue('a');
      result.current.render();
    });

    expect(result.current.lastSurfacedAt()).toBe(42);
  });

  it('honors a custom window', () => {
    const now = withClock([0, 4_999, 5_000]);
    const { result } = renderHook(() => useNudgeQueue<string>({ now, windowMs: 5_000 }));

    act(() => {
      result.current.enqueue('a');
      result.current.enqueue('b');
    });

    const results: (string | null)[] = [];
    act(() => {
      results.push(result.current.render());
    });
    act(() => {
      results.push(result.current.render());
    });
    act(() => {
      results.push(result.current.render());
    });

    expect(results).toEqual(['a', null, 'b']);
  });
});
