import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { shellAvailable, useCapture } from '../useCapture';

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
});

describe('outside the desktop shell', () => {
  it('reports the shell as unavailable rather than guessing', () => {
    expect(shellAvailable()).toBe(false);
    const { result } = renderHook(() => useCapture());
    expect(result.current.available).toBe(false);
  });

  it('settles into idle with no sources instead of throwing', async () => {
    const { result } = renderHook(() => useCapture());

    await waitFor(() => expect(result.current.status.state).toBe('idle'));
    expect(result.current.sources).toEqual([]);
    expect(result.current.status.source).toBeNull();
  });

  it('leaves the controls callable and inert', async () => {
    const { result } = renderHook(() => useCapture());

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
    const { result } = renderHook(() => useCapture());
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

    const { result } = renderHook(() => useCapture());

    await waitFor(() => expect(result.current.blockedReason).toMatch(/no microphone/i));
  });

  it('says nothing about microphones before the browser has been asked', () => {
    vi.stubGlobal('isSecureContext', true);
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { enumerateDevices: () => new Promise(() => {}), getUserMedia: async () => ({}) },
    });

    const { result } = renderHook(() => useCapture());

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

    const { result } = renderHook(() => useCapture());
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

    const { result } = renderHook(() => useCapture());
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

    const { result } = renderHook(() => useCapture());

    expect(result.current.elapsedSeconds).toBe(0);
  });

  it('counts up while recording', async () => {
    vi.useFakeTimers();
    try {
      vi.stubGlobal('isSecureContext', true);
      browserWithMicrophone();

      const { result } = renderHook(() => useCapture());
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

      const { result } = renderHook(() => useCapture());
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

      const { result } = renderHook(() => useCapture());
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

      const { result } = renderHook(() => useCapture());
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
