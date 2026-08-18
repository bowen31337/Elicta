import { useCallback, useRef, useState } from 'react';
import { stopSession } from './stopSession';
import type { StopSessionOptions } from './stopSession';
import type { CoverageSummary, SessionStopResult } from './types';

export type StopSessionStatus = 'idle' | 'pending' | 'stopped' | 'error';

export interface UseStopSessionResult {
  /** Where the stop request currently stands; starts `'idle'` until `stop` is called. */
  readonly status: StopSessionStatus;
  /** The service tier's confirmation, once `status` is `'stopped'`. */
  readonly result: SessionStopResult | null;
  /** The failure, once `status` is `'error'`. */
  readonly error: Error | null;
  /** Stops the session, flushing `coverage` to the service tier as the session's final state. */
  stop: (coverage: CoverageSummary | null) => Promise<void>;
}

/**
 * Drives `POST /api/meetings/{id}/session/stop` for the panel's "end meeting"
 * action. Exposed as status/result/error rather than throwing from `stop`,
 * so a caller can render a pending or failed stop in place -- ending a
 * meeting is a deliberate operator action, not something to leave unclear
 * if the flush to the service tier fails.
 */
export function useStopSession(meetingId: string, options: StopSessionOptions = {}): UseStopSessionResult {
  const [status, setStatus] = useState<StopSessionStatus>('idle');
  const [result, setResult] = useState<SessionStopResult | null>(null);
  const [error, setError] = useState<Error | null>(null);

  const optionsRef = useRef(options);
  optionsRef.current = options;

  const stop = useCallback(
    async (coverage: CoverageSummary | null) => {
      setStatus('pending');
      setError(null);
      try {
        const stopped = await stopSession(meetingId, coverage, optionsRef.current);
        setResult(stopped);
        setStatus('stopped');
      } catch (err) {
        setError(err instanceof Error ? err : new Error(String(err)));
        setStatus('error');
      }
    },
    [meetingId],
  );

  return { status, result, error, stop };
}
