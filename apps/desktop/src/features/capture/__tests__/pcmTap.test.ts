import { describe, expect, it } from 'vitest';

import { openPcmTap, type PcmContextLike, type ScriptProcessorLike } from '../pcmTap';

/**
 * Reading the actual samples off an open microphone, in a browser.
 *
 * The level meter next door taps the same stream through an `AnalyserNode`,
 * which yields byte *magnitudes* — enough to draw a bar, and impossible to
 * reconstruct audio from. This is the second tap, and the only place in the
 * web build where a recording exists as audio rather than as a picture of one.
 *
 * Written over an injected `AudioContext`-shaped object, exactly like
 * `levelMeter` and `browserCapture`, so every branch is reachable with no
 * browser, no Web Audio and no microphone.
 */

/**
 * A node whose state is read back after the fact.
 *
 * Deliberately not built by spreading a shared factory: `{ ...node() }` copies
 * a getter's *value* at spread time, so `disconnected` would stay false
 * however many times the tap disconnected it — and the test would pass on an
 * implementation that leaks the audio graph.
 */
function node() {
  return {
    connectedTo: [] as unknown[],
    disconnected: false,
    connect(to: unknown) {
      this.connectedTo.push(to);
    },
    disconnect() {
      this.disconnected = true;
    },
  };
}

function fakeContext(sampleRate: number) {
  const source = node();
  const gain = Object.assign(node(), { gain: { value: 1 } });
  let processor: (ScriptProcessorLike & { disconnected: boolean }) | null = null;
  let closed = false;

  const context: PcmContextLike = {
    sampleRate,
    destination: { name: 'speakers' },
    createMediaStreamSource: () => source,
    createScriptProcessor: () => {
      processor = Object.assign(node(), {
        onaudioprocess: null as ScriptProcessorLike['onaudioprocess'],
      });
      return processor;
    },
    createGain: () => gain,
    close: async () => {
      closed = true;
    },
  };

  return {
    context,
    source,
    gain,
    get processor() {
      return processor;
    },
    get closed() {
      return closed;
    },
    /** What the browser does when a buffer of input is ready. */
    emit(samples: Float32Array) {
      processor?.onaudioprocess?.({
        inputBuffer: { getChannelData: () => samples },
      });
    },
  };
}

describe('openPcmTap', () => {
  it('hands out 16kHz signed samples from a 48kHz context', () => {
    const fake = fakeContext(48_000);
    const received: Int16Array[] = [];
    openPcmTap(fake.context, {}, (samples) => received.push(samples));

    fake.emit(new Float32Array(48).fill(1));

    expect(received).toHaveLength(1);
    expect(received[0].length).toBe(16);
    expect([...received[0]]).toEqual(new Array(16).fill(32767));
  });

  it('passes samples through untouched when the context is already at 16kHz', () => {
    const fake = fakeContext(16_000);
    const received: Int16Array[] = [];
    openPcmTap(fake.context, {}, (samples) => received.push(samples));

    fake.emit(Float32Array.from([1, -1, 0]));

    expect([...received[0]]).toEqual([32767, -32768, 0]);
  });

  it('routes the tap through a silent gain, so the room is not played back at itself', () => {
    // A `ScriptProcessorNode` only runs while it is connected onward to the
    // destination, and connecting it straight there puts the microphone
    // through the laptop speakers — feedback, in a room being recorded.
    const fake = fakeContext(48_000);

    openPcmTap(fake.context, {}, () => {});

    expect(fake.gain.gain.value).toBe(0);
    expect(fake.gain.connectedTo).toContain(fake.context.destination);
  });

  it('releases the graph and the context when it closes', async () => {
    const fake = fakeContext(48_000);
    const tap = openPcmTap(fake.context, {}, () => {});

    tap.close();
    await Promise.resolve();

    expect(fake.source.disconnected).toBe(true);
    expect(fake.gain.disconnected).toBe(true);
    expect(fake.closed).toBe(true);
  });

  it('delivers nothing after it has closed', () => {
    const fake = fakeContext(48_000);
    const received: Int16Array[] = [];
    const tap = openPcmTap(fake.context, {}, (samples) => received.push(samples));

    tap.close();
    fake.emit(new Float32Array(48).fill(1));

    expect(received).toEqual([]);
  });
});
