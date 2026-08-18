import { describe, expect, it, vi } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import { useStopSession } from '../useStopSession';
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

describe('useStopSession', () => {
  it('starts idle with no result or error', () => {
    const { result } = renderHook(() => useStopSession('meeting-1'));

    expect(result.current.status).toBe('idle');
    expect(result.current.result).toBeNull();
    expect(result.current.error).toBeNull();
  });

  it('transitions through pending to stopped on a successful stop', async () => {
    const fetchImpl = vi.fn<StopSessionFetch>().mockResolvedValue(
      jsonResponse(200, { session_id: 'session-1', meeting_id: 'meeting-1', stopped_at: '2026-08-19T09:30:00Z' }),
    );
    const { result } = renderHook(() => useStopSession('meeting-1', { fetch: fetchImpl }));

    act(() => {
      void result.current.stop(coverage);
    });
    expect(result.current.status).toBe('pending');

    await waitFor(() => expect(result.current.status).toBe('stopped'));
    expect(result.current.result).toEqual({
      sessionId: 'session-1',
      meetingId: 'meeting-1',
      stoppedAt: '2026-08-19T09:30:00Z',
    });
    expect(result.current.error).toBeNull();
  });

  it('transitions to error when the stop request fails', async () => {
    const fetchImpl = vi.fn<StopSessionFetch>().mockResolvedValue(jsonResponse(404, { detail: 'meeting not found' }));
    const { result } = renderHook(() => useStopSession('does-not-exist', { fetch: fetchImpl }));

    await act(async () => {
      await result.current.stop(coverage);
    });

    expect(result.current.status).toBe('error');
    expect(result.current.error).toBeInstanceOf(Error);
    expect(result.current.result).toBeNull();
  });

  it('passes the meeting id and coverage summary through to stopSession', async () => {
    const fetchImpl = vi.fn<StopSessionFetch>().mockResolvedValue(
      jsonResponse(200, { session_id: 'session-1', meeting_id: 'meeting-1', stopped_at: '2026-08-19T09:30:00Z' }),
    );
    const { result } = renderHook(() => useStopSession('meeting-1', { fetch: fetchImpl }));

    await act(async () => {
      await result.current.stop(coverage);
    });

    expect(fetchImpl).toHaveBeenCalledWith('/api/meetings/meeting-1/session/stop', expect.anything());
    const [, init] = fetchImpl.mock.calls[0];
    expect(JSON.parse(init.body as string)).toEqual({
      coverage: { slots: [{ id: 'scope', label: 'Scope boundary', filled: true }], time_remaining_ms: 30_000 },
    });
  });
});
