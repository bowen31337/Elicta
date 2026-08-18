import { useEffect, useRef, useState } from 'react';
import { parseSessionStreamEvent } from './sessionStreamEvents';
import type { CoverageSummary, SessionStreamNudge } from './types';

/**
 * The subset of `EventSource` this hook relies on. Kept as a narrow
 * interface rather than depending on the global `EventSource` directly, so
 * tests can supply a fake source and drive it deterministically instead of
 * needing a real SSE connection (or a jsdom polyfill for one).
 */
export interface SessionStreamSource {
  addEventListener(type: string, listener: (event: MessageEvent<string>) => void): void;
  removeEventListener(type: string, listener: (event: MessageEvent<string>) => void): void;
  close(): void;
}

export type SessionStreamSourceFactory = (url: string) => SessionStreamSource;

const defaultCreateSource: SessionStreamSourceFactory = (url) => new EventSource(url);

export interface UseSessionStreamOptions {
  /** Called for every nudge event the stream carries. */
  onNudge?: (nudge: SessionStreamNudge) => void;
  /** Overridable for tests; defaults to opening a real `EventSource`. */
  createSource?: SessionStreamSourceFactory;
}

export interface UseSessionStreamResult {
  /** The most recent coverage summary the stream has delivered. */
  coverage: CoverageSummary | null;
}

/**
 * Consumes `GET /api/meetings/{id}/session/stream` for the second-screen
 * panel (architecture §7: desktop captures, phone renders). The stream
 * carries both coverage updates and nudges; this hook surfaces coverage as
 * state (FR-6.5's persistent indicator needs "the current summary" to
 * render, not "the log of updates") and forwards nudges through a callback,
 * since nudge queueing and rate-limiting belong to `panel/nudge`, not here.
 */
export function useSessionStream(
  meetingId: string,
  options: UseSessionStreamOptions = {},
): UseSessionStreamResult {
  const { onNudge, createSource = defaultCreateSource } = options;
  const [coverage, setCoverage] = useState<CoverageSummary | null>(null);

  // `onNudge` is read through a ref so a caller passing a fresh callback
  // each render does not tear down and reopen the stream connection.
  const onNudgeRef = useRef(onNudge);
  onNudgeRef.current = onNudge;

  useEffect(() => {
    const source = createSource(`/api/meetings/${encodeURIComponent(meetingId)}/session/stream`);

    const handleCoverage = (event: MessageEvent<string>) => {
      const parsed = parseSessionStreamEvent('coverage', event.data);
      if (parsed?.type === 'coverage') {
        setCoverage(parsed.coverage);
      }
    };

    const handleNudge = (event: MessageEvent<string>) => {
      const parsed = parseSessionStreamEvent('nudge', event.data);
      if (parsed?.type === 'nudge') {
        onNudgeRef.current?.(parsed.nudge);
      }
    };

    source.addEventListener('coverage', handleCoverage);
    source.addEventListener('nudge', handleNudge);

    return () => {
      source.removeEventListener('coverage', handleCoverage);
      source.removeEventListener('nudge', handleNudge);
      source.close();
    };
  }, [meetingId, createSource]);

  return { coverage };
}
