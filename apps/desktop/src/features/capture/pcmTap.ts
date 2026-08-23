import { createResampler, toInt16, TARGET_SAMPLE_RATE } from './pcm';

/**
 * The samples themselves, off an open microphone, in a browser.
 *
 * The level meter taps the same stream through an `AnalyserNode` and gets byte
 * magnitudes — enough to draw a bar, impossible to reconstruct audio from. So
 * a recording that has to reach the service needs a second tap, and this is
 * it: the only place in the web build where the meeting exists as audio rather
 * than as a picture of one. The desktop shell needs none of this; its Rust
 * pipeline already produces 16kHz mono `i16`.
 *
 * **A `ScriptProcessorNode`, deliberately, in 2026.** It is deprecated in
 * favour of `AudioWorklet`, which runs off the main thread and would be the
 * right answer for anything doing work per sample. This does no work per
 * sample — it copies a buffer and hands it on — and a worklet costs a separate
 * module file fetched at runtime, which is a second thing that can fail in a
 * meeting and cannot be injected in a test. When that trade changes, the seam
 * to swap is this file: `openPcmTap` is what the rest of the app knows about.
 *
 * Written over an injected `AudioContext`-shaped object for the same reason
 * `levelMeter` and `browserCapture` are.
 */

interface ConnectableNode {
  connect(to: unknown): void;
  disconnect(): void;
}

export interface AudioProcessEvent {
  readonly inputBuffer: { getChannelData(channel: number): Float32Array };
}

export interface ScriptProcessorLike extends ConnectableNode {
  onaudioprocess: ((event: AudioProcessEvent) => void) | null;
}

export interface GainLike extends ConnectableNode {
  readonly gain: { value: number };
}

/** The `AudioContext` surface this module needs, and no more of it. */
export interface PcmContextLike {
  readonly sampleRate: number;
  readonly destination: unknown;
  /**
   * `"suspended"` until the browser is satisfied the user asked for this.
   * Optional because it is only read to decide whether to `resume`, and a
   * context that cannot say is treated as one that does not need it.
   */
  readonly state?: string;
  resume?(): Promise<unknown>;
  createMediaStreamSource(stream: never): ConnectableNode;
  createScriptProcessor(
    bufferSize: number,
    inputChannels: number,
    outputChannels: number,
  ): ScriptProcessorLike;
  createGain(): GainLike;
  close(): Promise<unknown>;
}

export interface PcmTap {
  /** Releases the graph and the context. Idempotent. */
  close(): void;
}

/**
 * How many samples a buffer carries: about 85ms at 48kHz.
 *
 * Small enough that stopping mid-sentence loses a fraction of a word, large
 * enough that the main thread is interrupted twelve times a second rather than
 * two hundred.
 */
const BUFFER_SAMPLES = 4096;

export function openPcmTap(
  context: PcmContextLike,
  stream: unknown,
  onSamples: (samples: Int16Array) => void,
): PcmTap {
  const resampler = createResampler(context.sampleRate);
  const source = context.createMediaStreamSource(stream as never);
  const processor = context.createScriptProcessor(BUFFER_SAMPLES, 1, 1);
  // A `ScriptProcessorNode` is only pumped while it is connected onward to the
  // destination — and connecting it straight there puts the microphone through
  // the speakers, which is feedback in a room that is being recorded. The
  // silent gain keeps the graph alive and the room quiet.
  const silence = context.createGain();
  silence.gain.value = 0;

  // Chrome starts a context suspended unless it was constructed inside a user
  // gesture, and this one never is: the tap opens after the device has been
  // checked, after the session has been booked and after the consent gate has
  // answered — three awaits and two network round trips past the click.
  //
  // A suspended context does not pump the graph, so `onaudioprocess` never
  // fires. Nothing throws, so nothing is caught and nothing is reported: the
  // screen says Recording, the level meter moves — it polls an analyser of its
  // own rather than waiting to be pumped, on a context opened during the
  // gesture — and not one byte of the meeting is uploaded.
  //
  // Resuming needs only *sticky* activation, which the click that started the
  // recording already granted. Not awaited: the graph below is connected
  // either way, and the samples start when the context does.
  if (context.state === "suspended") void context.resume?.();

  let open = true;

  processor.onaudioprocess = (event) => {
    if (!open) return;
    // Channel 0 only: `getUserMedia` is asked for one channel, and a browser
    // that hands back two would have mixed them to mono already.
    const frame = event.inputBuffer.getChannelData(0);
    const resampled =
      context.sampleRate === TARGET_SAMPLE_RATE ? frame : resampler.push(frame);
    if (resampled.length === 0) return;
    onSamples(toInt16(resampled));
  };

  source.connect(processor);
  processor.connect(silence);
  silence.connect(context.destination);

  return {
    close() {
      if (!open) return;
      open = false;
      processor.onaudioprocess = null;
      source.disconnect();
      processor.disconnect();
      silence.disconnect();
      // The context holds a device open on some platforms, which keeps the
      // browser's recording indicator lit after the operator stopped — the
      // same lie `levelMeter.close` exists to avoid.
      void context.close();
    },
  };
}

/**
 * A factory for a 16kHz `AudioContext`, or `null` where there is no Web Audio.
 *
 * The rate is *asked for* rather than assumed: Chrome, Firefox and Safari will
 * open a context at 16kHz, which means the browser's own resampler does the
 * work and `createResampler` never runs. Where the request is refused the
 * context comes back at the hardware rate and the fallback in `pcm.ts` takes
 * over — so this is an optimisation, never a correctness condition.
 */
export function currentPcmContextFactory(): (() => PcmContextLike) | null {
  if (typeof window === 'undefined') return null;
  const Ctor = (window as unknown as {
    AudioContext?: new (options?: { sampleRate?: number }) => PcmContextLike;
    webkitAudioContext?: new (options?: { sampleRate?: number }) => PcmContextLike;
  });
  const AudioCtor = Ctor.AudioContext ?? Ctor.webkitAudioContext;
  if (AudioCtor === undefined) return null;
  return () => {
    try {
      return new AudioCtor({ sampleRate: TARGET_SAMPLE_RATE });
    } catch {
      return new AudioCtor();
    }
  };
}
