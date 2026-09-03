import { describe, expect, it, vi } from 'vitest';
import { stopSession } from '../stopSession';
import type { StopSessionFetch } from '../stopSession';

/**
 * Every test in this file passed for as long as the route did not exist.
 *
 * A stubbed `fetch` answers whatever URL it is handed, so nothing here could
 * ever have said whether `/api/meetings/{id}/session/stop` was mounted — and
 * it was not, so the panel's Stop button 404'd on every press. What this file
 * can prove is the shape of the request and the translation of the reply;
 * that the service answers at all is proved in
 * `tests/e2e/api_integration/test_stopping_a_meeting_from_the_panel.py`,
 * against the composition root that ships.
 */
function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  } as Response;
}

const STOPPED = {
  session_id: 'session-1',
  meeting_id: 'meeting-1',
  stopped_at: '2026-08-19T09:30:00Z',
};

describe('stopSession', () => {
  it('posts to the meeting session stop endpoint', async () => {
    const fetchImpl = vi.fn<StopSessionFetch>().mockResolvedValue(jsonResponse(200, STOPPED));

    await stopSession('meeting-1', { fetch: fetchImpl });

    expect(fetchImpl).toHaveBeenCalledWith(
      '/api/meetings/meeting-1/session/stop',
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('sends no body', async () => {
    // Coverage is derived in the service, from the meeting's own nudge
    // dispositions, so there is one answer in one place. This used to flush
    // the panel's own count — the arrangement that once reported eight of
    // eight sections covered on evidence of nothing.
    const fetchImpl = vi.fn<StopSessionFetch>().mockResolvedValue(jsonResponse(200, STOPPED));

    await stopSession('meeting-1', { fetch: fetchImpl });

    const [, init] = fetchImpl.mock.calls[0];
    expect(init.body).toBeUndefined();
  });

  it('resolves with the service tier confirmation, converted to domain camelCase', async () => {
    const fetchImpl = vi.fn<StopSessionFetch>().mockResolvedValue(jsonResponse(200, STOPPED));

    const result = await stopSession('meeting-1', { fetch: fetchImpl });

    expect(result).toEqual({
      sessionId: 'session-1',
      meetingId: 'meeting-1',
      stoppedAt: '2026-08-19T09:30:00Z',
    });
  });

  it('carries through a stop that closed nothing', async () => {
    // `null` means the service had no session open for this meeting. It is a
    // success — the operator asked for the recording to be over — and the
    // caller is told which of the two happened rather than having them merged.
    const fetchImpl = vi
      .fn<StopSessionFetch>()
      .mockResolvedValue(jsonResponse(200, { ...STOPPED, session_id: null }));

    const result = await stopSession('meeting-1', { fetch: fetchImpl });

    expect(result.sessionId).toBeNull();
    expect(result.meetingId).toBe('meeting-1');
  });

  it('encodes the meeting id in the URL', async () => {
    const fetchImpl = vi
      .fn<StopSessionFetch>()
      .mockResolvedValue(jsonResponse(200, { ...STOPPED, meeting_id: 'meeting one' }));

    await stopSession('meeting one', { fetch: fetchImpl });

    expect(fetchImpl).toHaveBeenCalledWith(
      '/api/meetings/meeting%20one/session/stop',
      expect.anything(),
    );
  });

  it('throws when the service tier rejects the stop request', async () => {
    const fetchImpl = vi
      .fn<StopSessionFetch>()
      .mockResolvedValue(jsonResponse(404, { detail: 'meeting not found' }));

    await expect(stopSession('does-not-exist', { fetch: fetchImpl })).rejects.toThrow(/404/);
  });
});
