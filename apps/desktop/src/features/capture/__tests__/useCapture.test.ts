import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

/**
 * The shell's event channel. Held as a module mock rather than a global stub
 * because the hook reaches it through a dynamic `import`, which is the only
 * way the same bundle can run in a browser with no Tauri to import from.
 */
const shellEvents: { emit?: (payload: unknown) => void } = {};
vi.mock('@tauri-apps/api/event', () => ({
  listen: vi.fn(async (name: string, handler: (event: { payload: unknown }) => void) => {
    if (name === 'capture://frame') {
      shellEvents.emit = (payload) => handler({ payload });
    }
    return () => undefined;
  }),
}));
vi.mock('@tauri-apps/api/core', () => ({ invoke: vi.fn(async () => null) }));

import { createCaptureStore } from '../../../services/captureSession';
import { shellAvailable, useCapture } from '../useCapture';

/**
 * One session per test, rather than the one the application runs.
 *
 * The session moved out of this hook and into `services/captureSession`, so
 * that the consent screen can open a device the capture screen then displays.
 * A module singleton would carry a live session — and the environment it read
 * at construction — from one test into the next.
 */
function renderCapture() {
  const store = createCaptureStore();
  return renderHook(() => useCapture(store));
}

/**
 * The hook's job outside the desktop shell is to be harmless.
 *
 * Every one of these components also renders in a plain browser — the
 * screenshot harness and the accessibility audit both do — where there is no
 * Tauri to invoke. A hook that threw there would take down the screens whose
 * appearance those tools exist to check, and the failure would look like a
 * design regression rather than a missing shell.
 */

afterEach(() => {
  delete (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__;
  vi.restoreAllMocks();
  // `restoreAllMocks` does not undo `stubGlobal`, so without this a test that
  // stubs `AudioContext` leaves it standing for every test after it -- and the
  // one case that matters, a browser with no Web Audio at all, can then never
  // be reached.
  vi.unstubAllGlobals();
});

describe('outside the desktop shell', () => {
  it('reports the shell as unavailable rather than guessing', () => {
    expect(shellAvailable()).toBe(false);
    const { result } = renderCapture();
    expect(result.current.available).toBe(false);
  });

  it('settles into idle with no sources instead of throwing', async () => {
    const { result } = renderCapture();

    await waitFor(() => expect(result.current.status.state).toBe('idle'));
    expect(result.current.sources).toEqual([]);
    expect(result.current.status.source).toBeNull();
  });

  it('leaves the controls callable and inert', async () => {
    const { result } = renderCapture();

    // Not "does not throw" as an incidental fact — a screen that renders a
    // pause button has to survive that button being pressed.
    await expect(result.current.pause()).resolves.toBeUndefined();
    await expect(result.current.resume()).resolves.toBeUndefined();
    await expect(result.current.start('line-in')).resolves.toBeUndefined();
    await expect(result.current.stop()).resolves.toBeUndefined();
    expect(result.current.status.state).toBe('idle');
  });
});

describe('inside the desktop shell', () => {
  it('detects the shell', () => {
    (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__ = {};
    expect(shellAvailable()).toBe(true);
    const { result } = renderCapture();
    expect(result.current.available).toBe(true);
  });
});

describe('a browser with no microphone attached', () => {
  /**
   * The pure check is unit-tested next door; this is the wiring, which is the
   * half that was missing. The count has to reach the check from the same
   * enumeration that fills the source list, or the screen keeps showing a dead
   * button beside an empty list exactly as a live run photographed it.
   */
  it('reports the reason once the enumeration has come back empty', async () => {
    vi.stubGlobal('isSecureContext', true);
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { enumerateDevices: async () => [], getUserMedia: async () => ({}) },
    });

    const { result } = renderCapture();

    await waitFor(() => expect(result.current.blockedReason).toMatch(/no microphone/i));
  });

  it('says nothing about microphones before the browser has been asked', () => {
    vi.stubGlobal('isSecureContext', true);
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { enumerateDevices: () => new Promise(() => {}), getUserMedia: async () => ({}) },
    });

    const { result } = renderCapture();

    expect(result.current.blockedReason).toBeNull();
  });
});

