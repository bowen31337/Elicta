import { describe, expect, it, vi } from 'vitest';

import { createCaptureStore } from '../captureSession';
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
