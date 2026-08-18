import { useCallback, useRef, useState } from 'react';
import { parkThread } from './parkThread';
import type { ParkThreadOptions } from './parkThread';
import type { ParkedThread, Thread } from './types';

export type ParkItStatus = 'idle' | 'pending' | 'parked' | 'error';

export interface UseParkItChipOptions extends ParkThreadOptions {
  /**
   * Fire-and-forget notification that the thread was parked, mirroring
   * `useGoDeeperChip`'s `onFollowOn` -- never awaited, since `parked` is
   * already the value this hook renders by the time this callback runs.
   */
  onParked?: (parked: ParkedThread) => void;
}

export interface UseParkItChipResult {
  /** Where the park request currently stands; starts `'idle'` until `tap` is called. */
  readonly status: ParkItStatus;
  /** Confirmation of the persisted `open_questions` row, once `status` is `'parked'`. */
  readonly parked: ParkedThread | null;
  /** The failure, once `status` is `'error'`. */
  readonly error: Error | null;
  /** Defers `thread` to the `open_questions` table on the service tier. */
  readonly tap: () => Promise<void>;
}

/**
 * Backs the `Park it` chip (PRD FR-6.8): tapping defers `thread` to the
 * `open_questions` table for later follow-up, without touching the
 * thread's own resolution state -- `thread.operatorAskedAt` is untouched by
 * parking, since parking and being asked live (FR-6.10) are two
 * independent ways a thread gets dealt with, and this hook never dismisses
 * or removes the thread it was called with. Exposes status/result/error
 * the same way `useGoDeeperChip` does for its own network call, so a
 * caller can render a pending or failed request in place. A second tap
 * while already `'pending'` still fires; the service tier settles which
 * request, if any, lands last.
 */
export function useParkItChip(thread: Thread, options: UseParkItChipOptions = {}): UseParkItChipResult {
  const [status, setStatus] = useState<ParkItStatus>('idle');
  const [parked, setParked] = useState<ParkedThread | null>(null);
  const [error, setError] = useState<Error | null>(null);

  const optionsRef = useRef(options);
  optionsRef.current = options;

  const tap = useCallback(async () => {
    setStatus('pending');
    setError(null);
    try {
      const { onParked, ...fetchOptions } = optionsRef.current;
      const result = await parkThread(thread, fetchOptions);
      setParked(result);
      setStatus('parked');
      onParked?.(result);
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
      setStatus('error');
    }
  }, [thread]);

  return { status, parked, error, tap };
}