describe('a browser that has not yet been given permission', () => {
  /**
   * The end of the chain a live run walked into. Before the prompt a browser
   * hands back one blank placeholder per device kind — the `deviceId` is
   * withheld along with the label — so the list the screen renders at mount
   * is a device with no name and no id. Opening that id with `exact` can only
   * ever fail, and nothing here asked for permission any other way, so the id
   * never became real and every recording failed identically.
   *
   * The prompt belongs on the click, not on the mount: "Start recording" is
   * when the operator expects to be asked, and a granted prompt is what turns
   * the placeholder into a named device for every attempt after it.
   */
  it('records from the default microphone rather than failing on a withheld id', async () => {
    vi.stubGlobal('isSecureContext', true);
    let granted = false;
    const track = { kind: 'audio', enabled: true, stop() {} };

    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: {
        enumerateDevices: async () => [
          granted
            ? { kind: 'audioinput', deviceId: 'mic-1', label: 'Scarlett Solo USB' }
            : { kind: 'audioinput', deviceId: '', label: '' },
        ],
        getUserMedia: async (constraints: unknown) => {
          const audio = (constraints as { audio?: { deviceId?: { exact?: string } } }).audio;
          const exact = audio?.deviceId?.exact;
          if (exact !== undefined && exact !== 'mic-1') {
            // Verbatim what Chrome answered on the live page.
            throw Object.assign(new Error('Requested device not found'), {
              name: 'NotFoundError',
            });
          }
          granted = true;
          return { getAudioTracks: () => [track], getTracks: () => [track] };
        },
      },
    });

    const { result } = renderCapture();
    await waitFor(() => expect(result.current.sources).toHaveLength(1));

    await act(async () => {
      await result.current.start();
    });

    expect(result.current.error).toBeNull();
    expect(result.current.status.state).toBe('capturing');
    // The granted prompt is what makes the *next* attempt able to name a
    // device, so the re-read has to land.
    await waitFor(() => expect(result.current.sources[0].label).toBe('Scarlett Solo USB'));
  });
});

describe('marking the input that is live', () => {
  /**
   * Reachable only once opening the default microphone works: before that a
   * browser start always failed, so no row was ever live. The list is re-read
   * after the prompt and comes back carrying real ids, so a status still
   * holding the placeholder's empty id matches nothing and the row that is
   * recording carries no "In use" — which a headless check caught.
   */
  it('marks the device the browser opened, not the placeholder that was clicked', async () => {
    vi.stubGlobal('isSecureContext', true);
    let granted = false;
    const track = {
      kind: 'audio',
      enabled: true,
      stop() {},
      getSettings: () => ({ deviceId: 'mic-1' }),
    };

    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: {
        enumerateDevices: async () => [
          granted
            ? { kind: 'audioinput', deviceId: 'mic-1', label: 'Scarlett Solo USB' }
            : { kind: 'audioinput', deviceId: '', label: '' },
        ],
        getUserMedia: async () => {
          granted = true;
          return { getAudioTracks: () => [track], getTracks: () => [track] };
        },
      },
    });

    const { result } = renderCapture();
    await waitFor(() => expect(result.current.sources).toHaveLength(1));

    await act(async () => {
      await result.current.start();
    });

    await waitFor(() => expect(result.current.status.source?.id).toBe('mic-1'));
    expect(result.current.status.source?.label).toBe('Scarlett Solo USB');
  });
});

