import type { FollowOnCandidate, Thread } from './types';

interface WireFollowOnCandidate {
  question: string;
}

/** The subset of `fetch` this module relies on, so tests can supply a stub instead of a real network call. */
export type RequestFollowOnFetch = (input: string, init: RequestInit) => Promise<Response>;

export interface RequestFollowOnCandidateOptions {
  /** Overridable for tests; defaults to the global `fetch`. */
  fetch?: RequestFollowOnFetch;
}

/**
 * Requests a follow-on candidate question on `thread` (PRD FR-6.8's `Go
 * deeper` chip), via `POST /api/threads/{id}/go-deeper`. The thread id
 * travels in the URL rather than the candidate question in the request
 * body, since going deeper asks the service tier to reason about the
 * thread it already holds -- this call carries no payload beyond which
 * thread to deepen.
 */
export async function requestFollowOnCandidate(
  thread: Thread,
  options: RequestFollowOnCandidateOptions = {},
): Promise<FollowOnCandidate> {
  const { fetch: fetchImpl = fetch } = options;

  const response = await fetchImpl(`/api/threads/${encodeURIComponent(thread.id)}/go-deeper`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  });

  if (!response.ok) {
    throw new Error(`failed to request a follow-on candidate for thread ${thread.id}: ${response.status}`);
  }

  const payload = (await response.json()) as WireFollowOnCandidate;
  return { threadId: thread.id, question: payload.question };
}
