import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { createCaptureStore } from '../captureSession';
import type { AudioBridge } from '../audioBridge';
import type { PcmContextLike, ScriptProcessorLike } from '../../features/capture/pcmTap';

/**
 * Watching for the one failure the screen cannot otherwise show: silence.
 *
 * A recording that reads no samples looks exactly like one that is working.
 * The device is open, so the state word says Recording and stays there. The
 * level meter moves, because it polls an analyser of its own rather than
 * waiting for the graph to be pumped. Nothing throws, so no error is caught
 * and no note is written. The operator finds out after the meeting, from a
 * transcript that does not exist.
 *
 * That is not hypothetical: it is how a suspended `AudioContext` presented on
 * a real Mac, and it cost a full session of testing to find, because every
 * signal on the screen said the microphone was working. The uploader's own
 * failures already announce themselves; this is the absence of anything to
 * upload, which can only be noticed by waiting for it.
 */

function fakeContext() {
  let processor: ScriptProcessorLike | null = null;
  const node = () => ({ connect() {}, disconnect() {} });

  const context: PcmContextLike = {
    sampleRate: 16_000,
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
    emit(samples: Float32Array) {
      processor?.onaudioprocess?.({ inputBuffer: { getChannelData: () => samples } });
    },
  };
}

function fakeBridge(): AudioBridge {
  return {
    start: vi.fn(async () => {}),
    push: vi.fn(),
    stop: vi.fn(async () => {}),
    reportFailure: vi.fn(),
  } as unknown as AudioBridge;
}

function deps(overrides: Record<string, unknown> = {}) {
  const stream = {
    getAudioTracks: () => [
      { kind: 'audio', enabled: true, stop() {}, getSettings: () => ({ deviceId: 'mic-1' }) },
    ],
    getTracks: () => [{ kind: 'audio', enabled: true, stop() {} }],
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

describe('a recording that is reading no audio', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('says so, rather than looking like a working recording', async () => {
    const context = fakeContext();
    const store = createCaptureStore(
      deps({ pcmContext: () => () => context.context, createBridge: () => fakeBridge() }),
    );

    await store.refresh();
    await store.start('mic-1');
    // No samples emitted at all: the tap is open and the graph is not running.
    await vi.advanceTimersByTimeAsync(12_000);

    expect(store.getSnapshot().uploadNote).toMatch(/no audio/i);
  });

  it('stays quiet while samples are arriving', async () => {
    const context = fakeContext();
    const store = createCaptureStore(
      deps({ pcmContext: () => () => context.context, createBridge: () => fakeBridge() }),
    );

    await store.refresh();
    await store.start('mic-1');
    for (let tick = 0; tick < 12; tick += 1) {
      context.emit(new Float32Array(320).fill(0.2));
      await vi.advanceTimersByTimeAsync(1_000);
    }

    expect(store.getSnapshot().uploadNote).toBeNull();
  });

  it('takes the warning back down when audio starts arriving again', async () => {
    // A microphone that comes back deserves a screen that comes back with it:
    // a warning left standing over a recording that is now uploading is the
    // same lie in the other direction.
    const context = fakeContext();
    const store = createCaptureStore(
      deps({ pcmContext: () => () => context.context, createBridge: () => fakeBridge() }),
    );

    await store.refresh();
    await store.start('mic-1');
    await vi.advanceTimersByTimeAsync(12_000);
    expect(store.getSnapshot().uploadNote).toMatch(/no audio/i);

    context.emit(new Float32Array(320).fill(0.2));
    await vi.advanceTimersByTimeAsync(6_000);

    expect(store.getSnapshot().uploadNote).toBeNull();
  });

  it('stops watching once the recording has stopped', async () => {
    // Otherwise every stopped recording raises the alarm a few seconds later,
    // and a warning that always fires is one nobody reads.
    const context = fakeContext();
    const store = createCaptureStore(
      deps({ pcmContext: () => () => context.context, createBridge: () => fakeBridge() }),
    );

    await store.refresh();
    await store.start('mic-1');
    await store.stop();
    await vi.advanceTimersByTimeAsync(20_000);

    expect(store.getSnapshot().uploadNote).toBeNull();
  });

  it('starts watching again when the recording resumes', async () => {
    // The other half of pausing the watch. A microphone that dies during a
    // pause is the same silent failure as one that dies during a recording,
    // and a watch that is never restarted is a watch that has been removed.
    const context = fakeContext();
    const store = createCaptureStore(
      deps({ pcmContext: () => () => context.context, createBridge: () => fakeBridge() }),
    );

    await store.refresh();
    await store.start('mic-1');
    context.emit(new Float32Array(320).fill(0.2));
    await store.pause();
    await vi.advanceTimersByTimeAsync(20_000);
    expect(store.getSnapshot().uploadNote).toBeNull();

    await store.resume();
    await vi.advanceTimersByTimeAsync(12_000);

    expect(store.getSnapshot().uploadNote).toMatch(/no audio/i);
  });
});

describe('the same watch on the desktop shell', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('warns when Rust is emitting no audio either', async () => {
    // The shell can fail this way too — a backend that opens a device and
    // then emits nothing leaves the same screen saying the same Recording.
    // The cause differs; what the operator needs told does not.
    const store = createCaptureStore(
      deps({
        shellAvailable: () => true,
        invoke: async (command: string) => {
          if (command === 'list_sources') {
            return [{ id: 'mic-1', label: 'Desk microphone', kind: 'microphone' }];
          }
          // Idle until asked to start: a shell reporting `capturing` at rest
          // makes `openDevice` refuse, which is the store protecting itself
          // rather than anything this test means to exercise.
          return command === 'start_capture'
            ? { state: 'capturing', sourceId: 'mic-1', elapsedMs: 0 }
            : { state: 'idle', sourceId: null, elapsedMs: 0 };
        },
        listen: async () => () => undefined,
        createBridge: () => fakeBridge(),
      }),
    );

    await store.refresh();
    await store.start('mic-1');
    await vi.advanceTimersByTimeAsync(12_000);

    expect(store.getSnapshot().uploadNote).toMatch(/no audio/i);
  });
});

