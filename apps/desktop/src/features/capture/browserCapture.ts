import type { CaptureSourceOption } from './useCapture';

/**
 * Capture over the browser's own microphone API, for running Elicta as a web
 * app rather than in the Tauri shell.
 *
 * The screen used to say "Audio capture is unavailable outside the desktop
 * app" in every case, which is only one of four situations and the only one
 * the operator cannot do anything about. A page served over plain HTTP, a
 * refused permission prompt and a machine with no microphone are the other
 * three, and each has a different next step — so each says which it is.
 *
 * **The secure-context rule is the one that catches people out.** Browsers
 * expose `navigator.mediaDevices` only on a secure origin: HTTPS, or
 * `localhost`/`127.0.0.1`. Served on a LAN address over plain HTTP the object
 * is not merely empty, it is `undefined`, so there is nothing to permit and no
 * prompt to accept. `start.sh --https` exists for that case.
 *
 * Written over an injected `MediaDevices`-shaped object rather than reaching
 * for the global, so every branch here is testable without a browser, a device
 * or a permission prompt.
 */

/** The two `navigator.mediaDevices` calls this module needs. */
export interface MediaDevicesLike {
  enumerateDevices(): Promise<readonly unknown[]>;
  getUserMedia(constraints: unknown): Promise<MediaStreamLike>;
}

interface MediaTrackLike {
  kind: string;
  enabled: boolean;
  stop(): void;
}

interface MediaStreamLike {
  getAudioTracks(): readonly MediaTrackLike[];
  getTracks(): readonly MediaTrackLike[];
}

interface DeviceInfoLike {
  kind?: string;
  deviceId?: string;
  label?: string;
}

/** What the page can tell us about its own ability to reach a microphone. */
export interface BrowserAudioEnvironment {
  readonly isSecureContext: boolean;
  readonly mediaDevices: MediaDevicesLike | undefined;
  /**
   * How many audio inputs the browser admitted to, once it has been asked.
   * `undefined` means not asked yet, which is not the same as none — saying
   * "no microphone" before looking would be a guess rather than a reading.
   */
  readonly inputCount?: number;
}

/** Reads the real environment, for callers that are not a test. */
export function currentAudioEnvironment(): BrowserAudioEnvironment {
  if (typeof window === 'undefined' || typeof navigator === 'undefined') {
    return { isSecureContext: false, mediaDevices: undefined };
  }
  return {
    isSecureContext: window.isSecureContext === true,
    mediaDevices: (navigator.mediaDevices as MediaDevicesLike | undefined) ?? undefined,
  };
}

/**
 * Why this page cannot open a microphone, or `null` when it can.
 *
 * The insecure-page case is checked first and deliberately does not mention
 * the desktop app: the operator is one URL away from it working, and telling
 * them to go and install something instead would be wrong as well as unhelpful.
 */
export function browserCaptureBlockedReason(env: BrowserAudioEnvironment): string | null {
  if (!env.isSecureContext) {
    return (
      'The browser only allows microphone access on a secure page. Open Elicta ' +
      'over HTTPS, or at localhost on the machine running it, and recording will work.'
    );
  }
  if (env.mediaDevices === undefined) {
    return 'This browser does not offer microphone access, so nothing can be recorded.';
  }
  if (env.inputCount === 0) {
    // The case a live run caught: a secure page, a browser that offers the
    // API, and a machine with nothing plugged in. Both checks above passed, so
    // the screen showed a greyed-out button beside an empty list and explained
    // neither. An operator can do something about "no microphone"; they can do
    // nothing about a control that does nothing.
    return (
      'No microphone is available to this browser. Connect one — or allow ' +
      'access if it was refused — and it will appear here.'
    );
  }
  return null;
}

/**
 * The microphones the browser will admit to having.
 *
 * Every one is reported as `degraded` — which the capture screen renders as
 * "room microphone — picks up echo and cross-talk". A browser cannot tell a
 * laptop mic from a wired feed off a mixing desk, and labelling an unknown
 * device "wired — the cleanest signal" would be a confident claim with nothing
 * behind it. Warning and being wrong costs an operator one glance; reassuring
 * and being wrong costs them the transcript.
 */
export async function listBrowserSources(
  media: MediaDevicesLike,
): Promise<readonly CaptureSourceOption[]> {
  const devices = (await media.enumerateDevices()) as readonly DeviceInfoLike[];
  return devices
    .filter((device) => device.kind === 'audioinput')
    .map((device, index) => ({
      id: device.deviceId ?? '',
      // Labels are withheld until permission is granted, so before the prompt
      // every one of these is the empty string.
      label: device.label && device.label.trim() !== '' ? device.label : `Microphone ${index + 1}`,
      degraded: true,
    }));
}

/** An open microphone, and the three things an operator can do to it. */
export interface BrowserCaptureSession {
  pause(): void;
  resume(): void;
  stop(): void;
}

function openFailureMessage(cause: unknown): string {
  const name = (cause as { name?: string } | null)?.name;
  if (name === 'NotAllowedError' || name === 'SecurityError') {
    return (
      'Microphone access was refused. Allow it for this site in the browser’s ' +
      'address bar, then start again.'
    );
  }
  if (name === 'NotFoundError' || name === 'OverconstrainedError') {
    return 'No microphone matching that input was found.';
  }
  if (name === 'NotReadableError') {
    return 'The microphone is in use by another application and could not be opened.';
  }
  return 'The microphone could not be opened.';
}

/**
 * Opens one microphone for capture.
 *
 * The three processing constraints are switched off on purpose, and it is the
 * same claim the consent screen makes to the client: platform voice processing
 * is tuned for a human listener and removes detail a transcriber uses. Leaving
 * them at their defaults would quietly undo that promise.
 */
export async function openBrowserCapture(
  media: MediaDevicesLike,
  sourceId: string,
): Promise<BrowserCaptureSession> {
  let stream: MediaStreamLike;
  try {
    stream = await media.getUserMedia({
      audio: {
        deviceId: { exact: sourceId },
        echoCancellation: false,
        noiseSuppression: false,
        autoGainControl: false,
      },
      video: false,
    });
  } catch (cause) {
    throw new Error(openFailureMessage(cause));
  }

  const tracks = stream.getAudioTracks();
  return {
    // Pausing silences the track rather than stopping it: the device stays
    // open, so resuming is instant and does not re-prompt. FR-1.3 wants pause
    // to take effect on the tap, and a disabled track emits silence at once.
    pause: () => tracks.forEach((track) => (track.enabled = false)),
    resume: () => tracks.forEach((track) => (track.enabled = true)),
    // Stopping releases the device, which is what turns off the browser's
    // recording indicator — the operator's own proof that it really stopped.
    stop: () => stream.getTracks().forEach((track) => track.stop()),
  };
}
