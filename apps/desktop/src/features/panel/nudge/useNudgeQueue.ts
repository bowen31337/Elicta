import { useCallback, useRef, useState } from 'react';
import { NUDGE_SURFACE_WINDOW_MS } from './nudgeRateGate';
import { NudgeQueueState, createNudgeQueue, enqueueNudge, renderNudgeQueue } from './nudgeQueue';

export interface UseNudgeQueueOptions {
  windowMs?: number;
  now?: () => number;
}

export interface UseNudgeQueueResult<T> {
  /** Called at generation time, for every candidate that passes the trigger gate. Never drops. */
  enqueue: (candidate: T) => void;
  /**
   * Called at render time (e.g. on a display tick). Applies the FR-5.8 rate
   * limit against the queue's oldest pending candidate and, if the window
   * has elapsed, surfaces it. Returns null when nothing may surface yet.
   */
  render: () => T | null;
  /** The most recently surfaced nudge, kept until `render` surfaces a new one. */
  displayed: T | null;
  pendingCount: () => number;
  lastSurfacedAt: () => number | null;
}

/**
 * Buffers generated nudge candidates and enforces the surfacing rate limit
 * at render time rather than at generation time, because generation is
 * bursty: several candidates can clear the trigger gate within the same
 * second. Queueing them and deciding at render time means a burst fills the
 * queue instead of having all but the first candidate dropped outright.
 */
export function useNudgeQueue<T>(options: UseNudgeQueueOptions = {}): UseNudgeQueueResult<T> {
  const { windowMs = NUDGE_SURFACE_WINDOW_MS, now = () => Date.now() } = options;
  const stateRef = useRef<NudgeQueueState<T>>(createNudgeQueue<T>());
  const [displayed, setDisplayed] = useState<T | null>(null);

  const enqueue = useCallback((candidate: T) => {
    stateRef.current = enqueueNudge(stateRef.current, candidate);
  }, []);

  const render = useCallback(() => {
    const { surfaced, state } = renderNudgeQueue(stateRef.current, now(), windowMs);
    stateRef.current = state;
    if (surfaced !== null) {
      setDisplayed(surfaced);
    }
    return surfaced;
  }, [now, windowMs]);

  const pendingCount = useCallback(() => stateRef.current.pending.length, []);
  const lastSurfacedAt = useCallback(() => stateRef.current.lastSurfacedAt, []);

  return { enqueue, render, displayed, pendingCount, lastSurfacedAt };
}
