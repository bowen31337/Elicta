/**
 * Reading how loud the open microphone actually is.
 *
 * The capture screen could say "Recording" for forty minutes over a muted
 * input and look exactly the same as one that was working. A level meter is
 * the only thing on that screen that distinguishes them, which makes it a
 * safety feature of the same family as the pause banner rather than a
 * decoration: it is the operator's evidence that sound is arriving.
 *
 * **It measures one mixed stream, and cannot do otherwise.** `getUserMedia`
 * opens a single device and the shell's session holds a single source, so
 * what this reads is the room, not the people in it. Speaker attribution
 * exists in this product, but it happens on finalised transcript utterances —
 * seconds behind, and only ever "the operator or not" — which cannot drive a
 * meter. A bar per participant would be a drawn number with nothing behind
 * it, so the screen shows one bar and says which device it belongs to.
 *
 * Written over injected `AudioContext`-shaped objects rather than reaching for
 * the global, exactly like `browserCapture` is written over `MediaDevicesLike`
 * — so every branch here is testable with no browser and no microphone.
 */

/** The analyser calls this module makes. */
export interface AnalyserLike {
  fftSize: number;
  getByteTimeDomainData(into: Uint8Array): void;
}

interface SourceLike {
  connect(node: AnalyserLike): void;
  disconnect(): void;
}

/** The `AudioContext` surface this module needs, and no more of it. */
export interface AudioContextLike {
  createAnalyser(): AnalyserLike;
  createMediaStreamSource(stream: never): SourceLike;
  close(): Promise<unknown>;
}

/** How loud one analyser frame was. */
export interface AudioLevel {
  /** Root-mean-square amplitude, 0..1 — what the ear reads as loudness. */
  readonly rms: number;
  /** Largest single sample in the frame, 0..1 — what clipping shows up in. */
  readonly peak: number;
}

export const SILENCE: AudioLevel = { rms: 0, peak: 0 };

/**
 * The floor of the meter, in dBFS.
 *
 * Below this is room tone and electrical noise, and stretching the scale down
 * to it would leave a silent room drawing a visible bar — which is the one
 * reading this meter exists to make unmistakable.
 */
const FLOOR_DB = -60;

/**
 * How loud one frame of byte time-domain data was.
 *
 * The centring is the part worth stating: a browser writes silence as **128**,
 * not as zero, so the amplitude of a sample is its distance from 128. Reading
 * the byte directly parks a silent room at half scale, which looks like a
 * working meter in a noisy office and is why this has a test of its own.
 */
export function levelOfFrame(frame: Uint8Array): AudioLevel {
  if (frame.length === 0) return SILENCE;

  let sumOfSquares = 0;
  let peak = 0;
  for (const sample of frame) {
    const amplitude = Math.abs(sample - 128) / 127;
    sumOfSquares += amplitude * amplitude;
    if (amplitude > peak) peak = amplitude;
  }
  return {
    rms: Math.min(1, Math.sqrt(sumOfSquares / frame.length)),
    peak: Math.min(1, peak),
  };
}

/**
 * The dBFS readout for an amplitude, or `null` for digital silence.
 *
 * `null` rather than `-Infinity` because the difference is what the screen
 * renders: a number gets drawn, and "-Infinity dB" is not a thing to put in
 * front of an operator. The screen shows a dash instead.
 */
export function decibels(amplitude: number): number | null {
  if (amplitude <= 0) return null;
  return 20 * Math.log10(Math.min(1, amplitude));
}

/**
 * Where the bar sits, 0..1.
 *
 * Deliberately a decibel scale rather than the raw amplitude. Speech peaks
 * around 0.05 linear, so a linear bar spends the whole meeting in its first
 * twentieth and tells the operator nothing — the same reading on this scale is
 * over half way, and moves with the talking.
 */
export function meterPosition(amplitude: number): number {
  const db = decibels(amplitude);
  if (db === null) return 0;
  if (db <= FLOOR_DB) return 0;
  return Math.min(1, (db - FLOOR_DB) / -FLOOR_DB);
}

/**
 * The scrolling wave: newest reading last, oldest dropped once full.
 *
 * Returned as a new array rather than mutated, because it is React state and
 * a mutated array would not re-render.
 */
export function pushHistory(
  history: readonly number[],
  value: number,
  capacity: number,
): number[] {
  const next = [...history, value];
  return next.length > capacity ? next.slice(next.length - capacity) : next;
}

/** An open analyser on a live stream. */
export interface LevelReader {
  read(): AudioLevel;
  close(): void;
}

/**
 * Taps a live stream for its level.
 *
 * `close` is idempotent and a read afterwards returns silence rather than
 * throwing: the meter is driven by a timer, so a stop that lands between a
 * tick being scheduled and running is ordinary rather than exceptional, and
 * an exception there would take the capture screen down at the exact moment
 * the operator pressed Stop.
 */
export function openLevelReader(context: AudioContextLike, stream: unknown): LevelReader {
  const analyser = context.createAnalyser();
  // 2048 samples is ~46ms at 44.1kHz: long enough that the RMS is steady
  // rather than flickering on individual glottal pulses, short enough that
  // the bar still reacts within a syllable.
  analyser.fftSize = 2048;
  const source = context.createMediaStreamSource(stream as never);
  source.connect(analyser);

  const buffer = new Uint8Array(analyser.fftSize);
  let open = true;

  return {
    read: () => {
      if (!open) return SILENCE;
      analyser.getByteTimeDomainData(buffer);
      return levelOfFrame(buffer);
    },
    close: () => {
      if (!open) return;
      open = false;
      source.disconnect();
      // The context holds an audio device open on some platforms, so leaving
      // it running would keep the browser's recording indicator lit after the
      // operator stopped -- the same lie `browserCapture.stop` exists to avoid.
      void context.close();
    },
  };
}

/**
 * A factory for the page's own `AudioContext`, or `null` where there is none.
 *
 * `null` is a real answer, not a failure: jsdom has no Web Audio, and neither
 * does every engine this bundle can be opened in. Recording must not depend on
 * metering being possible, so the caller degrades to no meter rather than to a
 * meter stuck at zero -- which would read as a silent room.
 */
export function currentAudioContextFactory(): (() => AudioContextLike) | null {
  if (typeof window === 'undefined') return null;
  const Ctor = (window as unknown as { AudioContext?: new () => AudioContextLike })
    .AudioContext;
  if (Ctor === undefined) return null;
  return () => new Ctor();
}
