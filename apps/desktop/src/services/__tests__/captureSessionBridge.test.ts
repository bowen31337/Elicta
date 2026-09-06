import { describe, expect, it, vi } from 'vitest';

import { createCaptureStore, type CaptureDeps } from '../captureSession';
import type { AudioBridge } from '../audioBridge';
import type { PcmContextLike, ScriptProcessorLike } from '../../features/capture/pcmTap';

/**
 * The capture session feeding the audio bridge.
 *
 * Everything either side of this is tested on its own — the tap turns a
 * browser's floats into 16kHz samples, the bridge decides whether they may
 * leave the machine. What is asserted here is the join: that a running
 * recording feeds it, that **a paused one does not**, and that stopping ends
 * it once.
 *
 * The pause rule is the one worth stating. In a browser, pausing disables the
 * track, which does not stop the audio graph — it makes it produce digital
 * silence. Left alone, a paused meeting would go on uploading minutes of
 * nothing, and the transcript of a conversation somebody asked to have off the
 * record would contain the silence where it happened, timed and dated. The
 * shell drops paused frames before they leave Rust; this is the browser doing
 * the same.
 */

function fakeContext(sampleRate = 16_000) {
  let processor: (ScriptProcessorLike & { disconnected: boolean }) | null = null;
  const node = () => ({
    connectedTo: [] as unknown[],
    disconnected: false,
    connect(to: unknown) {
      this.connectedTo.push(to);
    },
    disconnect() {
      this.disconnected = true;
    },
  });

  const context: PcmContextLike = {
    sampleRate,
    destination: {},
    createMediaStreamSource: () => node(),
    createScriptProcessor: () => {
      processor = Object.assign(node(), {
        onaudioprocess: null as ScriptProcessorLike['onaudioprocess'],
      });
      return processor;
    },
    createGain: () => Object.assign(node(), { gain: { value: 1 } }),
    close: async () => {},
  };

  return {
    context,
    get closed() {
      return processor?.disconnected ?? false;
    },
    emit(samples: Float32Array) {
      processor?.onaudioprocess?.({ inputBuffer: { getChannelData: () => samples } });
    },
  };
}

function fakeBridge() {
  const pushed: number[] = [];
  let note: string | null = null;
  const bridge: AudioBridge & { pushed: number[] } = {
    start: vi.fn(async () => {}),
    push: (samples: Int16Array) => pushed.push(samples.length),
    stop: vi.fn(async () => {}),
    reportFailure: (message: string) => {
      note = message;
    },
    get note() {
      return note;
    },
    pushed,
  };
  return bridge;
}

function deps(overrides: Record<string, unknown> = {}) {
  const track = { kind: 'audio', enabled: true, stopped: false };
  const stream = {
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
        getSettings: () => ({ deviceId: 'mic-1' }),
      },
    ],
    getTracks: () => [{ ...track, stop: () => {} }],
  };

  return {
    shellAvailable: () => false,
    environment: () => ({
      isSecureContext: true,
      mediaDevices: {
        enumerateDevices: async () => [
          { kind: 'audioinput', deviceId: 'mic-1', label: 'Desk microphone' },
        ],
        getUserMedia: async () => stream,
      },
    }),
    audioContext: () => null,
    ...overrides,
  };
}

