import { describe, expect, it, vi } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import { useStopSession } from '../useStopSession';
import type { StopSessionFetch } from '../stopSession';
import type { CaptureStore } from '../../../../services/captureSession';

/**
 * Ending the meeting is two things, and this hook used to do one.
 *
 * It posted, and left the microphone open. Nothing here could have caught
 * that, because nothing here knew a microphone existed — which is the shape of
 * the older bug as well: every test in this file passed while the route being
 * posted to was absent from the service, since a stubbed `fetch` answers
 * whatever URL it is handed. The route itself is proved in
 * `tests/e2e/api_integration/test_stopping_a_meeting_from_the_panel.py`,
 * against the real composition root. What is proved here is the order and the
 * failure handling.
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

/** Just enough of the capture session to watch it being released. */
function fakeStore(stop: () => Promise<void> = () => Promise.resolve()): CaptureStore {
  return { stop: vi.fn(stop) } as unknown as CaptureStore;
}

describe('useStopSession', () => {
  it('starts idle with no result or error', () => {
    const { result } = renderHook(() => useStopSession('meeting-1'));

    expect(result.current.status).toBe('idle');
    expect(result.current.result).toBeNull();
    expect(result.current.error).toBeNull();
  });

  it('transitions through pending to stopped on a successful stop', async () => {
    const fetchImpl = vi.fn<StopSessionFetch>().mockResolvedValue(jsonResponse(200, STOPPED));
    const { result } = renderHook(() =>
      useStopSession('meeting-1', { fetch: fetchImpl, store: fakeStore() }),
    );

    act(() => {
      void result.current.stop();
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

  it('releases the microphone, not only the session', async () => {
    // The half that was missing. A stop that only posts leaves the device
    // open and the chunks uploading, so `receiving_audio` stays true and the
    // bar keeps reading "Recording" with the clock running — the operator's
    // symptom is identical to the route not existing at all.
    const store = fakeStore();
    const fetchImpl = vi.fn<StopSessionFetch>().mockResolvedValue(jsonResponse(200, STOPPED));
    const { result } = renderHook(() => useStopSession('meeting-1', { fetch: fetchImpl, store }));

    await act(async () => {
      await result.current.stop();
    });

    expect(store.stop).toHaveBeenCalledTimes(1);
  });

  it('releases the microphone before it posts', async () => {
    // Order, not just both: a chunk uploaded after the session closed belongs
    // to a session that is no longer open.
    const order: string[] = [];
    const store = fakeStore(async () => {
      order.push('device');
    });
    const fetchImpl = vi.fn<StopSessionFetch>().mockImplementation(async () => {
      order.push('post');
      return jsonResponse(200, STOPPED);
    });
    const { result } = renderHook(() => useStopSession('meeting-1', { fetch: fetchImpl, store }));

    await act(async () => {
      await result.current.stop();
    });

    expect(order).toEqual(['device', 'post']);
  });

  it('still releases the microphone when the service refuses', async () => {
    // The one outcome nobody would accept: an operator presses Stop in a
    // client's meeting, the request fails, and the room carries on being
    // recorded. A session left open in the service is recoverable — the next
    // start closes it. A recording nobody consented to continuing is not.
    const store = fakeStore();
    const fetchImpl = vi.fn<StopSessionFetch>().mockResolvedValue(jsonResponse(500, {}));
    const { result } = renderHook(() => useStopSession('meeting-1', { fetch: fetchImpl, store }));

    await act(async () => {
      await result.current.stop();
    });

    expect(store.stop).toHaveBeenCalledTimes(1);
    expect(result.current.status).toBe('error');
  });

  it('reports a device that would not release', async () => {
    // Reported rather than swallowed: this is the one failure in the pair an
    // operator has to act on, because it is the one where something is still
    // listening.
    const store = fakeStore(() => Promise.reject(new Error('device is busy')));
    const fetchImpl = vi.fn<StopSessionFetch>().mockResolvedValue(jsonResponse(200, STOPPED));
    const { result } = renderHook(() => useStopSession('meeting-1', { fetch: fetchImpl, store }));

    await act(async () => {
      await result.current.stop();
    });

    expect(result.current.status).toBe('error');
    expect(result.current.error?.message).toContain('device is busy');
  });

  it('transitions to error when the stop request fails', async () => {
    const fetchImpl = vi
      .fn<StopSessionFetch>()
      .mockResolvedValue(jsonResponse(404, { detail: 'meeting not found' }));
    const { result } = renderHook(() =>
      useStopSession('does-not-exist', { fetch: fetchImpl, store: fakeStore() }),
    );

    await act(async () => {
      await result.current.stop();
    });

    expect(result.current.status).toBe('error');
    expect(result.current.error).toBeInstanceOf(Error);
    expect(result.current.result).toBeNull();
  });

  it('accepts a stop that closed nothing as a success', async () => {
    // `session_id: null` is the service saying there was nothing open. The
    // operator asked for the recording to be over and it is over; rendering
    // that as a failure would send them back to a button that appears broken.
    const fetchImpl = vi
      .fn<StopSessionFetch>()
      .mockResolvedValue(jsonResponse(200, { ...STOPPED, session_id: null }));
    const { result } = renderHook(() =>
      useStopSession('meeting-1', { fetch: fetchImpl, store: fakeStore() }),
    );

    await act(async () => {
      await result.current.stop();
    });

    expect(result.current.status).toBe('stopped');
    expect(result.current.result?.sessionId).toBeNull();
  });

  it('posts to the meeting it was given, with no body', async () => {
    // No body: coverage is derived in the service now, from the meeting's own
    // nudge dispositions. A copy sent from the panel would be a second answer
    // to a question that has one.
    const fetchImpl = vi.fn<StopSessionFetch>().mockResolvedValue(jsonResponse(200, STOPPED));
    const { result } = renderHook(() =>
      useStopSession('meeting-1', { fetch: fetchImpl, store: fakeStore() }),
    );

    await act(async () => {
      await result.current.stop();
    });

    expect(fetchImpl).toHaveBeenCalledWith(
      '/api/meetings/meeting-1/session/stop',
      expect.anything(),
    );
    const [, init] = fetchImpl.mock.calls[0];
    expect(init.method).toBe('POST');
    expect(init.body).toBeUndefined();
  });
});
