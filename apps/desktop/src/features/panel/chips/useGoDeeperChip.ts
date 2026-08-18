import { useCallback, useRef, useState } from 'react';
import { requestFollowOnCandidate } from './requestFollowOnCandidate';
import type { RequestFollowOnCandidateOptions } from './requestFollowOnCandidate';
import type { FollowOnCandidate, Thread } from './types';

export type GoDeeperStatus = 'idle' | 'pending' | 'loaded' | 'error';

export interface UseGoDeeperChipOptions extends RequestFollowOnCandidateOptions {
  /**
   * Fire-and-forget notification of the follow-on candidate, mirroring
   * `useAskedItChip`'s `onAsked` -- never awaited, since `candidate` is
   * already the value this hook renders by the time this callback runs.
   */
  onFollowOn?: (candidate: FollowOnCandidate) => void;
}

export interface UseGoDeeperChipResult {
  /** Where the follow-on request currently stands; starts `'idle'` until `tap` is called. */
  readonly status: GoDeeperStatus;
  /** The follow-on candidate, once `status` is `'loaded'`. */
  readonly candidate: FollowOnCandidate | null;
  /** The failure, once `status` is `'error'`. */
  readonly error: Error | null;
  /** Requests a follow-on candidate on `thread` from the service tier. */
  readonly tap: () => Promise<void>;
}

/**
 * Backs the `Go deeper` chip (PRD FR-6.8): unlike `Asked it` and `What am I
 * missing?`, which resolve locally with no round trip, going deeper asks
 * the service tier to generate a follow-on question on the same thread, so
 * this hook exposes status/result/error the same way `useStopSession` does
 * for its own network call -- a caller can render a pending or failed
 * request in place rather than assuming the tap already produced a result.
 * A second tap while already `'pending'` still fires; the service tier
 * settles which response, if any, lands last.
 */
export function useGoDeeperChip(thread: Thread, options: UseGoDeeperChipOptions = {}): UseGoDeeperChipResult {
  const [status, setStatus] = useState<GoDeeperStatus>('idle');
  const [candidate, setCandidate] = useState<FollowOnCandidate | null>(null);
  const [error, setError] = useState<Error | null>(null);

  const optionsRef = useRef(options);
  optionsRef.current = options;

  const tap = useCallback(async () => {
    setStatus('pending');
    setError(null);
    try {
      const { onFollowOn, ...fetchOptions } = optionsRef.current;
      const result = await requestFollowOnCandidate(thread, fetchOptions);
      setCandidate(result);
      setStatus('loaded');
      onFollowOn?.(result);
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
      setStatus('error');
    }
  }, [thread]);

  return { status, candidate, error, tap };
}
