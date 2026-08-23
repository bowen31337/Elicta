import { afterEach, describe, expect, it, vi } from 'vitest';

import { createCaptureStore, type CaptureDeps } from '../captureSession';

/**
 * The capture session, as a module store rather than a hook's `useRef`.
 *
 * The behaviour these tests exist for is the one a hook cannot have: the
 * session outlives the screen that started it. The consent screen opens the
 * device and then navigates to the capture screen, and an operator who walks
 * between screens mid-meeting must not be releasing and re-acquiring their
 * microphone on the way.
 *
 * Written over injected `MediaDevices`-shaped and `invoke`-shaped doubles for
 * the same reason `browserCapture` and `levelMeter` are — every branch is
 * reachable with no browser, no device and no permission prompt.
 */

interface FakeTrack {
  kind: string;
  enabled: boolean;
  stopped: boolean;
}

function fakeStream(deviceId = 'mic-1') {
  const track: FakeTrack = { kind: 'audio', enabled: true, stopped: false };
  return {
    track,
    stream: {
      getAudioTracks: () => [
        {
          ...track,
          get enabled() {
            return track.enabled;
          },
          set enabled(value: boolean) {
            track.enabled = value;
          },
          stop: () => {
            track.stopped = true;
          },
          getSettings: () => ({ deviceId }),
        },
      ],
      getTracks: () => [
        {
          ...track,
          stop: () => {
            track.stopped = true;
          },
        },
      ],
    },
  };
}

