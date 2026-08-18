import { describe, expect, it, vi } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import { useGoDeeperChip } from '../useGoDeeperChip';
import type { RequestFollowOnFetch } from '../requestFollowOnCandidate';
import type { Thread } from '../types';

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  } as Response;
}

const thread: Thread = {
  id: 'budget',
  question: 'What is your budget for this project?',
  operatorAskedAt: null,
};

describe('useGoDeeperChip', () => {
  it('starts idle with no candidate or error', () => {
    const { result } = renderHook(() => useGoDeeperChip(thread));

    expect(result.current.status).toBe('idle');
    expect(result.current.candidate).toBeNull();
    expect(result.current.error).toBeNull();
  });

  it('transitions through pending to loaded on a successful request', async () => {
    const fetchImpl = vi
      .fn<RequestFollowOnFetch>()
      .mockResolvedValue(jsonResponse(200, { question: 'What happens if the budget slips?' }));
    const { result } = renderHook(() => useGoDeeperChip(thread, { fetch: fetchImpl }));

    act(() => {
      void result.current.tap();
    });
    expect(result.current.status).toBe('pending');

    await waitFor(() => expect(result.current.status).toBe('loaded'));
    expect(result.current.candidate).toEqual({
      threadId: 'budget',
      question: 'What happens if the budget slips?',
    });
    expect(result.current.error).toBeNull();
  });

  it('transitions to error when the follow-on request fails', async () => {
    const fetchImpl = vi.fn<RequestFollowOnFetch>().mockResolvedValue(jsonResponse(500, { detail: 'boom' }));
    const { result } = renderHook(() => useGoDeeperChip(thread, { fetch: fetchImpl }));

    await act(async () => {
      await result.current.tap();
    });

    expect(result.current.status).toBe('error');
    expect(result.current.error).toBeInstanceOf(Error);
    expect(result.current.candidate).toBeNull();
  });

  it('calls onFollowOn with the loaded candidate, without needing to be awaited', async () => {
    const onFollowOn = vi.fn();
    const fetchImpl = vi
      .fn<RequestFollowOnFetch>()
      .mockResolvedValue(jsonResponse(200, { question: 'What happens if the budget slips?' }));
    const { result } = renderHook(() => useGoDeeperChip(thread, { fetch: fetchImpl, onFollowOn }));

    await act(async () => {
      await result.current.tap();
    });

    expect(onFollowOn).toHaveBeenCalledWith({ threadId: 'budget', question: 'What happens if the budget slips?' });
  });

  it('requests against the thread passed in', async () => {
    const fetchImpl = vi.fn<RequestFollowOnFetch>().mockResolvedValue(jsonResponse(200, { question: 'q2' }));
    const { result } = renderHook(() => useGoDeeperChip(thread, { fetch: fetchImpl }));

    await act(async () => {
      await result.current.tap();
    });

    expect(fetchImpl).toHaveBeenCalledWith('/api/threads/budget/go-deeper', expect.anything());
  });
});
