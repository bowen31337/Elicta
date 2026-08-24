import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * One GET against the service, in the shape every full screen needs.
 *
 * The screens this backs were shipped rendering hardcoded empty props, so the
 * running app showed em dashes and empty lists while the fixture harness
 * showed a full screen. The failure mode that matters when connecting them is
 * not "no data" — it is **an unreachable service that looks like no data**.
 * So the four outcomes are kept apart rather than collapsed into
 * `data | null`:
 *
 * - `idle`    — nothing to ask for yet (no id selected)
 * - `loading` — asked, still waiting
 * - `ready`   — the service answered; `data` may legitimately be empty
 * - `missing` — the service answered 404: this thing has not happened yet
 * - `error`   — the service could not be reached, or refused
 *
 * `missing` is deliberately not `error`. A meeting that was never transcribed
 * 404s on its divergences, and that is a normal point in its life, not a
 * fault. Telling an operator "something is broken" there would train them to
 * ignore the message that means it.
 *
 * Requests go to a relative apiUrl(`/api/...`) path: the panel is served same-origin
 * with an `/api` proxy (`vite.config.ts`), so there is no base URL to
 * configure and no CORS to negotiate. That is the same choice
 * `useDebriefChat` makes.
 */
export type ResourceStatus = 'idle' | 'loading' | 'ready' | 'missing' | 'error';

export interface Resource<T> {
  readonly data: T | null;
  readonly status: ResourceStatus;
  /** Set only when `status` is `error`; what to show the operator. */
  readonly error: string | null;
  readonly reload: () => void;
}

export class ServiceUnreachable extends Error {}

/** A GET that treats 404 as a value rather than a throw. */
export async function fetchJson<T>(path: string): Promise<T | null> {
  let response: Response;
  try {
    response = await fetch(path, { headers: { Accept: 'application/json' } });
  } catch {
    throw new ServiceUnreachable('The service could not be reached.');
  }
  if (response.status === 404) return null;
  if (!response.ok) {
    throw new ServiceUnreachable(`The service answered ${response.status}.`);
  }
  return (await response.json()) as T;
}

/**
 * Fetches `path`, re-fetching whenever it changes. A `null` path means there
 * is nothing to ask for yet — a screen waiting on an engagement to be chosen —
 * and stays `idle` rather than reporting an error it has not earned.
 */
export function useResource<T>(path: string | null): Resource<T> {
  const [data, setData] = useState<T | null>(null);
  const [status, setStatus] = useState<ResourceStatus>(path === null ? 'idle' : 'loading');
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  /**
   * The path `data` was answered for, or `null` when there is no answer to
   * stand on. This is what tells a refetch from a change of subject.
   */
  const answered = useRef<string | null>(null);

  useEffect(() => {
    if (path === null) {
      setData(null);
      setStatus('idle');
      setError(null);
      answered.current = null;
      return;
    }

    // A screen can be switched away from mid-request, and a late answer must
    // not overwrite what replaced it.
    let live = true;
    // Re-asking the same question keeps the answer on screen until a new one
    // arrives. Screens reload every read after every write, and blanking them
    // meanwhile cost the operator their scroll position mid-review. A
    // *different* path still blanks: holding the last answer there would show
    // one engagement's documents under another engagement's name.
    if (answered.current !== path) {
      setStatus('loading');
    }
    setError(null);

    void (async () => {
      try {
        const body = await fetchJson<T>(path);
        if (!live) return;
        setData(body);
        answered.current = path;
        setStatus(body === null ? 'missing' : 'ready');
      } catch (cause) {
        if (!live) return;
        setData(null);
        // Staleness may not outlive the connection: the next attempt starts
        // from nothing rather than from an answer this one just disproved.
        answered.current = null;
        setStatus('error');
        setError(cause instanceof Error ? cause.message : 'The service could not be reached.');
      }
    })();

    return () => {
      live = false;
    };
  }, [path, attempt]);

  return {
    data,
    status,
    error,
    reload: useCallback(() => setAttempt((count) => count + 1), []),
  };
}

/** The worst of several statuses — what a screen assembled from more than one read should show. */
export function combineStatus(...statuses: readonly ResourceStatus[]): ResourceStatus {
  if (statuses.includes('error')) return 'error';
  if (statuses.includes('loading')) return 'loading';
  if (statuses.includes('idle')) return 'idle';
  if (statuses.includes('ready')) return 'ready';
  return statuses.length > 0 ? 'missing' : 'idle';
}
