/**
 * The arithmetic between what a browser hands out and what the service accepts.
 *
 * `POST /api/sessions/{id}/audio-chunk` takes base64 **linear16, 16kHz mono**
 * — the same format the desktop shell's `NormalizingPipeline` already produces
 * in Rust. A browser's `AudioContext` hands out 32-bit floats at whatever rate
 * it chose, which is 48kHz on every machine seen so far. This module is the
 * conversion between the two, and nothing else: no device, no network, no
 * `AudioContext`, so every branch is testable in a plain function call.
 */

/** What the record path is fed, everywhere. Matches `capture::ring::TARGET_SAMPLE_RATE`. */
export const TARGET_SAMPLE_RATE = 16_000;

export interface Resampler {
  /** The 16kHz samples this frame yielded. Empty until a whole one is due. */
  push(frame: Float32Array): Float32Array;
}

/**
 * Rate conversion down to 16kHz, with the remainder carried between frames.
 *
 * **The carry is the whole point.** Resampling each frame on its own means
 * flooring its length, which discards up to a window of audio *per frame* —
 * around a hundred frames a second, for the length of a meeting. The transcript
 * would come back sped up and clipped at every buffer boundary, which reads as
 * a bad engine rather than as arithmetic.
 *
 * Each output sample is the **mean** of the input window behind it rather than
 * one sample plucked from it. Decimation alone would fold everything above
 * 8kHz back down into the speech band as aliasing noise, which is a mess to
 * transcribe; averaging is a crude low-pass, cheap enough to run on the audio
 * thread and enough to keep that out.
 */
export function createResampler(inputRate: number): Resampler {
  const ratio = inputRate / TARGET_SAMPLE_RATE;
  let leftover = new Float32Array(0);
  /** Where the next window starts inside `leftover`, which a non-integer
   *  ratio (44.1kHz, say) leaves part-way through a sample. */
  let phase = 0;

  return {
    push(frame) {
      const buffer = new Float32Array(leftover.length + frame.length);
      buffer.set(leftover, 0);
      buffer.set(frame, leftover.length);

      const out: number[] = [];
      let start = phase;
      while (start + ratio <= buffer.length) {
        const end = start + ratio;
        let sum = 0;
        let count = 0;
        for (let i = Math.floor(start); i < Math.min(buffer.length, Math.ceil(end)); i += 1) {
          sum += buffer[i];
          count += 1;
        }
        out.push(count === 0 ? 0 : sum / count);
        start = end;
      }

      const consumed = Math.floor(start);
      leftover = buffer.slice(consumed);
      phase = start - consumed;
      return Float32Array.from(out);
    },
  };
}

/**
 * Floats in −1..1 as signed 16-bit samples.
 *
 * Clamped rather than allowed to wrap: a sample over full scale is a clipped
 * one, and wrapping turns the loudest moment of a sentence into a sign
 * inversion — a click the transcriber hears and the speaker never made.
 */
export function toInt16(samples: Float32Array): Int16Array {
  const out = new Int16Array(samples.length);
  for (let i = 0; i < samples.length; i += 1) {
    const clamped = Math.max(-1, Math.min(1, samples[i]));
    // Asymmetric on purpose: the negative side of the range is one larger.
    out[i] = Math.round(clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff);
  }
  return out;
}

/** How many bytes are turned into a binary string at a time — see below. */
const BASE64_STRIDE = 8192;

/**
 * Little-endian bytes, base64-encoded, which is what `pcm` means on the wire.
 *
 * The byte order is written out rather than taken from the `Int16Array`'s own
 * buffer, so this does not quietly depend on the machine being little-endian.
 * And the encoding runs in strides because `String.fromCharCode(...bytes)`
 * overflows the call stack somewhere around a hundred thousand arguments —
 * one five-second chunk is 160,000 bytes, so the naive version would fail in
 * the first real meeting rather than in a test.
 */
export function base64OfInt16(samples: Int16Array): string {
  const bytes = new Uint8Array(samples.length * 2);
  for (let i = 0; i < samples.length; i += 1) {
    const value = samples[i];
    bytes[i * 2] = value & 0xff;
    bytes[i * 2 + 1] = (value >> 8) & 0xff;
  }

  let binary = '';
  for (let offset = 0; offset < bytes.length; offset += BASE64_STRIDE) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + BASE64_STRIDE));
  }
  return btoa(binary);
}

/**
 * The other direction: what the desktop shell emits, as samples.
 *
 * The shell's `capture://pcm` carries the same base64 little-endian linear16
 * this module produces, encoded by a hand-written encoder in `capture.rs`. The
 * two are asserted against the same literals on both sides of the language
 * boundary, because nothing else checks that a Rust byte order and a
 * TypeScript one agree.
 */
export function int16OfBase64(pcm: string): Int16Array {
  if (pcm === '') return new Int16Array(0);
  const binary = atob(pcm);
  const samples = new Int16Array(binary.length >> 1);
  for (let i = 0; i < samples.length; i += 1) {
    const low = binary.charCodeAt(i * 2);
    const high = binary.charCodeAt(i * 2 + 1);
    // The sign has to be put back by hand: the bytes are unsigned, and
    // `(high << 8) | low` for 0xFFFE is 65534, not −2.
    const value = (high << 8) | low;
    samples[i] = value >= 0x8000 ? value - 0x10000 : value;
  }
  return samples;
}