function browserDeps(overrides: Record<string, unknown> = {}) {
  const opened = fakeStream();
  const getUserMedia = vi.fn(async () => opened.stream);
  return {
    opened,
    getUserMedia,
    deps: {
      shellAvailable: () => false,
      environment: () => ({
        isSecureContext: true,
        mediaDevices: {
          enumerateDevices: async () => [
            { kind: 'audioinput', deviceId: 'mic-1', label: 'Desk microphone' },
          ],
          getUserMedia,
        },
      }),
      audioContext: () => null,
      ...overrides,
    },
  };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe('in a browser', () => {
  it('opens the chosen device and reports it as capturing', async () => {
    const { deps, getUserMedia } = browserDeps();
    const store = createCaptureStore(deps);

    await store.refresh();
    await store.start('mic-1');

    expect(getUserMedia).toHaveBeenCalledTimes(1);
    expect(store.getSnapshot().status.state).toBe('capturing');
    expect(store.getSnapshot().status.source?.label).toBe('Desk microphone');
  });

  it('refuses a second start rather than opening a second device', async () => {
    const { deps, getUserMedia } = browserDeps();
    const store = createCaptureStore(deps);

    await store.refresh();
    await store.start('mic-1');

    // The shell has always answered this way (`start_capture` returns
    // "capture is already running"); the browser used to stop the old session
    // and open a new one, which was only ever safe because one screen held it.
    await expect(store.start('mic-1')).rejects.toThrow(/already running/);
    expect(getUserMedia).toHaveBeenCalledTimes(1);
    expect(store.getSnapshot().status.state).toBe('capturing');
  });

  it('stays idle and keeps the reason when the device will not open', async () => {
    const refused = Object.assign(new Error('denied'), { name: 'NotAllowedError' });
    const { deps } = browserDeps();
    const store = createCaptureStore({
      ...deps,
      environment: () => ({
        isSecureContext: true,
        mediaDevices: {
          enumerateDevices: async () => [
            { kind: 'audioinput', deviceId: 'mic-1', label: 'Desk microphone' },
          ],
          getUserMedia: async () => {
            throw refused;
          },
        },
      }),
    });

    await store.refresh();

    // Thrown as well as recorded: the consent screen sequences the device
    // before the service, and only a rejection stops it allocating a session
    // for a recording that never began.
    await expect(store.start('mic-1')).rejects.toThrow(/refused/i);
    expect(store.getSnapshot().status.state).toBe('idle');
    expect(store.getSnapshot().error).toMatch(/refused/i);
  });

  it('releases the device on stop', async () => {
    const { deps, opened } = browserDeps();
    const store = createCaptureStore(deps);

    await store.refresh();
    await store.start('mic-1');
    await store.stop();

    expect(opened.track.stopped).toBe(true);
    expect(store.getSnapshot().status.state).toBe('idle');
  });

  it('silences the track on pause without releasing the device', async () => {
    const { deps, opened } = browserDeps();
    const store = createCaptureStore(deps);

    await store.refresh();
    await store.start('mic-1');
    await store.pause();

    expect(opened.track.enabled).toBe(false);
    expect(opened.track.stopped).toBe(false);
    expect(store.getSnapshot().status.state).toBe('paused');

    await store.resume();
    expect(opened.track.enabled).toBe(true);
    expect(store.getSnapshot().status.state).toBe('capturing');
  });

  it('counts recorded time, not wall time, across a pause', async () => {
    // The clock lives here for the same reason the session does: an operator
    // who starts on the consent screen and walks to the capture screen would
    // otherwise arrive at a recording that claims to have just begun.
    let now = 1_000;
    const { deps } = browserDeps();
    const store = createCaptureStore({ ...deps, now: () => now });

    await store.refresh();
    await store.start('mic-1');
    now += 4_000;
    await store.pause();
    now += 60_000; // off the record, and not counted
    await store.resume();
    now += 2_000;

    expect(store.getSnapshot().elapsedSeconds).toBe(6);
  });

  it('opens the device for a check without starting the clock', async () => {
    // The green room. A browser withholds device ids and labels until the
    // first permission grant, so the list drawn before it reads "Microphone 1"
    // and is not a choice at all. Checking is what grants permission, and it
    // is also the operator's only chance to see sound arriving before the
    // choice becomes binding.
    const { deps, getUserMedia } = browserDeps();
    const store = createCaptureStore(deps);

    await store.refresh();
    await store.check();

    expect(getUserMedia).toHaveBeenCalledTimes(1);
    expect(store.getSnapshot().status.state).toBe('checking');
    // Nothing is being recorded, so nothing has been recorded for.
    expect(store.getSnapshot().elapsedSeconds).toBe(0);
  });

  it('records on the device it was checking, without re-opening it', async () => {
    // Promotion, not a restart: a second `getUserMedia` would prompt again on
    // some browsers and would certainly leave a gap where the device is shut.
    const { deps, getUserMedia } = browserDeps();
    const store = createCaptureStore(deps);

    await store.refresh();
    await store.check();
    await store.beginRecording();

    expect(getUserMedia).toHaveBeenCalledTimes(1);
    expect(store.getSnapshot().status.state).toBe('capturing');
  });

  it('refuses to start at all when nothing here can open a microphone', async () => {
    // Silently doing nothing would be worse than failing: the consent screen
    // opens the device and then allocates a session, so a start that no-ops
    // would book a meeting against a recording that cannot exist.
    const store = createCaptureStore({
      shellAvailable: () => false,
      audioContext: () => null,
      environment: () => ({ isSecureContext: false, mediaDevices: undefined }),
    });

    await store.refresh();

    await expect(store.start()).rejects.toThrow(/secure page/i);
    expect(store.getSnapshot().status.state).toBe('idle');
  });

  it('releases the device when the page goes away', async () => {
    // The protection that used to live in the hook's unmount effect. An open
    // microphone keeps the browser's recording indicator lit, which tells an
    // operator they are being recorded when they are not — and now that no
    // unmount stops the session, this is the only thing left that does.
    const handlers: Record<string, () => void> = {};
    const { deps, opened } = browserDeps();
    const store = createCaptureStore({
      ...deps,
      pageEvents: {
        addEventListener: (type: string, handler: () => void) => {
          handlers[type] = handler;
        },
      },
    });

    await store.refresh();
    await store.start('mic-1');
    handlers['pagehide']?.();

    expect(opened.track.stopped).toBe(true);
    expect(store.getSnapshot().status.state).toBe('idle');
  });

  it('samples the meter once, however many screens are watching', async () => {
    vi.useFakeTimers();
    try {
      let reads = 0;
      const analyser = {
        fftSize: 0,
        getByteTimeDomainData(into: Uint8Array) {
          reads += 1;
          // Silence is 128; this is a frame with real signal in it.
          into.fill(200);
        },
      };
      const audioContext = () => () => ({
        createAnalyser: () => analyser,
        createMediaStreamSource: () => ({ connect: () => undefined, disconnect: () => undefined }),
        close: async () => undefined,
      });
      const { deps } = browserDeps();
      const store = createCaptureStore({ ...deps, audioContext });
      // Two screens mounted at once is the ordinary case mid-meeting: the
      // panel floats over the capture screen.
      store.subscribe(() => undefined);
      store.subscribe(() => undefined);

      await store.refresh();
      await store.start('mic-1');
      reads = 0;
      vi.advanceTimersByTime(200);

      // Four ticks at 50ms, and one read each — not one per subscriber.
      expect(reads).toBe(4);
      expect(store.getSnapshot().level?.rms).toBeGreaterThan(0);
      expect(store.getSnapshot().waveform.length).toBe(4);
    } finally {
      vi.useRealTimers();
    }
  });

  it('flattens the meter whole while paused', async () => {
    vi.useFakeTimers();
    try {
      const analyser = {
        fftSize: 0,
        getByteTimeDomainData: (into: Uint8Array) => into.fill(200),
      };
      const audioContext = () => () => ({
        createAnalyser: () => analyser,
        createMediaStreamSource: () => ({ connect: () => undefined, disconnect: () => undefined }),
        close: async () => undefined,
      });
      const { deps } = browserDeps();
      const store = createCaptureStore({ ...deps, audioContext });

      await store.refresh();
      await store.start('mic-1');
      vi.advanceTimersByTime(200);
      await store.pause();

      // Not merely advanced by one silent reading: the wave is a history, and
      // a history of loud speech drawn beside the word "Paused" is the one
      // ambiguity the capture screen exists to remove.
      expect(store.getSnapshot().level).toEqual({ rms: 0, peak: 0 });
      expect(store.getSnapshot().waveform.every((bar) => bar === 0)).toBe(true);
    } finally {
      vi.useRealTimers();
    }
  });
});

describe('in the desktop shell', () => {
  function shellDeps(answer: (command: string) => Promise<unknown>) {
    return {
      shellAvailable: () => true,
      // Cast because the real seam is generic per command; a double answers
      // every command from one function and cannot be.
      invoke: vi.fn(answer) as unknown as CaptureDeps['invoke'],
      environment: () => ({ isSecureContext: true, mediaDevices: undefined }),
      audioContext: () => null,
    };
  }

  it('surfaces what the shell refused with instead of swallowing it', async () => {
    // `start_capture` returns `Result<CaptureStatus, String>` and has three
    // real refusals to offer. `callShell` used to catch every one and return
    // `null`, which made a failed start on the desktop indistinguishable from
    // a successful one — and would have walked the operator to a capture
    // screen reading "Stopped" with nothing to explain it.
    const deps = shellDeps(async (command: string) => {
      if (command === 'start_capture') throw new Error('capture is already running');
      if (command === 'list_audio_sources') return [];
      return null;
    });
    const store = createCaptureStore(deps);

    await expect(store.start('line-in')).rejects.toThrow('capture is already running');
    expect(store.getSnapshot().error).toBe('capture is already running');
    expect(store.getSnapshot().status.state).toBe('idle');
  });

  it('adopts a session the shell is already running', async () => {
    // The desktop half of what the store gives the browser: an operator who
    // started on the consent screen and walked to the capture screen finds the
    // session, because Rust held it the whole time.
    const live = {
      state: 'capturing',
      source: { id: 'line-in', label: 'Audio interface (line in)', degraded: false },
      frames: 42,
    };
    const deps = shellDeps(async (command: string) => {
      if (command === 'capture_status') return live;
      if (command === 'list_audio_sources') return [live.source];
      return null;
    });
    const store = createCaptureStore(deps);

    await store.refresh();

    expect(store.getSnapshot().status).toEqual(live);
    expect(store.getSnapshot().blockedReason).toBeNull();
  });

  it('meters from the frame event, since no stream reaches the page', async () => {
    // Nothing downstream of the shell's audio thread ever sees a sample, so
    // the measurement rides on the frame event, taken where the samples are.
    const emit: Record<string, (payload: unknown) => void> = {};
    const store = createCaptureStore({
      ...shellDeps(async () => null),
      listen: async (name: string, handler: (event: { payload: unknown }) => void) => {
        emit[name] = (payload) => handler({ payload });
        return () => undefined;
      },
    });

    await store.refresh();
    emit['capture://frame']?.({ rms: 0.5, peak: 0.8 });

    expect(store.getSnapshot().level).toEqual({ rms: 0.5, peak: 0.8 });
    expect(store.getSnapshot().waveform.length).toBe(1);
  });

  it('returns to idle when the device is pulled mid-meeting', async () => {
    const emit: Record<string, (payload: unknown) => void> = {};
    const store = createCaptureStore({
      ...shellDeps(async (command: string) =>
        command === 'capture_status'
          ? { state: 'capturing', source: null, frames: 7 }
          : command === 'list_audio_sources'
            ? []
            : null,
      ),
      listen: async (name: string, handler: (event: { payload: unknown }) => void) => {
        emit[name] = (payload) => handler({ payload });
        return () => undefined;
      },
    });

    await store.refresh();
    expect(store.getSnapshot().status.state).toBe('capturing');

    // The session is over either way; showing "recording" would be a lie.
    emit['capture://disconnected']?.('the audio interface was unplugged');

    expect(store.getSnapshot().status.state).toBe('idle');
    expect(store.getSnapshot().error).toMatch(/unplugged/);
  });
});
