import { describe, expect, it, vi } from 'vitest';

import { createCaptureStore } from '../../../services/captureSession';
import { goLive } from '../goLive';

/**
 * Start recording, on the screen that can show you the input working.
 *
 * The order is the whole design here. The device is opened *first* and the
 * service is asked second, because a microphone that will not open is the
 * common failure and the only one the desktop shell can detect at all — its
 * source list is a compile-time fact, so there is nothing to pre-flight and
 * the only way to learn whether a device opens is to open it. Going the other
 * way round would leave a session allocated against a recording that never
 * began, and the only endpoint that ends a session also writes a coverage
 * summary and marks the meeting over.
 */

function storeThatOpens() {
  const track = { kind: 'audio', enabled: true, stop: vi.fn() };
  const stream = { getAudioTracks: () => [track], getTracks: () => [track] };
  const getUserMedia = vi.fn(async () => stream);
  return {
    track,
    getUserMedia,
    store: createCaptureStore({
      shellAvailable: () => false,
      audioContext: () => null,
      environment: () => ({
        isSecureContext: true,
        mediaDevices: {
          enumerateDevices: async () => [
            { kind: 'audioinput', deviceId: 'mic-1', label: 'Desk microphone' },
          ],
          getUserMedia,
        },
      }),
    }),
  };
}

describe('going live from the consent screen', () => {
  it('opens the microphone before it allocates a session', async () => {
    const order: string[] = [];
    const { store } = storeThatOpens();
    await store.refresh();

    await goLive('meeting-1', {
      store: {
        ...store,
        check: async (sourceId?: string) => {
          order.push('device');
          await store.check(sourceId);
        },
        beginRecording: async () => {
          order.push('record');
          await store.beginRecording();
        },
      },
      startSession: async () => {
        order.push('service');
        return { sessionId: 'session-1', startedAt: '2026-08-23T14:02:00Z' };
      },
    });

    expect(order).toEqual(['device', 'service', 'record']);
  });

  it('allocates nothing when the microphone will not open', async () => {
    const startSession = vi.fn();
    const store = createCaptureStore({
      shellAvailable: () => false,
      audioContext: () => null,
      environment: () => ({
        isSecureContext: true,
        mediaDevices: {
          enumerateDevices: async () => [
            { kind: 'audioinput', deviceId: 'mic-1', label: 'Desk microphone' },
          ],
          getUserMedia: async () => {
            throw Object.assign(new Error('denied'), { name: 'NotAllowedError' });
          },
        },
      }),
    });
    await store.refresh();

    await expect(goLive('meeting-1', { store, startSession })).rejects.toThrow(/refused/i);
    expect(startSession).not.toHaveBeenCalled();
    expect(store.getSnapshot().status.state).toBe('idle');
  });

  it('releases the microphone when the gate refuses after all', async () => {
    // Rare, because the screen has already read the gate and disables the
    // button while confirmation is outstanding — this is consent changing
    // under the operator between the read and the click.
    const { store, track } = storeThatOpens();
    await store.refresh();

    await expect(
      goLive('meeting-1', {
        store,
        startSession: async () => {
          throw new Error('consent has not been confirmed for this meeting');
        },
      }),
    ).rejects.toThrow(/consent has not been confirmed/);

    expect(track.stop).toHaveBeenCalled();
    expect(store.getSnapshot().status.state).toBe('idle');
  });

  it('records once the meeting is booked', async () => {
    const { store } = storeThatOpens();
    await store.refresh();

    const session = await goLive('meeting-1', {
      store,
      startSession: async () => ({ sessionId: 'session-1', startedAt: '2026-08-23T14:02:00Z' }),
    });

    expect(session.sessionId).toBe('session-1');
    expect(store.getSnapshot().status.state).toBe('capturing');
  });

  it('records on the device already being checked, without re-opening it', async () => {
    // The whole reason the check step exists: the input the operator watched
    // a level on is the input that records, with no second prompt and no gap
    // where the device is shut.
    const { store, getUserMedia } = storeThatOpens();
    await store.refresh();
    await store.check('mic-1');

    await goLive('meeting-1', {
      store,
      startSession: async () => ({ sessionId: 'session-1', startedAt: '2026-08-23T14:02:00Z' }),
    });

    expect(getUserMedia).toHaveBeenCalledTimes(1);
    expect(store.getSnapshot().status.state).toBe('capturing');
  });
});
