import { captureSession, type CaptureStore } from '../../services/captureSession';
import {
  startSession as postSessionStart,
  type SessionStarted,
} from '../consent/consentActions';

/**
 * Start recording: hold the device, book the meeting, record on it.
 *
 * **The meeting starts when the recording starts**, which is why this lives on
 * the capture screen and not on the consent screen. Consent used to carry a
 * Start button that booked a session and opened no device at all, so an
 * operator was told a meeting had begun while nothing was listening — and it
 * offered no way to choose an input, because it is not a screen that can show
 * you one working.
 *
 * **The device comes first.** A microphone that will not open is the common
 * failure, and on the desktop it is the *only* detectable one: the shell's
 * source list is a compile-time fact about which backends the build carries,
 * deliberately not a probe of the hardware, so nothing can be pre-flighted and
 * the only way to learn whether a device opens is to open it. Opening first
 * means that failure books nothing. The reverse order would leave a session
 * against a recording that never began, and there is no clean way back from
 * that: the only endpoint that ends a session also writes a coverage summary
 * and marks the meeting over.
 *
 * **A device already being checked is the device that records.** Re-opening it
 * would prompt again on some browsers and would certainly leave a gap where
 * the input is shut, so the check is promoted rather than restarted.
 */
export interface GoLiveOptions {
  /** The session to open. The application's own, outside a test. */
  readonly store?: CaptureStore;
  /** Overridable for tests; defaults to the real `POST .../session/start`. */
  readonly startSession?: (meetingId: string) => Promise<SessionStarted>;
  /** Which input to open, when one is not already being checked. */
  readonly sourceId?: string;
}

export async function goLive(
  meetingId: string,
  options: GoLiveOptions = {},
): Promise<SessionStarted> {
  const { store = captureSession, startSession = postSessionStart, sourceId } = options;

  // A check already holds the device. Otherwise open one now — this throws
  // with the device's own sentence, a refused permission or an input another
  // application holds, and nothing has been booked.
  const wasChecking = store.getSnapshot().status.state === 'checking';
  if (!wasChecking) await store.check(sourceId);

  let session: SessionStarted;
  try {
    session = await startSession(meetingId);
  } catch (cause) {
    // The service refused — consent outstanding, most likely. Put the device
    // back where it was rather than leaving it open for a meeting that will
    // not happen.
    await store.stop();
    throw cause;
  }

  await store.beginRecording();
  return session;
}