describe('the recording clock', () => {
  /**
   * `elapsed` was the literal string "00:00" in the route: the prop existed,
   * the screen styled it with tabular numerals, and nothing ever computed a
   * value. A meeting recorded for forty minutes showed the two zeroes it
   * showed before it started, which reads as capture having failed.
   *
   * The hook owns it because neither backend can supply it: the shell's
   * status reports frames and no timestamp, and a browser `MediaStream` has
   * no start time either.
   */
  function browserWithMicrophone() {
    const track = { kind: 'audio', enabled: true, stop() {} };
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: {
        enumerateDevices: async () => [
          { kind: 'audioinput', deviceId: 'mic-1', label: 'Built-in Microphone' },
        ],
        getUserMedia: async () => ({ getAudioTracks: () => [track], getTracks: () => [track] }),
      },
    });
  }

  it('reads zero before anything has been recorded', () => {
    vi.stubGlobal('isSecureContext', true);
    browserWithMicrophone();

    const { result } = renderCapture();

    expect(result.current.elapsedSeconds).toBe(0);
  });

  it('counts up while recording', async () => {
    vi.useFakeTimers();
    try {
      vi.stubGlobal('isSecureContext', true);
      browserWithMicrophone();

      const { result } = renderCapture();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      await act(async () => {
        await result.current.start();
      });

      await act(async () => {
        await vi.advanceTimersByTimeAsync(3_000);
      });

      expect(result.current.elapsedSeconds).toBe(3);
    } finally {
      vi.useRealTimers();
    }
  });

  it('holds still while paused, because paused time is not recorded time', async () => {
    vi.useFakeTimers();
    try {
      vi.stubGlobal('isSecureContext', true);
      browserWithMicrophone();

      const { result } = renderCapture();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      await act(async () => {
        await result.current.start();
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2_000);
      });
      await act(async () => {
        await result.current.pause();
      });

      await act(async () => {
        await vi.advanceTimersByTimeAsync(10_000);
      });

      expect(result.current.elapsedSeconds).toBe(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it('resumes from where it paused rather than from zero', async () => {
    vi.useFakeTimers();
    try {
      vi.stubGlobal('isSecureContext', true);
      browserWithMicrophone();

      const { result } = renderCapture();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      await act(async () => {
        await result.current.start();
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2_000);
      });
      await act(async () => {
        await result.current.pause();
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(10_000);
      });
      await act(async () => {
        await result.current.resume();
      });

      await act(async () => {
        await vi.advanceTimersByTimeAsync(1_000);
      });

      expect(result.current.elapsedSeconds).toBe(3);
    } finally {
      vi.useRealTimers();
    }
  });

  it('goes back to zero when the recording stops', async () => {
    vi.useFakeTimers();
    try {
      vi.stubGlobal('isSecureContext', true);
      browserWithMicrophone();

      const { result } = renderCapture();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      await act(async () => {
        await result.current.start();
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(5_000);
      });
      await act(async () => {
        await result.current.stop();
      });

      expect(result.current.elapsedSeconds).toBe(0);
    } finally {
      vi.useRealTimers();
    }
  });
});

/**
 * The level meter.
 *
 * The screen it feeds can say "Recording" for forty minutes over a muted input
 * and look identical to one that is working, so these assert the reading is a
 * real one taken off the stream -- and, just as importantly, that its absence
 * is reported as absence rather than as a zero, which would be the same lie in
 * the other direction.
 */
