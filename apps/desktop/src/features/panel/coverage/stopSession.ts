import type { CoverageSummary, SessionStopResult } from './types';
import { apiUrl } from '../../../services/apiClient';

interface WireCoverageSlot {
  id: string;
  label: string;
  filled: boolean;
}

interface WireCoverageSummary {
  slots: WireCoverageSlot[];
  time_remaining_ms: number | null;
}

interface WireSessionStop {
  session_id: string;
  meeting_id: string;
  stopped_at: string;
}

/** The subset of `fetch` this module relies on, so tests can supply a stub instead of a real network call. */
export type StopSessionFetch = (input: string, init: RequestInit) => Promise<Response>;

export interface StopSessionOptions {
  /** Overridable for tests; defaults to the global `fetch`. */
  fetch?: StopSessionFetch;
}

function toWireCoverage(coverage: CoverageSummary | null): WireCoverageSummary | null {
  if (coverage === null) {
    return null;
  }
  return {
    slots: coverage.slots.map((slot) => ({ id: slot.id, label: slot.label, filled: slot.filled })),
    time_remaining_ms: coverage.timeRemainingMs,
  };
}

/**
 * Stops a meeting's live capture session and flushes the panel's last-known
 * coverage summary to the service tier (`POST /api/meetings/{id}/session/stop`).
 * The summary travels in the request body rather than relying on whatever the
 * service last saw over the session stream, since a stream event can still be
 * in flight (or dropped) when the operator ends the meeting -- the stop call
 * is the one place this panel guarantees its state reaches the service tier.
 */
export async function stopSession(
  meetingId: string,
  coverage: CoverageSummary | null,
  options: StopSessionOptions = {},
): Promise<SessionStopResult> {
  const { fetch: fetchImpl = fetch } = options;

  const response = await fetchImpl(apiUrl(`/api/meetings/${encodeURIComponent(meetingId)}/session/stop`), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ coverage: toWireCoverage(coverage) }),
  });

  if (!response.ok) {
    throw new Error(`failed to stop session for meeting ${meetingId}: ${response.status}`);
  }

  const payload = (await response.json()) as WireSessionStop;
  return {
    sessionId: payload.session_id,
    meetingId: payload.meeting_id,
    stoppedAt: payload.stopped_at,
  };
}
