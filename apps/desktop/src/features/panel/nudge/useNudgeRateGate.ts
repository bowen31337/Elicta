import { useCallback, useRef } from 'react';
import { NUDGE_SURFACE_WINDOW_MS, canSurfaceNudge } from './nudgeRateGate';

export interface UseNudgeRateGateOptions {
  windowMs?: number;
  now?: () => number;
}

export interface UseNudgeRateGateResult<T> {
  admit: (candidate: T) => T | null;
  lastSurfacedAt: () => number | null;
}

/**
 * Sits in front of `useNudgeStack`'s `pushNudge` (or any equivalent
 * surfacing call). Callers run every candidate that passes the trigger gate
 * through `admit`; only the first one in each `windowMs` span is returned
 * (and starts the next window) — the rest are dropped, not queued, since
 * FR-5.8 caps surfacing frequency rather than asking for delayed delivery of
 * the remainder.
 */
export function useNudgeRateGate<T>(
  options: UseNudgeRateGateOptions = {},
): UseNudgeRateGateResult<T> {
  const { windowMs = NUDGE_SURFACE_WINDOW_MS, now = () => Date.now() } = options;
  const lastSurfacedAtRef = useRef<number | null>(null);

  const admit = useCallback(
    (candidate: T) => {
      const timestamp = now();
      if (!canSurfaceNudge(timestamp, lastSurfacedAtRef.current, windowMs)) {
        return null;
      }
      lastSurfacedAtRef.current = timestamp;
      return candidate;
    },
    [now, windowMs],
  );

  const lastSurfacedAt = useCallback(() => lastSurfacedAtRef.current, []);

  return { admit, lastSurfacedAt };
}