describe('the level meter', () => {
  /** An `AudioContext` whose analyser always reports the byte given. */
  function stubAudioContext(byte: number) {
    const released = { source: false, context: false };
    class FakeAudioContext {
      createAnalyser() {
        return {
          fftSize: 0,
          getByteTimeDomainData(into: Uint8Array) {
            into.fill(byte);
          },
        };
      }
      createMediaStreamSource() {
        return {
          connect: () => undefined,
          disconnect: () => {
            released.source = true;
          },
        };
      }
      async close() {
        released.context = true;
      }
    }
    vi.stubGlobal('AudioContext', FakeAudioContext);
    return released;
  }

  function stubMicrophone() {
    const track = { kind: 'audio', enabled: true, stop: () => undefined };
    vi.stubGlobal('isSecureContext', true);
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: {
        enumerateDevices: async () => [
          { kind: 'audioinput', deviceId: 'mic-1', label: 'Built-in Microphone' },
        ],
        getUserMedia: async () => ({
          getAudioTracks: () => [track],
          getTracks: () => [track],
        }),
      },
    });
  }

  it('reports a level read off the open stream while recording', async () => {
    stubAudioContext(255);
    stubMicrophone();

    const { result } = renderCapture();
    await waitFor(() => expect(result.current.sources).toHaveLength(1));
    await act(async () => {
      await result.current.start('mic-1');
    });

    await waitFor(() => expect(result.current.level?.peak).toBe(1));
  });

  it('builds a waveform from successive readings, so the screen can scroll it', async () => {
    stubAudioContext(255);
    stubMicrophone();

    const { result } = renderCapture();
    await waitFor(() => expect(result.current.sources).toHaveLength(1));
    await act(async () => {
      await result.current.start('mic-1');
    });

    await waitFor(() => expect(result.current.waveform.length).toBeGreaterThan(1));
  });

  it('has no level at all before recording starts, rather than a zero', async () => {
    // Zero is a reading -- "the room is silent". Before a device is open there
    // is no reading, and a meter drawn at zero would claim otherwise.
    stubAudioContext(255);
    stubMicrophone();

    const { result } = renderCapture();

    await waitFor(() => expect(result.current.sources).toHaveLength(1));
    expect(result.current.level).toBeNull();
  });

  it('releases the audio graph when recording stops', async () => {
    const released = stubAudioContext(255);
    stubMicrophone();

    const { result } = renderCapture();
    await waitFor(() => expect(result.current.sources).toHaveLength(1));
    await act(async () => {
      await result.current.start('mic-1');
    });
    await act(async () => {
      await result.current.stop();
    });

    expect(released.source).toBe(true);
    expect(released.context).toBe(true);
    expect(result.current.level).toBeNull();
  });

  it('reads a flat zero while paused, in every backend', async () => {
    // The one reading this meter must never get wrong. In a browser pause
    // disables the track, so silence is physically true. In the desktop shell
    // a paused session drops each frame *before* emitting it, so a level fed
    // by those events would simply freeze at its last value -- a bar still
    // showing sound arriving at the moment the operator went off the record.
    stubAudioContext(255);
    stubMicrophone();

    const { result } = renderCapture();
    await waitFor(() => expect(result.current.sources).toHaveLength(1));
    await act(async () => {
      await result.current.start('mic-1');
    });
    await waitFor(() => expect(result.current.level?.peak).toBe(1));

    await act(async () => {
      await result.current.pause();
    });

    expect(result.current.level).toEqual({ rms: 0, peak: 0 });
  });

  it('flattens the whole wave on pause, not just its newest bar', async () => {
    // The wave is a history, and a history of loud speech is still drawn loud.
    // Left alone it puts a wall of green beside the word "Paused" -- the one
    // ambiguity this screen exists to remove. While paused the recent input
    // level genuinely is zero, so that is what it shows, on the tap.
    stubAudioContext(255);
    stubMicrophone();

    const { result } = renderCapture();
    await waitFor(() => expect(result.current.sources).toHaveLength(1));
    await act(async () => {
      await result.current.start('mic-1');
    });
    await waitFor(() => expect(result.current.waveform.length).toBeGreaterThan(2));
    expect(result.current.waveform.some((bar) => bar > 0)).toBe(true);

    await act(async () => {
      await result.current.pause();
    });

    expect(result.current.waveform.every((bar) => bar === 0)).toBe(true);
    expect(result.current.waveform.length).toBeGreaterThan(2);
  });

  it('records without a meter on a browser that has no Web Audio at all', async () => {
    // jsdom is such a browser, and so is any engine where the constructor is
    // missing. Recording must not depend on the meter being possible.
    stubMicrophone();

    const { result } = renderCapture();
    await waitFor(() => expect(result.current.sources).toHaveLength(1));
    await act(async () => {
      await result.current.start('mic-1');
    });

    expect(result.current.status.state).toBe('capturing');
    expect(result.current.level).toBeNull();
  });
});

describe('the level meter in the desktop shell', () => {
  /**
   * The shell has no Web Audio to tap: nothing downstream of the audio thread
   * ever sees a sample, so the measurement travels on the frame event itself.
   */
  it('takes its reading from the frame events the session emits', async () => {
    (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__ = {};

    const { result } = renderCapture();
    await waitFor(() => expect(shellEvents.emit).toBeDefined());

    act(() => {
      shellEvents.emit?.({ samples: 320, sequence: 1, rms: 0.5, peak: 0.8 });
    });

    expect(result.current.level).toEqual({ rms: 0.5, peak: 0.8 });
  });

  it('ignores a frame event from a build too old to measure one', async () => {
    // A packaged shell without the level fields must leave the meter absent
    // rather than pinning it at zero, which would read as a silent room.
    (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__ = {};

    const { result } = renderCapture();
    await waitFor(() => expect(shellEvents.emit).toBeDefined());

    act(() => {
      shellEvents.emit?.({ samples: 320, sequence: 1 });
    });

    expect(result.current.level).toBeNull();
  });
});
