import type { ParkedThread, Thread } from './types';

interface WireParkedThread {
  open_question_id: string;
}

/** The subset of `fetch` this module relies on, so tests can supply a stub instead of a real network call. */
export type ParkThreadFetch = (input: string, init: RequestInit) => Promise<Response>;

export interface ParkThreadOptions {
  /** Overridable for tests; defaults to the global `fetch`. */
  fetch?: ParkThreadFetch;
}

/**
 * Defers `thread` to the `open_questions` table (PRD FR-6.8's `Park it`
 * chip), via `POST /api/threads/{id}/park`. Mirrors
 * `requestFollowOnCandidate`'s shape: the thread id travels in the URL
 * rather than the question text in the request body, since the service
 * tier already holds the thread it's being asked to park -- this call
 * carries no payload beyond which thread to defer.
 */
export async function parkThread(thread: Thread, options: ParkThreadOptions = {}): Promise<ParkedThread> {
  const { fetch: fetchImpl = fetch } = options;

  const response = await fetchImpl(`/api/threads/${encodeURIComponent(thread.id)}/park`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  });

  if (!response.ok) {
    throw new Error(`failed to park thread ${thread.id}: ${response.status}`);
  }

  const payload = (await response.json()) as WireParkedThread;
  return { threadId: thread.id, openQuestionId: payload.open_question_id };
}
