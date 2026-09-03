import type { SessionStopResult } from './types';
import { apiUrl } from '../../../services/apiClient';

interface WireSessionStop {
  session_id: string | null;
  meeting_id: string;
  stopped_at: string;
}

/** The subset of `fetch` this module relies on, so tests can supply a stub instead of a real network call. */
export type StopSessionFetch = (input: string, init: RequestInit) => Promise<Response>;

export interface StopSessionOptions {
  /** Overridable for tests; defaults to the global `fetch`. */
  fetch?: StopSessionFetch;
}

/**
 * Ends a meeting's live capture session
 * (`POST /api/meetings/{id}/session/stop`).
 *
 * **Everything below this line was true of a route the service did not
 * serve.** The path was absent from the live-session router for as long as
 * this function existed, so every call 404'd and every press of the panel's
 * Stop button did nothing an operator could see. This file was unit-tested
 * throughout — against a stubbed `fetch`, which answers whatever URL it is
 * handed. A stub cannot tell you a route is missing; only the service can, and
 * `tests/e2e/api_integration/test_stopping_a_meeting_from_the_panel.py` is
 * where it does.
 *
 * No request body any more. This used to flush the panel's last-known coverage
 * summary as the session's final state, from when the panel was where coverage
 * was counted. It is derived in the service now — from the meeting's own nudge
 * dispositions, so that one answer lives in one place — and a second copy sent
 * from here would be re-opening the arrangement that once reported eight of
 * eight sections covered on evidence of nothing.
 */
export async function stopSession(
  meetingId: string,
  options: StopSessionOptions = {},
): Promise<SessionStopResult> {
  const { fetch: fetchImpl = fetch } = options;

  const response = await fetchImpl(apiUrl(`/api/meetings/${encodeURIComponent(meetingId)}/session/stop`), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
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