describe('the capture session feeding the bridge', () => {
  it('feeds the samples the tap reads to the bridge', async () => {
    const context = fakeContext();
    const bridge = fakeBridge();
    const store = createCaptureStore(
      deps({ pcmContext: () => () => context.context, createBridge: () => bridge }),
    );

    await store.refresh();
    await store.start('mic-1');
    context.emit(new Float32Array(320).fill(0.5));

    expect(bridge.start).toHaveBeenCalledTimes(1);
    expect(bridge.pushed).toEqual([320]);
  });

  it('feeds nothing while the recording is paused', async () => {
    const context = fakeContext();
    const bridge = fakeBridge();
    const store = createCaptureStore(
      deps({ pcmContext: () => () => context.context, createBridge: () => bridge }),
    );

    await store.refresh();
    await store.start('mic-1');
    await store.pause();
    context.emit(new Float32Array(320).fill(0.5));

    expect(bridge.pushed).toEqual([]);
  });

  it('feeds again once the recording resumes', async () => {
    const context = fakeContext();
    const bridge = fakeBridge();
    const store = createCaptureStore(
      deps({ pcmContext: () => () => context.context, createBridge: () => bridge }),
    );

    await store.refresh();
    await store.start('mic-1');
    await store.pause();
    await store.resume();
    context.emit(new Float32Array(320).fill(0.5));

    expect(bridge.pushed).toEqual([320]);
  });

  it('closes the tap and ends the bridge when the recording stops', async () => {
    const context = fakeContext();
    const bridge = fakeBridge();
    const store = createCaptureStore(
      deps({ pcmContext: () => () => context.context, createBridge: () => bridge }),
    );

    await store.refresh();
    await store.start('mic-1');
    await store.stop();

    expect(context.closed).toBe(true);
    expect(bridge.stop).toHaveBeenCalledTimes(1);
  });

  it('publishes what the bridge has to say about this recording', async () => {
    const context = fakeContext();
    const bridge = fakeBridge();
    const held: { publishNote: ((note: string | null) => void) | null } = { publishNote: null };
    const store = createCaptureStore(
      deps({
        pcmContext: () => () => context.context,
        createBridge: (onNote: (note: string | null) => void) => {
          held.publishNote = onNote;
          return bridge;
        },
      }),
    );

    await store.refresh();
    await store.start('mic-1');
    held.publishNote?.('Nobody has confirmed consent for this meeting.');

    expect(store.getSnapshot().uploadNote).toContain('consent');
  });

  it('records with no upload, and says so, in a browser that cannot read the audio', async () => {
    const bridge = fakeBridge();
    const store = createCaptureStore(
      deps({ pcmContext: () => null, createBridge: () => bridge }),
    );

    await store.refresh();
    await store.start('mic-1');

    // Recording must still work: the meter is optional and so is the upload,
    // but an operator told neither would find out from an empty transcript.
    expect(store.getSnapshot().status.state).toBe('capturing');
    expect(bridge.start).not.toHaveBeenCalled();
    expect(store.getSnapshot().uploadNote).toMatch(/transcrib/i);
  });

  it('clears the last recording’s note when a new one starts', async () => {
    const context = fakeContext();
    const bridge = fakeBridge();
    const held: { publishNote: ((note: string | null) => void) | null } = { publishNote: null };
    const store = createCaptureStore(
      deps({
        pcmContext: () => () => context.context,
        createBridge: (onNote: (note: string | null) => void) => {
          held.publishNote = onNote;
          return bridge;
        },
      }),
    );

    await store.refresh();
    await store.start('mic-1');
    held.publishNote?.('The service could not be reached.');
    await store.stop();
    await store.start('mic-1');

    expect(store.getSnapshot().uploadNote).toBeNull();
  });
});

describe('the desktop shell feeding the bridge', () => {
  /**
   * The shell's audio never touches an `AudioContext`: Rust normalises it to
   * 16kHz mono `i16` in the capture pipeline and emits it as
   * `capture://pcm`. So the browser's tap is absent here and the same bridge
   * is fed from the event channel instead — one uploader, two feeds, and the
   * sequencing living in neither backend.
   */
  function shellDeps(bridge: AudioBridge, listeners: Record<string, (event: { payload: unknown }) => void>) {
    return {
      shellAvailable: () => true,
      invoke: vi.fn(async (command: string) => {
        if (command === 'list_audio_sources') return [];
        if (command === 'capture_status') return null;
        return { state: 'capturing', source: null, frames: 0 };
      }) as never,
      environment: () => ({ isSecureContext: true, mediaDevices: undefined }),
      audioContext: () => null,
      pcmContext: () => null,
      createBridge: () => bridge,
      listen: async (name: string, handler: (event: { payload: unknown }) => void) => {
        listeners[name] = handler;
        return () => {};
      },
    };
  }

  it('opens the bridge for a recording even with no browser tap', async () => {
    const bridge = fakeBridge();
    const listeners: Record<string, (event: { payload: unknown }) => void> = {};
    const store = createCaptureStore(shellDeps(bridge, listeners));

    await store.refresh();
    await store.start('line-in');

    // `pcmContext` is null here, which in a browser means "cannot read the
    // audio". In the shell it means nothing of the sort — Rust reads it.
    expect(bridge.start).toHaveBeenCalledTimes(1);
    expect(store.getSnapshot().uploadNote).toBeNull();
  });

  it('opens the event channel for a recording that began without a refresh', async () => {
    const bridge = fakeBridge();
    const listeners: Record<string, (event: { payload: unknown }) => void> = {};
    const store = createCaptureStore(shellDeps(bridge, listeners));

    // Deliberately no `refresh()`. The channel is opened there, and the consent
    // screen starts a recording without ever mounting a screen that refreshes —
    // which would have left the shell recording with nothing listening for its
    // audio, and no sign of it anywhere.
    await store.start('line-in');
    listeners['capture://pcm']?.({ payload: { sequence: 1, pcm: 'AQD+/w==' } });

    expect(bridge.pushed).toEqual([2]);
  });

  it('feeds the samples Rust emits to the bridge', async () => {
    const bridge = fakeBridge();
    const listeners: Record<string, (event: { payload: unknown }) => void> = {};
    const store = createCaptureStore(shellDeps(bridge, listeners));

    await store.refresh();
    await store.start('line-in');
    // The literal `capture.rs` encodes for two samples, asserted there too.
    listeners['capture://pcm']?.({ payload: { sequence: 1, pcm: 'AQD+/w==' } });

    expect(bridge.pushed).toEqual([2]);
  });

  it('feeds nothing from the shell while the recording is paused', async () => {
    const bridge = fakeBridge();
    const listeners: Record<string, (event: { payload: unknown }) => void> = {};
    const store = createCaptureStore(shellDeps(bridge, listeners));

    await store.refresh();
    await store.start('line-in');
    await store.pause();
    // Rust drops paused frames before emitting, so this event should never
    // arrive. Gated here too: two independent guards on the one promise the
    // pause banner makes, and this is the cheaper of them.
    listeners['capture://pcm']?.({ payload: { sequence: 2, pcm: 'AQD+/w==' } });

    expect(bridge.pushed).toEqual([]);
  });

  it('feeds again once a shell recording resumes', async () => {
    const bridge = fakeBridge();
    const listeners: Record<string, (event: { payload: unknown }) => void> = {};
    const store = createCaptureStore(shellDeps(bridge, listeners));

    await store.refresh();
    await store.start('line-in');
    await store.pause();
    await store.resume();
    listeners['capture://pcm']?.({ payload: { sequence: 3, pcm: 'AQD+/w==' } });

    expect(bridge.pushed).toEqual([2]);
  });

  it('ends the bridge when a shell recording stops', async () => {
    const bridge = fakeBridge();
    const listeners: Record<string, (event: { payload: unknown }) => void> = {};
    const store = createCaptureStore(shellDeps(bridge, listeners));

    await store.refresh();
    await store.start('line-in');
    await store.stop();

    expect(bridge.stop).toHaveBeenCalledTimes(1);
  });
});

