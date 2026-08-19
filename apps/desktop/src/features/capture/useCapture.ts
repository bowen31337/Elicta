import { useCallback, useEffect, useState } from 'react';

/**
 * Drives the real capture session in the desktop shell.
 *
 * The screen this feeds was built and tested long before anything opened a
 * microphone, which is why it stays presentational and this hook is separate:
 * the journey scenes and the screen tests render fixed states and must keep
 * working with no device anywhere near them.
 *
 * **It has to work outside Tauri.** The same components render in a browser —
 * the screenshot harness and the accessibility audit both do exactly that —
 * where `window.__TAURI_INTERNALS__` is absent and `invoke` throws. So every
 * call goes through `callShell`, which reports the shell as unavailable rather
 * than raising, and the hook settles into an inert `stopped` state with no
 * sources. That is also what an operator sees if the audio backend fails to
 * load, and it is the honest thing to show them.
 */
export interface CaptureSourceOption {
  readonly id: string;
  readonly label: string;
  readonly degraded: boolean;
}

export interface CaptureStatus {
  readonly state: 'idle' | 'capturing' | 'paused';
  readonly source: CaptureSourceOption | null;
  readonly frames: number;
}

const IDLE: CaptureStatus = { state: 'idle', source: null, frames: 0 };

/** Whether this bundle is running inside the desktop shell at all. */
export function shellAvailable(): boolean {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;
}

async function callShell<T>(command: string, args?: Record<string, unknown>): Promise<T | null> {
  if (!shellAvailable()) return null;
  try {
    const { invoke } = await import('@tauri-apps/api/core');
    return await invoke<T>(command, args);
  } catch {
    // A command that rejects — no session running, device unplugged — is a
    // state the screen already renders. Throwing here would instead take the
    // whole panel down mid-meeting.
    return null;
  }
}

export interface UseCapture {
  readonly status: CaptureStatus;
  readonly sources: readonly CaptureSourceOption[];
  /** False when running outside the desktop shell, so the UI can say so. */
  readonly available: boolean;
  readonly start: (sourceId: string) => Promise<void>;
  readonly pause: () => Promise<void>;
  readonly resume: () => Promise<void>;
  readonly stop: () => Promise<void>;
}

export function useCapture(): UseCapture {
  const [status, setStatus] = useState<CaptureStatus>(IDLE);
  const [sources, setSources] = useState<readonly CaptureSourceOption[]>([]);
  const available = shellAvailable();

  useEffect(() => {
    let live = true;
    void (async () => {
      const [listed, current] = await Promise.all([
        callShell<CaptureSourceOption[]>('list_audio_sources'),
        callShell<CaptureStatus>('capture_status'),
      ]);
      if (!live) return;
      if (listed) setSources(listed);
      if (current) setStatus(current);
    })();
    return () => {
      live = false;
    };
  }, []);

  // A device pulled mid-meeting has to reach the operator — the session is
  // over either way, and silently showing "recording" would be a lie.
  useEffect(() => {
    if (!available) return undefined;
    let unlisten: (() => void) | undefined;
    void (async () => {
      try {
        const { listen } = await import('@tauri-apps/api/event');
        unlisten = await listen('capture://disconnected', () => setStatus(IDLE));
      } catch {
        // Same reasoning as `callShell`: if the event channel cannot be
        // opened, the screen is merely not told about a disconnect. An
        // unhandled rejection here would be a worse outcome than that.
      }
    })();
    return () => unlisten?.();
  }, [available]);

  const run = useCallback(async (command: string, args?: Record<string, unknown>) => {
    const next = await callShell<CaptureStatus>(command, args);
    if (next) setStatus(next);
  }, []);

  return {
    status,
    sources,
    available,
    start: useCallback((sourceId: string) => run('start_capture', { sourceId }), [run]),
    pause: useCallback(() => run('pause_capture'), [run]),
    resume: useCallback(() => run('resume_capture'), [run]),
    stop: useCallback(() => run('stop_capture'), [run]),
  };
}
