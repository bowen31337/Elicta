import { describe, expect, it, vi } from 'vitest';
import { stopSession } from '../stopSession';
import type { StopSessionFetch } from '../stopSession';
import type { CoverageSummary } from '../types';

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  } as Response;
}

const coverage: CoverageSummary = {
  slots: [{ id: 'scope', label: 'Scope boundary', filled: true }],
  timeRemainingMs: 30_000,
};

describe('stopSession', () => {
  it('posts to the meeting session stop endpoint', async () => {
    const fetchImpl = vi.fn<StopSessionFetch>().mockResolvedValue(
      jsonResponse(200, { session_id: 'session-1', meeting_id: 'meeting-1', stopped_at: '2026-08-19T09:30:00Z' }),
    );

    await stopSession('meeting-1', coverage, { fetch: fetchImpl });

    expect(fetchImpl).toHaveBeenCalledWith(
      '/api/meetings/meeting-1/session/stop',
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('flushes the coverage summary as the request body, converting to wire snake_case', async () => {
    const fetchImpl = vi.fn<StopSessionFetch>().mockResolvedValue(
      jsonResponse(200, { session_id: 'session-1', meeting_id: 'meeting-1', stopped_at: '2026-08-19T09:30:00Z' }),
    );

    await stopSession('meeting-1', coverage, { fetch: fetchImpl });

    const [, init] = fetchImpl.mock.calls[0];
    expect(JSON.parse(init.body as string)).toEqual({
      coverage: {
        slots: [{ id: 'scope', label: 'Scope boundary', filled: true }],
        time_remaining_ms: 30_000,
      },
    });
  });

  it('flushes a null coverage summary as null', async () => {
    const fetchImpl = vi.fn<StopSessionFetch>().mockResolvedValue(
      jsonResponse(200, { session_id: 'session-1', meeting_id: 'meeting-1', stopped_at: '2026-08-19T09:30:00Z' }),
    );

    await stopSession('meeting-1', null, { fetch: fetchImpl });

    const [, init] = fetchImpl.mock.calls[0];
    expect(JSON.parse(init.body as string)).toEqual({ coverage: null });
  });

  it('resolves with the service tier confirmation, converted to domain camelCase', async () => {
    const fetchImpl = vi.fn<StopSessionFetch>().mockResolvedValue(
      jsonResponse(200, { session_id: 'session-1', meeting_id: 'meeting-1', stopped_at: '2026-08-19T09:30:00Z' }),
    );

    const result = await stopSession('meeting-1', coverage, { fetch: fetchImpl });

    expect(result).toEqual({
      sessionId: 'session-1',
      meetingId: 'meeting-1',
      stoppedAt: '2026-08-19T09:30:00Z',
    });
  });

  it('encodes the meeting id in the URL', async () => {
    const fetchImpl = vi.fn<StopSessionFetch>().mockResolvedValue(
      jsonResponse(200, { session_id: 'session-1', meeting_id: 'meeting one', stopped_at: '2026-08-19T09:30:00Z' }),
    );

    await stopSession('meeting one', coverage, { fetch: fetchImpl });

    expect(fetchImpl).toHaveBeenCalledWith('/api/meetings/meeting%20one/session/stop', expect.anything());
  });

  it('throws when the service tier rejects the stop request', async () => {
    const fetchImpl = vi.fn<StopSessionFetch>().mockResolvedValue(jsonResponse(404, { detail: 'meeting not found' }));

    await expect(stopSession('does-not-exist', coverage, { fetch: fetchImpl })).rejects.toThrow(/404/);
  });
});