describe('the warning and the recording it is about', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('takes the warning down when the recording stops', async () => {
    /* Reported: "i have already stopped the recording. why does UI show The
       microphone is open but no audio is being read from it".

       Because it did, and then stopped. `stop()` publishes `IDLE` and clears
       nothing else, so a note raised mid-recording outlived the recording it
       describes — in the present tense, about a microphone that is shut.

       The test above it does stop a recording, and passes against this: it
       stops before the five seconds are up, so there is no warning standing
       when `stop` runs and nothing for `stop` to fail to clear. */
    const context = fakeContext();
    const store = createCaptureStore(
      deps({ pcmContext: () => () => context.context, createBridge: () => fakeBridge() }),
    );

    await store.refresh();
    await store.start('mic-1');
    await vi.advanceTimersByTimeAsync(12_000);
    expect(store.getSnapshot().uploadNote).toMatch(/no audio/i);

    await store.stop();

    expect(store.getSnapshot().uploadNote).toBeNull();
  });

  it('does not raise it over a recording the operator paused', async () => {
    /* The shell drops paused frames in Rust before it emits them, so a paused
       recording delivers nothing to count -- and the watch counts *after* the
       feeding gate on that path, which the browser path deliberately does not
       (see the comment on its own `sawSamples` call). Five seconds into a
       pause the operator was told their microphone was delivering nothing,
       which is true, is the state they asked for, and reads as a fault. */
    const bridge = fakeBridge();
    const listeners: Record<string, (event: { payload: unknown }) => void> = {};
    const store = createCaptureStore(
      deps({
        shellAvailable: () => true,
        environment: () => ({ isSecureContext: true, mediaDevices: undefined }),
        pcmContext: () => null,
        createBridge: () => bridge,
        invoke: (async (command: string) => {
          if (command === 'list_audio_sources') return [];
          if (command === 'capture_status') return null;
          if (command === 'pause_capture') return { state: 'paused', source: null, frames: 0 };
          return { state: 'capturing', source: null, frames: 0 };
        }) as never,
        listen: async (name: string, handler: (event: { payload: unknown }) => void) => {
          listeners[name] = handler;
          return () => {};
        },
      }),
    );

    await store.refresh();
    await store.start('line-in');
    // Audio is flowing, so nothing is wrong.
    listeners['capture://pcm']?.({ payload: { pcm: 'AAAA' } });
    await vi.advanceTimersByTimeAsync(6_000);
    expect(store.getSnapshot().uploadNote).toBeNull();

    await store.pause();
    // Rust emits nothing at all while paused.
    await vi.advanceTimersByTimeAsync(20_000);

    expect(store.getSnapshot().uploadNote).toBeNull();
  });

  it('starts watching again when the recording resumes', async () => {
    // The other half of pausing the watch. A microphone that dies during a
    // pause is the same silent failure as one that dies during a recording,
    // and a watch that is never restarted is a watch that has been removed.
    const context = fakeContext();
    const store = createCaptureStore(
      deps({ pcmContext: () => () => context.context, createBridge: () => fakeBridge() }),
    );

    await store.refresh();
    await store.start('mic-1');
    context.emit(new Float32Array(320).fill(0.2));
    await store.pause();
    await vi.advanceTimersByTimeAsync(20_000);
    expect(store.getSnapshot().uploadNote).toBeNull();

    await store.resume();
    await vi.advanceTimersByTimeAsync(12_000);

    expect(store.getSnapshot().uploadNote).toMatch(/no audio/i);
  });
});
