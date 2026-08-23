import { describe, expect, it, vi } from 'vitest';

import { openPcmTap, type PcmContextLike } from '../pcmTap';

/**
 * A context that will not run reads no samples, and says nothing about it.
 *
 * Chrome starts an `AudioContext` suspended when it is constructed outside a
 * user gesture, and this one is: the tap is opened after the device has been
 * checked, after the session has been booked and after the consent gate has
 * answered — three awaits and two network round trips past the click that
 * began the recording.
 *
 * A `ScriptProcessorNode` on a suspended context never fires. Nothing throws,
 * so nothing is caught and nothing is reported: the screen says Recording, the
 * level meter moves (it polls its own analyser rather than waiting to be
 * pumped), and not one byte of the meeting is uploaded. That is the shape this
 * failed in on a real Mac, where every automated test here had passed —
 * because a headless browser does not enforce the policy at all.
 */
function fakeContext(state: string, resume: () => Promise<void>): PcmContextLike {
  const node = { connect: vi.fn(), disconnect: vi.fn() };
  return {
    sampleRate: 16_000,
    destination: {},
    state,
    resume,
    createMediaStreamSource: () => ({ ...node }),
    createScriptProcessor: () => ({ ...node, onaudioprocess: null }),
    createGain: () => ({ ...node, gain: { value: 1 } }),
    close: () => Promise.resolve(),
  } as unknown as PcmContextLike;
}

describe('opening the tap on a context the browser has suspended', () => {
  it('resumes it, because a suspended context reads no samples', () => {
    const resume = vi.fn(() => Promise.resolve());

    openPcmTap(fakeContext('suspended', resume), {}, () => undefined);

    expect(resume).toHaveBeenCalled();
  });

  it('leaves a running context alone', () => {
    const resume = vi.fn(() => Promise.resolve());

    openPcmTap(fakeContext('running', resume), {}, () => undefined);

    expect(resume).not.toHaveBeenCalled();
  });

  it('opens the tap even where the context cannot say whether it is suspended', () => {
    // `PcmContextLike` is deliberately the narrowest surface this module
    // needs, and the tests elsewhere supply fakes without `state` at all. A
    // tap that required it would break on every one of them, and on any
    // browser whose context does not report it.
    const node = { connect: vi.fn(), disconnect: vi.fn() };
    const bare = {
      sampleRate: 16_000,
      destination: {},
      createMediaStreamSource: () => ({ ...node }),
      createScriptProcessor: () => ({ ...node, onaudioprocess: null }),
      createGain: () => ({ ...node, gain: { value: 1 } }),
      close: () => Promise.resolve(),
    } as unknown as PcmContextLike;

    expect(() => openPcmTap(bare, {}, () => undefined)).not.toThrow();
  });
});
