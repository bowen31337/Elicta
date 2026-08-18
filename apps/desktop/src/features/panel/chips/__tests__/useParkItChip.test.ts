import { describe, expect, it, vi } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import { useParkItChip } from '../useParkItChip';
import type { ParkThreadFetch } from '../parkThread';
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

describe('useParkItChip', () => {
  it('starts idle with no parked confirmation or error', () => {
    const { result } = renderHook(() => useParkItChip(thread));

    expect(result.current.status).toBe('idle');
    expect(result.current.parked).toBeNull();
    expect(result.current.error).toBeNull();
  });

  it('transitions through pending to parked on a successful request', async () => {
    const fetchImpl = vi.fn<ParkThreadFetch>().mockResolvedValue(jsonResponse(200, { open_question_id: 'oq-1' }));
    const { result } = renderHook(() => useParkItChip(thread, { fetch: fetchImpl }));

    act(() => {
      void result.current.tap();
    });
    expect(result.current.status).toBe('pending');

    await waitFor(() => expect(result.current.status).toBe('parked'));
    expect(result.current.parked).toEqual({ threadId: 'budget', openQuestionId: 'oq-1' });
    expect(result.current.error).toBeNull();
  });

  it('transitions to error when the park request fails', async () => {
    const fetchImpl = vi.fn<ParkThreadFetch>().mockResolvedValue(jsonResponse(500, { detail: 'boom' }));
    const { result } = renderHook(() => useParkItChip(thread, { fetch: fetchImpl }));

    await act(async () => {
      await result.current.tap();
    });

    expect(result.current.status).toBe('error');
    expect(result.current.error).toBeInstanceOf(Error);
    expect(result.current.parked).toBeNull();
  });

  it('calls onParked with the confirmation, without needing to be awaited', async () => {
    const onParked = vi.fn();
    const fetchImpl = vi.fn<ParkThreadFetch>().mockResolvedValue(jsonResponse(200, { open_question_id: 'oq-1' }));
    const { result } = renderHook(() => useParkItChip(thread, { fetch: fetchImpl, onParked }));

    await act(async () => {
      await result.current.tap();
    });

    expect(onParked).toHaveBeenCalledWith({ threadId: 'budget', openQuestionId: 'oq-1' });
  });

  it('requests against the thread passed in', async () => {
    const fetchImpl = vi.fn<ParkThreadFetch>().mockResolvedValue(jsonResponse(200, { open_question_id: 'oq-1' }));
    const { result } = renderHook(() => useParkItChip(thread, { fetch: fetchImpl }));

    await act(async () => {
      await result.current.tap();
    });

    expect(fetchImpl).toHaveBeenCalledWith('/api/threads/budget/park', expect.anything());
  });
});