describe('checking a microphone, which is not a recording', () => {
  /**
   * The seam where two changes met: the green room that opens a device so an
   * operator can see it working, and the bridge that sends audio away. They
   * landed in this file from different directions, and nothing asserted what
   * happens when the first runs without the second.
   *
   * It matters more than an ordinary regression would. Checking happens
   * *before* the client has been told anything — it is the operator alone,
   * confirming their microphone works. Audio leaving the machine at that
   * point would be audio sent from a room where nobody has been asked yet,
   * and the consent screen's promise is made about a recording that has not
   * begun.
   */
  it('creates no bridge at all while checking', async () => {
    const context = fakeContext();
    const createBridge = vi.fn(() => fakeBridge());
    const store = createCaptureStore(
      deps({ pcmContext: () => () => context.context, createBridge }),
    );

    await store.refresh();
    await store.check('mic-1');

    expect(store.getSnapshot().status.state).toBe('checking');
    // Not merely "pushed nothing" — nothing was built that could push.
    expect(createBridge).not.toHaveBeenCalled();
  });

  it('reads no samples while checking, even with the device open', async () => {
    const context = fakeContext();
    const bridge = fakeBridge();
    const store = createCaptureStore(
      deps({ pcmContext: () => () => context.context, createBridge: () => bridge }),
    );

    await store.refresh();
    await store.check('mic-1');
    // The device is open and the graph would carry audio if anything had
    // attached to it.
    context.emit(new Float32Array(1024).fill(0.5));

    expect(bridge.pushed).toEqual([]);
  });

  it('starts uploading only once the check becomes a recording', async () => {
    // The other half: a check that never uploads would be useless if the
    // recording it turns into inherited that silence.
    const context = fakeContext();
    const bridge = fakeBridge();
    const store = createCaptureStore(
      deps({ pcmContext: () => () => context.context, createBridge: () => bridge }),
    );

    await store.refresh();
    await store.check('mic-1');
    await store.beginRecording();
    context.emit(new Float32Array(1024).fill(0.5));

    expect(store.getSnapshot().status.state).toBe('capturing');
    expect(bridge.pushed.length).toBeGreaterThan(0);
  });
});

