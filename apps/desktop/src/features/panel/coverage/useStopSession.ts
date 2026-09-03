import { useCallback, useRef, useState } from 'react';
import { stopSession } from './stopSession';
import type { StopSessionOptions } from './stopSession';
import type { SessionStopResult } from './types';
import { captureSession, type CaptureStore } from '../../../services/captureSession';

export type StopSessionStatus = 'idle' | 'pending' | 'stopped' | 'error';

export interface UseStopSessionResult {
  /** Where the stop request currently stands; starts `'idle'` until `stop` is called. */
  readonly status: StopSessionStatus;
  /** The service tier's confirmation, once `status` is `'stopped'`. */
  readonly result: SessionStopResult | null;
  /** The failure, once `status` is `'error'`. */
  readonly error: Error | null;
  /** Ends the meeting: releases the microphone, then closes the session. */
  stop: () => Promise<void>;
}

export interface UseStopSessionOptions extends StopSessionOptions {
  /** The capture session to release. The application's own, outside a test. */
  readonly store?: CaptureStore;
}

/**
 * Ends the meeting, for the panel's recording bar.
 *
 * **Two halves, and it only ever had one.** Closing the session tells the
 * service the meeting is over; it does not close the microphone, which lives
 * in `services/captureSession` and is what is actually producing audio. So
 * even once the route existed, a stop that only posted would have left the
 * device open, chunks uploading, `receiving_audio` true, and the bar reading
 * "Recording" with its clock still counting — the same symptom the missing
 * route produced, from a different cause. The device goes first, so nothing
 * further arrives for a session that is being closed.
 *
 * The device is released **even if the post then fails**. An operator pressing
 * Stop in a client's meeting is asking for the microphone to be shut; leaving
 * it open because a request failed would be the one outcome nobody would
 * accept, and it is also the one that keeps the browser's recording indicator
 * lit. A session left open in the service is recoverable — the next start
 * closes it — and a recording nobody consented to continuing is not.
 *
 * Exposed as status/result/error rather than throwing from `stop`, so a caller
 * can render a pending or failed stop in place. That mattering is not
 * hypothetical: this hook has been returning `'error'` on every press for as
 * long as the route was missing, and the panel rendered none of it.
 */
export function useStopSession(
  meetingId: string,
  options: UseStopSessionOptions = {},
): UseStopSessionResult {
  const [status, setStatus] = useState<StopSessionStatus>('idle');
  const [result, setResult] = useState<SessionStopResult | null>(null);
  const [error, setError] = useState<Error | null>(null);

  const optionsRef = useRef(options);
  optionsRef.current = options;

  const stop = useCallback(async () => {
    setStatus('pending');
    setError(null);
    const { store = captureSession, ...request } = optionsRef.current;
    // First, and outside the try: the microphone closing is not conditional
    // on the service answering. Its own failure is still reported, because a
    // device that would not release is the one thing here an operator has to
    // know about.
    let deviceError: Error | null = null;
    try {
      await store.stop();
    } catch (err) {
      deviceError = err instanceof Error ? err : new Error(String(err));
    }
    try {
      const stopped = await stopSession(meetingId, request);
      if (deviceError !== null) throw deviceError;
      setResult(stopped);
      setStatus('stopped');
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
      setStatus('error');
    }
  }, [meetingId]);

  return { status, result, error, stop };
}
