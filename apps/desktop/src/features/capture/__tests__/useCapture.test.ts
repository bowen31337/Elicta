import { renderHook, waitFor } from '@testing-library/react';
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
