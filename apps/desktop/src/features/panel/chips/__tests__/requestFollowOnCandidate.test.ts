import { describe, expect, it, vi } from 'vitest';
import { requestFollowOnCandidate } from '../requestFollowOnCandidate';
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

describe('requestFollowOnCandidate', () => {
  it('posts to the thread go-deeper endpoint', async () => {
    const fetchImpl = vi
      .fn<RequestFollowOnFetch>()
      .mockResolvedValue(jsonResponse(200, { question: 'What happens if the budget slips?' }));

    await requestFollowOnCandidate(thread, { fetch: fetchImpl });

    expect(fetchImpl).toHaveBeenCalledWith(
      '/api/threads/budget/go-deeper',
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('resolves with the follow-on candidate scoped to the requesting thread', async () => {
    const fetchImpl = vi
      .fn<RequestFollowOnFetch>()
      .mockResolvedValue(jsonResponse(200, { question: 'What happens if the budget slips?' }));

    const result = await requestFollowOnCandidate(thread, { fetch: fetchImpl });

    expect(result).toEqual({
      threadId: 'budget',
      question: 'What happens if the budget slips?',
    });
  });

  it('encodes the thread id in the URL', async () => {
    const spacedThread: Thread = { id: 'thread one', question: 'q', operatorAskedAt: null };
    const fetchImpl = vi.fn<RequestFollowOnFetch>().mockResolvedValue(jsonResponse(200, { question: 'q2' }));

    await requestFollowOnCandidate(spacedThread, { fetch: fetchImpl });

    expect(fetchImpl).toHaveBeenCalledWith('/api/threads/thread%20one/go-deeper', expect.anything());
  });

  it('throws when the service tier rejects the request', async () => {
    const fetchImpl = vi.fn<RequestFollowOnFetch>().mockResolvedValue(jsonResponse(404, { detail: 'thread not found' }));

    await expect(requestFollowOnCandidate(thread, { fetch: fetchImpl })).rejects.toThrow(/404/);
  });
});
