import { describe, expect, it, vi } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { useOperatorAskedThread } from '../useOperatorAskedThread';
import type { Thread } from '../types';

const openThread: Thread = {
  id: 'budget',
  question: 'What is your budget for this project?',
  operatorAskedAt: null,
};

describe('useOperatorAskedThread', () => {
  it('starts not live, reflecting the thread passed in', () => {
    const { result } = renderHook(() => useOperatorAskedThread(openThread));
    expect(result.current.live).toBe(false);
    expect(result.current.thread).toEqual(openThread);
  });

  it('marks the thread live when a noticed utterance asks its question', () => {
    const { result } = renderHook(() => useOperatorAskedThread(openThread));

    act(() => {
      result.current.notice({
        text: "What's the budget for this project?",
        finalizedAt: 1_000,
      });
    });

    expect(result.current.live).toBe(true);
    expect(result.current.thread.operatorAskedAt).toBe(1_000);
  });

  it('returns whether the utterance marked the thread live', () => {
    const { result } = renderHook(() => useOperatorAskedThread(openThread));

    let matched: boolean | undefined;
    act(() => {
      matched = result.current.notice({ text: 'Nice weather today.', finalizedAt: 1_000 });
    });
    expect(matched).toBe(false);

    act(() => {
      matched = result.current.notice({
        text: 'What is your budget for this project?',
        finalizedAt: 2_000,
      });
    });
    expect(matched).toBe(true);
  });

  it('calls onOperatorAsked with the mutated thread, without needing to be awaited', () => {
    const onOperatorAsked = vi.fn();
    const { result } = renderHook(() => useOperatorAskedThread(openThread, { onOperatorAsked }));

    act(() => {
      result.current.notice({ text: 'What is your budget for this project?', finalizedAt: 500 });
    });

    expect(onOperatorAsked).toHaveBeenCalledWith({ ...openThread, operatorAskedAt: 500 });
  });

  it('ignores utterances that do not ask the question', () => {
    const onOperatorAsked = vi.fn();
    const { result } = renderHook(() => useOperatorAskedThread(openThread, { onOperatorAsked }));

    act(() => {
      result.current.notice({ text: 'Let me check my notes.', finalizedAt: 500 });
    });

    expect(result.current.live).toBe(false);
    expect(result.current.thread).toEqual(openThread);
    expect(onOperatorAsked).not.toHaveBeenCalled();
  });

  it('keeps the marker once set, ignoring further utterances', () => {
    const onOperatorAsked = vi.fn();
    const { result } = renderHook(() => useOperatorAskedThread(openThread, { onOperatorAsked }));

    act(() => {
      result.current.notice({ text: 'What is your budget for this project?', finalizedAt: 500 });
    });
    act(() => {
      result.current.notice({ text: 'What is your budget for this project?', finalizedAt: 900 });
    });

    expect(onOperatorAsked).toHaveBeenCalledTimes(1);
    expect(result.current.thread.operatorAskedAt).toBe(500);
  });

  it('starts already-live when given a thread that already has a marker', () => {
    const alreadyAsked: Thread = { ...openThread, operatorAskedAt: 42 };
    const onOperatorAsked = vi.fn();
    const { result } = renderHook(() =>
      useOperatorAskedThread(alreadyAsked, { onOperatorAsked }),
    );

    expect(result.current.live).toBe(true);

    act(() => {
      result.current.notice({ text: 'What is your budget for this project?', finalizedAt: 999 });
    });
    expect(onOperatorAsked).not.toHaveBeenCalled();
    expect(result.current.thread.operatorAskedAt).toBe(42);
  });
});
