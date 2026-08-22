import { useCallback, useEffect, useRef, useState } from 'react';

import {
  browserCaptureBlockedReason,
  currentAudioEnvironment,
  listBrowserSources,
  openBrowserCapture,
  type BrowserCaptureSession,
} from './browserCapture';

/**
 * Drives the real capture session, in the desktop shell or in a browser.
 *
 * The screen this feeds was built and tested long before anything opened a
 * microphone, which is why it stays presentational and this hook is separate:
 * the journey scenes and the screen tests render fixed states and must keep
 * working with no device anywhere near them.
 *
 * **There are two backends, and the shell is preferred.** Inside Tauri the
 * commands do the work, because the shell can reach loopback and wired inputs
 * a browser cannot see. Outside it, `browserCapture` opens the page's own
 * microphone — which is what makes `./start.sh` a usable way to try the
 * product before anything is packaged.
 *
 * **Unavailable is four different situations.** This used to report one
 * boolean and the screen printed "unavailable outside the desktop app" for all
 * of them, which was wrong in three cases and unhelpful in the fourth: a page
 * on plain HTTP, a refused permission, and a machine with no microphone are
 * all things the operator can act on. `blockedReason` says which.
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
  /** False when nothing on this machine can open a microphone. */
  readonly available: boolean;
  /** Why capture is unavailable, in words the operator can act on. */
  readonly blockedReason: string | null;
  /** The last failure from trying to open a microphone, if any. */
  readonly error: string | null;
  readonly start: (sourceId?: string) => Promise<void>;
  readonly pause: () => Promise<void>;
  readonly resume: () => Promise<void>;
  readonly stop: () => Promise<void>;
}

export function useCapture(): UseCapture {
  const [status, setStatus] = useState<CaptureStatus>(IDLE);
  const [sources, setSources] = useState<readonly CaptureSourceOption[]>([]);
  const [error, setError] = useState<string | null>(null);
  const shell = shellAvailable();

  // Read once: whether the page is secure and whether the API exists cannot
  // change without a navigation, and re-reading per render would make the
  // reason flicker.
  const [environment] = useState(currentAudioEnvironment);
  // Whether the browser found any input, once it has looked. `null` until it
  // has: `browserCaptureBlockedReason` treats "not asked" and "asked, none"
  // differently on purpose, and collapsing them here would put "no microphone"
  // on screen for the moment before the first enumeration returns.
  const [inputCount, setInputCount] = useState<number | null>(null);
  const blockedReason = shell
    ? null
    : browserCaptureBlockedReason({
        ...environment,
        inputCount: inputCount ?? undefined,
      });
  const available = blockedReason === null;

  const session = useRef<BrowserCaptureSession | null>(null);
  const media = environment.mediaDevices;

  const listSources = useCallback(async () => {
    if (shell) return (await callShell<CaptureSourceOption[]>('list_audio_sources')) ?? [];
    if (!media) return [];
    return listBrowserSources(media);
  }, [shell, media]);

  useEffect(() => {
    let live = true;
    void (async () => {
      const [listed, current] = await Promise.all([
        listSources(),
        shell ? callShell<CaptureStatus>('capture_status') : Promise.resolve(null),
      ]);
      if (!live) return;
      setSources(listed);
      if (!shell) setInputCount(listed.length);
      if (current) setStatus(current);
    })();
    return () => {
      live = false;
    };
  }, [listSources, shell]);

  // A device pulled mid-meeting has to reach the operator — the session is
  // over either way, and silently showing "recording" would be a lie.
  useEffect(() => {
    if (!shell) return undefined;
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
  }, [shell]);

  // Releasing the device when the screen goes away is not tidiness: an open
  // microphone keeps the browser's recording indicator lit, which tells an
  // operator they are being recorded when they are not.
  useEffect(() => () => session.current?.stop(), []);

  const runShell = useCallback(async (command: string, args?: Record<string, unknown>) => {
    const next = await callShell<CaptureStatus>(command, args);
    if (next) setStatus(next);
  }, []);

  const start = useCallback(
    async (sourceId?: string) => {
      setError(null);
      if (shell) return runShell('start_capture', { sourceId });
      if (!media) return;

      const chosen = sourceId ?? sources[0]?.id;
      if (chosen === undefined) {
        setError('No microphone is available to record from.');
        return;
      }
      try {
        session.current?.stop();
        session.current = await openBrowserCapture(media, chosen);
      } catch (cause) {
        session.current = null;
        setError(cause instanceof Error ? cause.message : 'The microphone could not be opened.');
        return;
      }
      setStatus({
        state: 'capturing',
        source: sources.find((source) => source.id === chosen) ?? null,
        frames: 0,
      });
      // Device labels are withheld until permission is granted, so the list
      // read before the prompt was a set of placeholders. Re-read it now that
      // the browser will tell us their names.
      setSources(await listSources());
    },
    [shell, media, sources, runShell, listSources],
  );

  const pause = useCallback(async () => {
    if (shell) return runShell('pause_capture');
    if (!session.current) return;
    session.current.pause();
    setStatus((current) => ({ ...current, state: 'paused' }));
  }, [shell, runShell]);

  const resume = useCallback(async () => {
    if (shell) return runShell('resume_capture');
    if (!session.current) return;
    session.current.resume();
    setStatus((current) => ({ ...current, state: 'capturing' }));
  }, [shell, runShell]);

  const stop = useCallback(async () => {
    if (shell) return runShell('stop_capture');
    session.current?.stop();
    session.current = null;
    setStatus(IDLE);
  }, [shell, runShell]);

  return { status, sources, available, blockedReason, error, start, pause, resume, stop };
}
