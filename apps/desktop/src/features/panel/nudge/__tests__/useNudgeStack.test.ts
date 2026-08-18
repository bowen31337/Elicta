import { describe, expect, it } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { useNudgeStack } from '../useNudgeStack';
import type { Nudge } from '../types';

function makeNudge(id: string): Nudge {
  return { id, stub: `stub-${id}`, question: `question ${id}?`, createdAt: 0 };
}

describe('useNudgeStack', () => {
  it('starts with no active nudge and empty history', () => {
    const { result } = renderHook(() => useNudgeStack());
    expect(result.current.active).toBeNull();
    expect(result.current.history).toEqual([]);
  });

  it('makes the first pushed nudge active with no history', () => {
    const { result } = renderHook(() => useNudgeStack());
    act(() => result.current.pushNudge(makeNudge('a')));
    expect(result.current.active?.id).toBe('a');
    expect(result.current.history).toEqual([]);
  });

  it('demotes the previously active nudge to history on the next push', () => {
    const { result } = renderHook(() => useNudgeStack());
    act(() => result.current.pushNudge(makeNudge('a')));
    act(() => result.current.pushNudge(makeNudge('b')));
    expect(result.current.active?.id).toBe('b');
    expect(result.current.history.map((n) => n.id)).toEqual(['a']);
  });

  it('keeps history ordered most-recent-first as more nudges arrive', () => {
    const { result } = renderHook(() => useNudgeStack());
    act(() => result.current.pushNudge(makeNudge('a')));
    act(() => result.current.pushNudge(makeNudge('b')));
    act(() => result.current.pushNudge(makeNudge('c')));
    expect(result.current.active?.id).toBe('c');
    expect(result.current.history.map((n) => n.id)).toEqual(['b', 'a']);
  });

  it('clear resets both active and history', () => {
    const { result } = renderHook(() => useNudgeStack());
    act(() => result.current.pushNudge(makeNudge('a')));
    act(() => result.current.pushNudge(makeNudge('b')));
    act(() => result.current.clear());
    expect(result.current.active).toBeNull();
    expect(result.current.history).toEqual([]);
  });
});
