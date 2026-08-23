import { describe, expect, it } from 'vitest';

import {
  base64OfInt16,
  createResampler,
  int16OfBase64,
  toInt16,
  TARGET_SAMPLE_RATE,
} from '../pcm';

/**
 * Turning what a browser gives us into what the service accepts.
 *
 * `POST /api/sessions/{id}/audio-chunk` wants base64 linear16 at 16kHz mono,
 * and a browser hands out 32-bit floats at whatever rate its `AudioContext`
 * chose — 48kHz on every machine seen so far. Everything in this module is the
 * arithmetic between those two facts, kept pure so it is testable with no
 * browser, no device and no service.
 */

describe('createResampler', () => {
  it('passes a frame through untouched when the input is already 16kHz', () => {
    const resampler = createResampler(TARGET_SAMPLE_RATE);
    const frame = Float32Array.from([0.25, -0.5, 0.75]);

    expect([...resampler.push(frame)]).toEqual([0.25, -0.5, 0.75]);
  });

  it('produces one sample per three at 48kHz', () => {
    const resampler = createResampler(48_000);

    expect(resampler.push(new Float32Array(48)).length).toBe(16);
  });

  it('averages each window rather than dropping samples, so a steady tone keeps its level', () => {
    const resampler = createResampler(48_000);
    const steady = new Float32Array(48).fill(0.5);

    for (const sample of resampler.push(steady)) {
      expect(sample).toBeCloseTo(0.5, 6);
    }
  });

  it('carries the remainder across frames, so a long recording does not drift short', () => {
    const resampler = createResampler(48_000);

    // 25 + 23 input samples is 48, which is 16 output samples. Resampling each
    // frame independently would floor to 8 and 7 and quietly lose one sample
    // per frame — a hundred frames a second, for the length of a meeting.
    const first = resampler.push(new Float32Array(25));
    const second = resampler.push(new Float32Array(23));

    expect(first.length + second.length).toBe(16);
  });
});

describe('toInt16', () => {
  it('scales full-scale floats to the ends of the 16-bit range', () => {
    expect([...toInt16(Float32Array.from([0, 1, -1]))]).toEqual([0, 32767, -32768]);
  });

  it('clamps rather than wrapping, so a clipped sample stays loud instead of inverting', () => {
    expect([...toInt16(Float32Array.from([1.5, -1.5]))]).toEqual([32767, -32768]);
  });
});

describe('base64OfInt16', () => {
  it('encodes little-endian, which is what linear16 means on the wire', () => {
    expect(base64OfInt16(Int16Array.from([1]))).toBe('AQA=');
    expect(base64OfInt16(Int16Array.from([-2]))).toBe('/v8=');
  });

  it('encodes a chunk far larger than an argument list without failing', () => {
    // The obvious `String.fromCharCode(...bytes)` overflows the call stack
    // somewhere around 100k arguments, and a five-second chunk is 160,000
    // bytes — so the failure would arrive in the first real meeting.
    const chunk = new Int16Array(80_000);

    expect(base64OfInt16(chunk).length).toBeGreaterThan(200_000);
  });
});

describe('int16OfBase64', () => {
  it('reads back what the desktop shell encodes', () => {
    // The shell emits `capture://pcm` as base64 little-endian linear16, from
    // its own hand-written encoder in `capture.rs`. These two literals are the
    // contract between the two languages, asserted on both sides.
    expect([...int16OfBase64('AQA=')]).toEqual([1]);
    expect([...int16OfBase64('AQD+/w==')]).toEqual([1, -2]);
  });

  it('round-trips whatever the browser encodes', () => {
    const samples = Int16Array.from([0, 32767, -32768, 1234, -1234]);

    expect([...int16OfBase64(base64OfInt16(samples))]).toEqual([...samples]);
  });

  it('reads nothing from an empty payload', () => {
    expect(int16OfBase64('').length).toBe(0);
  });
});
