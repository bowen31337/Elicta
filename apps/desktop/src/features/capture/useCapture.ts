import { useCallback, useEffect, useSyncExternalStore } from 'react';

import {
  captureSession,
  defaultShellAvailable,
  type CaptureSourceOption,
  type CaptureStatus,
  type CaptureStore,
} from '../../services/captureSession';
import type { AudioLevel } from './levelMeter';

/**
 * The capture session, as one screen sees it.
 *
 * **The session itself lives in `services/captureSession`, not here.** It used
 * to live in this hook, in a `useRef` whose unmount effect stopped the device
 * — which was safe for exactly as long as one screen ever called this. The
 * consent screen now opens the microphone and then navigates to the capture
 * screen, so a session that died with its screen would be released on the way
 * there. The desktop shell never had that problem: its session lives in Rust,
 * in a `CaptureManager` held as Tauri state. The store is the browser being
 * given the same lifetime, and this hook is now a subscriber to it.
 *
 * The screen this feeds stays presentational, which is why it is separate: the
 * journey scenes and the screen tests render fixed states and must keep
 * working with no device anywhere near them.
 */

export type { CaptureSourceOption, CaptureStatus };

/** Whether this bundle is running inside the desktop shell at all. */
export const shellAvailable = defaultShellAvailable;

export interface UseCapture {
  readonly status: CaptureStatus;
  readonly sources: readonly CaptureSourceOption[];
  /** False when nothing on this machine can open a microphone. */
  readonly available: boolean;
  /** Why capture is unavailable, in words the operator can act on. */
  readonly blockedReason: string | null;
  /** The last failure from trying to open a microphone, if any. */
  readonly error: string | null;
  /**
   * How long this recording has been running, in whole seconds, not counting
   * time spent paused. Zero when nothing is recording.
   */
  readonly elapsedSeconds: number;
  /**
   * How loud the open input is right now, or `null` when there is no reading
   * to be had — nothing recording, or a browser with no Web Audio.
   *
   * `null` rather than a zero, because the two mean opposite things: zero is
   * "the room is silent", which is a finding an operator acts on, and a meter
   * drawn at zero for want of a meter would be that finding invented.
   */
  readonly level: AudioLevel | null;
  /** Recent levels, oldest first, for the scrolling wave. Empty when idle. */
  readonly waveform: readonly number[];
  /**
   * What this recording is doing about a transcript, when it is not the
   * obvious thing — see `CaptureSnapshot.uploadNote`.
   */
  readonly uploadNote: string | null;
  readonly start: (sourceId?: string) => Promise<void>;
  readonly pause: () => Promise<void>;
  readonly resume: () => Promise<void>;
  readonly stop: () => Promise<void>;
}

/**
 * `store` is injectable for the same reason `browserCapture` takes its
 * `MediaDevices`: so a test drives a session of its own rather than the one
 * the application is running.
 */
export function useCapture(store: CaptureStore = captureSession): UseCapture {
  const snapshot = useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot);

  useEffect(() => {
    void store.refresh();
  }, [store]);

  const start = useCallback(
    async (sourceId?: string) => {
      // Swallowed here and not in the store: this is the capture screen's own
      // button, whose failure the screen renders from `error`. The consent
      // screen awaits the store directly, because it has to *not* go on to
      // allocate a session when the device refuses.
      try {
        await store.start(sourceId);
      } catch {
        /* recorded in the snapshot by the store */
      }
    },
    [store],
  );

  const pause = useCallback(() => store.pause(), [store]);
  const resume = useCallback(() => store.resume(), [store]);
  const stop = useCallback(() => store.stop(), [store]);

  return {
    status: snapshot.status,
    sources: snapshot.sources,
    available: snapshot.blockedReason === null,
    blockedReason: snapshot.blockedReason,
    error: snapshot.error,
    elapsedSeconds: snapshot.elapsedSeconds,
    level: snapshot.level,
    waveform: snapshot.waveform,
    uploadNote: snapshot.uploadNote,
    start,
    pause,
    resume,
    stop,
  };
}
