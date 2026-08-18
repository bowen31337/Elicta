import { describe, expect, it, vi } from 'vitest';
import { parkThread } from '../parkThread';
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

describe('parkThread', () => {
  it('posts to the thread park endpoint', async () => {
    const fetchImpl = vi.fn<ParkThreadFetch>().mockResolvedValue(jsonResponse(200, { open_question_id: 'oq-1' }));

    await parkThread(thread, { fetch: fetchImpl });

    expect(fetchImpl).toHaveBeenCalledWith('/api/threads/budget/park', expect.objectContaining({ method: 'POST' }));
  });

  it('resolves with confirmation scoped to the requesting thread', async () => {
    const fetchImpl = vi.fn<ParkThreadFetch>().mockResolvedValue(jsonResponse(200, { open_question_id: 'oq-1' }));

    const result = await parkThread(thread, { fetch: fetchImpl });

    expect(result).toEqual({ threadId: 'budget', openQuestionId: 'oq-1' });
  });

  it('encodes the thread id in the URL', async () => {
    const spacedThread: Thread = { id: 'thread one', question: 'q', operatorAskedAt: null };
    const fetchImpl = vi.fn<ParkThreadFetch>().mockResolvedValue(jsonResponse(200, { open_question_id: 'oq-2' }));

    await parkThread(spacedThread, { fetch: fetchImpl });

    expect(fetchImpl).toHaveBeenCalledWith('/api/threads/thread%20one/park', expect.anything());
  });

  it('throws when the service tier rejects the request', async () => {
    const fetchImpl = vi.fn<ParkThreadFetch>().mockResolvedValue(jsonResponse(404, { detail: 'thread not found' }));

    await expect(parkThread(thread, { fetch: fetchImpl })).rejects.toThrow(/404/);
  });
});