describe('checking a microphone in the desktop shell', () => {
  /**
   * A different route with the same risk. `check` reaches `start_capture`,
   * which starts the Rust capture thread — and that thread emits
   * `capture://pcm` for as long as it runs, with no notion of whether the UI
   * calls this a check or a recording. The only thing standing between those
   * frames and the network is the `feeding` guard.
   */
  it('drops the frames Rust emits while only checking', async () => {
    const emit: Record<string, (payload: unknown) => void> = {};
    const bridge = fakeBridge();
    const store = createCaptureStore({
      shellAvailable: () => true,
      environment: () => ({ isSecureContext: true, mediaDevices: undefined }),
      audioContext: () => null,
      createBridge: () => bridge,
      invoke: (async (command: string) =>
        command === 'start_capture'
          ? { state: 'capturing', source: null, frames: 0 }
          : command === 'list_audio_sources'
            ? []
            : null) as never,
      listen: async (name: string, handler: (event: { payload: unknown }) => void) => {
        emit[name] = (payload) => handler({ payload });
        return () => undefined;
      },
    });

    await store.refresh();
    await store.check('line-in');
    // Rust is running and emitting, exactly as it would be during a recording.
    emit['capture://pcm']?.({ pcm: 'AAAAAAAAAAA=' });

    expect(store.getSnapshot().status.state).toBe('checking');
    expect(bridge.pushed).toEqual([]);
  });
});

describe('a recording that hears nothing at all', () => {
  /**
   * A microphone that is open, delivering on time, and completely silent.
   *
   * The silence watch beside this one counts *arrivals*, which is the wrong
   * question for this failure: an input that is muted, pointed at the wrong
   * device, or denied permission by the OS still delivers buffers on schedule
   * — full of zeros. Every count is met, so nothing warns; audio reaches the
   * service, so the lane reports it is transcribing; and the recogniser
   * returns "" for every window because there is nothing in them. The
   * operator watches "Listening…" over a moving clock beside an empty
   * transcript for as long as they are willing to. This ran for eight
   * minutes, with every part of the chain reporting success.
   *
   * On macOS it is the shape a refused Microphone permission takes:
   * CoreAudio starts, reports success, and hands back silence rather than an
   * error.
   */
  function hearing(level: { byte: number }) {
    const context = fakeContext();
    // 128 is the zero line of a byte-domain waveform, so a frame filled with
    // 128 is digital silence and anything else is signal.
    const audioContext = () => () => ({
      createAnalyser: () => ({
        fftSize: 0,
        getByteTimeDomainData: (into: Uint8Array) => into.fill(level.byte),
      }),
      createMediaStreamSource: () => ({ connect: () => undefined, disconnect: () => undefined }),
      close: async () => undefined,
    });
    const store = createCaptureStore(
      deps({
        audioContext,
        pcmContext: () => () => context.context,
        createBridge: () => fakeBridge(),
      }) as Partial<CaptureDeps>,
    );
    return { store, context };
  }

  /**
   * Run the recording for `ms`, delivering a buffer every second throughout.
   *
   * The buffers are the point: this failure is buffers arriving *and* being
   * empty, so a fixture that stopped delivering them would be modelling the
   * other failure and would raise the other warning.
   */
  async function record(context: ReturnType<typeof fakeContext>, ms: number) {
    for (let elapsed = 0; elapsed < ms; elapsed += 1_000) {
      context.emit(new Float32Array(320));
      await vi.advanceTimersByTimeAsync(1_000);
    }
  }

  it('says so when every sample is zero', async () => {
    vi.useFakeTimers();
    try {
      const { store, context } = hearing({ byte: 128 });

      await store.start('mic-1');
      await record(context, 25_000);

      const note = store.getSnapshot().uploadNote ?? '';
      expect(note).toMatch(/complete silence/i);
      // Three causes, indistinguishable from here, so the remedy names all of
      // them rather than guessing one.
      expect(note).toMatch(/muted/i);
      expect(note).toMatch(/privacy & security/i);
    } finally {
      vi.useRealTimers();
    }
  });

  it('says nothing about a quiet room that still has a noise floor', async () => {
    // A real microphone in a silent room is never digitally zero. Warning
    // here would send an operator to check hardware that is working.
    vi.useFakeTimers();
    try {
      const { store, context } = hearing({ byte: 130 });

      await store.start('mic-1');
      await record(context, 25_000);

      expect(store.getSnapshot().uploadNote).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it('stops saying it once the microphone is heard from', async () => {
    vi.useFakeTimers();
    try {
      const level = { byte: 128 };
      const { store, context } = hearing(level);

      await store.start('mic-1');
      await record(context, 25_000);
      expect(store.getSnapshot().uploadNote).toMatch(/complete silence/i);

      // The operator unmutes, or grants the permission and speaks.
      level.byte = 200;
      await record(context, 25_000);

      expect(store.getSnapshot().uploadNote).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it('says nothing while the recording is paused', async () => {
    // Pausing disables the track, which does not stop the graph — it makes it
    // produce digital silence. This is the case a second watch lifecycle
    // would have got wrong first, which is why both watches share one.
    vi.useFakeTimers();
    try {
      const { store, context } = hearing({ byte: 128 });
      await store.start('mic-1');
      await store.pause();

      await record(context, 25_000);

      expect(store.getSnapshot().uploadNote).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });
});
