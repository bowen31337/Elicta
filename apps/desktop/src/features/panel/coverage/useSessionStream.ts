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
  /**
   * Whether the slow lane can reach a model. Starts `true` and is only ever
   * lowered by the service saying so: a panel that assumed the worst until
   * told otherwise would show the degraded banner for the first second of
   * every meeting, and a banner that cries wolf stops being read.
   */
  modelReachable: boolean;
  /** Why the lane is degraded, when it is. */
  degradedReason: string | null;
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
  /**
   * The meeting to follow, or `null` before one has started. Null is a real
   * state rather than an oversight: the panel exists before capture does, and
   * opening a stream to nothing would reconnect in a loop against a 404.
   */
  meetingId: string | null,
  options: UseSessionStreamOptions = {},
): UseSessionStreamResult {
  const { onNudge, createSource = defaultCreateSource } = options;
  const [coverage, setCoverage] = useState<CoverageSummary | null>(null);
  const [lane, setLane] = useState<{ reachable: boolean; reason: string | null }>({
    reachable: true,
    reason: null,
  });

  // `onNudge` is read through a ref so a caller passing a fresh callback
  // each render does not tear down and reopen the stream connection.
  const onNudgeRef = useRef(onNudge);
  onNudgeRef.current = onNudge;

  useEffect(() => {
    if (meetingId === null) {
      return;
    }
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

    const handleLane = (event: MessageEvent<string>) => {
      const parsed = parseSessionStreamEvent('lane', event.data);
      if (parsed?.type === 'lane') {
        setLane({ reachable: parsed.lane.modelReachable, reason: parsed.lane.reason });
      }
    };

    source.addEventListener('coverage', handleCoverage);
    source.addEventListener('nudge', handleNudge);
    source.addEventListener('lane', handleLane);

    return () => {
      source.removeEventListener('coverage', handleCoverage);
      source.removeEventListener('nudge', handleNudge);
      source.removeEventListener('lane', handleLane);
      source.close();
    };
  }, [meetingId, createSource]);

  return { coverage, modelReachable: lane.reachable, degradedReason: lane.reason };
}
