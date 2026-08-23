import { describe, expect, it } from 'vitest';

import {
  decibels,
  levelOfFrame,
  meterPosition,
  openLevelReader,
  pushHistory,
  SILENCE,
  type AnalyserLike,
  type AudioContextLike,
} from '../levelMeter';

/** A frame of byte time-domain data, which a browser centres on 128. */
function frame(...samples: number[]): Uint8Array {
  return Uint8Array.from(samples);
}

describe('levelOfFrame', () => {
  it('reads a silent frame as zero, not as half scale', () => {
    // The trap this guards: `getByteTimeDomainData` writes silence as 128, so
    // treating the byte as the amplitude pins a quiet room at 50% and the
    // meter never looks wrong enough to investigate.
    expect(levelOfFrame(frame(128, 128, 128, 128))).toEqual({ rms: 0, peak: 0 });
  });

  it('reads a full-scale square wave as one', () => {
    expect(levelOfFrame(frame(255, 1, 255, 1))).toEqual({ rms: 1, peak: 1 });
  });

  it('reports peak above rms for a signal that is mostly quiet', () => {
    const level = levelOfFrame(frame(128, 128, 128, 255));

    expect(level.peak).toBe(1);
    expect(level.rms).toBeCloseTo(0.5, 5);
  });
});

describe('decibels', () => {
  it('reads full scale as zero', () => {
    expect(decibels(1)).toBeCloseTo(0, 5);
  });

  it('reads half amplitude as about six decibels down', () => {
    expect(decibels(0.5)).toBeCloseTo(-6.02, 1);
  });

  it('has no reading for digital silence, rather than reporting minus infinity', () => {
    // A number would be rendered; `null` is what lets the screen show a dash.
    expect(decibels(0)).toBeNull();
  });
});

describe('meterPosition', () => {
  it('puts silence at the left end', () => {
    expect(meterPosition(0)).toBe(0);
  });

  it('puts full scale at the right end', () => {
    expect(meterPosition(1)).toBe(1);
  });

  it('places the bar on a decibel scale, not a linear one', () => {
    // Speech sits near 0.05 linear. On a linear bar that is a 5% twitch; on
    // the -60..0 dB scale it is a bar that visibly tracks the talking.
    expect(meterPosition(0.05)).toBeGreaterThan(0.5);
  });

  it('holds the floor at sixty decibels down rather than going negative', () => {
    expect(meterPosition(0.0001)).toBe(0);
  });
});

describe('pushHistory', () => {
  it('appends the newest reading at the end, so the wave scrolls left', () => {
    expect(pushHistory([0.1, 0.2], 0.3, 4)).toEqual([0.1, 0.2, 0.3]);
  });

  it('drops the oldest reading once it is full', () => {
    expect(pushHistory([0.1, 0.2, 0.3], 0.4, 3)).toEqual([0.2, 0.3, 0.4]);
  });
});

describe('openLevelReader', () => {
  /** An analyser that replays frames a test hands it. */
  function analyser(...frames: Uint8Array[]): AnalyserLike & { disconnected: boolean } {
    let next = 0;
    return {
      fftSize: 0,
      disconnected: false,
      getByteTimeDomainData(into: Uint8Array) {
        into.set(frames[Math.min(next++, frames.length - 1)]);
      },
    };
  }

  function context(node: AnalyserLike) {
    const closed = { context: false, source: false };
    return {
      closed,
      ctx: {
        createAnalyser: () => node,
        createMediaStreamSource: () => ({
          connect: () => undefined,
          disconnect: () => {
            closed.source = true;
          },
        }),
        close: async () => {
          closed.context = true;
        },
      } satisfies AudioContextLike,
    };
  }

  it('reads the live level off the stream', () => {
    const node = analyser(frame(255, 1, 255, 1));
    const reader = openLevelReader(context(node).ctx, {});

    expect(reader.read()).toEqual({ rms: 1, peak: 1 });
  });

  it('releases the audio graph when closed, so a stopped meter costs nothing', () => {
    const node = analyser(frame(128, 128));
    const { ctx, closed } = context(node);

    openLevelReader(ctx, {}).close();

    expect(closed.source).toBe(true);
    expect(closed.context).toBe(true);
  });

  it('reads silence after it is closed rather than throwing at a caller mid-frame', () => {
    // The meter is sampled on a timer. A close that raced the tick used to be
    // an unhandled rejection during teardown of the whole capture screen.
    const reader = openLevelReader(context(analyser(frame(255, 1))).ctx, {});

    reader.close();

    expect(reader.read()).toEqual(SILENCE);
  });
});
