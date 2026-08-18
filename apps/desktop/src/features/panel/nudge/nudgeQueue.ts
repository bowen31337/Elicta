import { NUDGE_SURFACE_WINDOW_MS, canSurfaceNudge } from './nudgeRateGate';

/**
 * Holds every candidate that has passed the trigger gate but has not yet
 * been surfaced, plus the timestamp the last nudge was actually displayed.
 */
export interface NudgeQueueState<T> {
  readonly pending: readonly T[];
  readonly lastSurfacedAt: number | null;
}

export function createNudgeQueue<T>(): NudgeQueueState<T> {
  return { pending: [], lastSurfacedAt: null };
}

/**
 * Appends a newly generated candidate to the queue. Generation is bursty —
 * several candidates can pass the trigger gate within milliseconds of each
 * other — so enqueueing never drops or rate-limits anything; every
 * candidate is retained until render time decides whether it may surface
 * (PRD FR-5.8).
 */
export function enqueueNudge<T>(state: NudgeQueueState<T>, candidate: T): NudgeQueueState<T> {
  return { ...state, pending: [...state.pending, candidate] };
}

export interface NudgeRenderResult<T> {
  readonly surfaced: T | null;
  readonly state: NudgeQueueState<T>;
}

/**
 * Called at render time, not at generation time: the 60-second rate limit
 * is evaluated here, against whatever is oldest in the queue, rather than
 * against each candidate as it was produced. If the window has elapsed and
 * a candidate is waiting, it is dequeued and surfaced; otherwise the queue
 * is left untouched so every pending candidate remains eligible on a later
 * render instead of being lost to the burst that produced it.
 */
export function renderNudgeQueue<T>(
  state: NudgeQueueState<T>,
  now: number,
  windowMs: number = NUDGE_SURFACE_WINDOW_MS,
): NudgeRenderResult<T> {
  if (state.pending.length === 0 || !canSurfaceNudge(now, state.lastSurfacedAt, windowMs)) {
    return { surfaced: null, state };
  }
  const [next, ...rest] = state.pending;
  return { surfaced: next, state: { pending: rest, lastSurfacedAt: now } };
}
