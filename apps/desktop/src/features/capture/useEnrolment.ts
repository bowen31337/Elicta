import { useCallback, useEffect, useRef, useState } from 'react';

import {
  browserCaptureBlockedReason,
  currentAudioEnvironment,
  openBrowserCapture,
  type BrowserAudioEnvironment,
} from './browserCapture';
import { base64OfInt16, TARGET_SAMPLE_RATE } from './pcm';
import { currentPcmContextFactory, openPcmTap, type PcmContextLike } from './pcmTap';

/**
 * Recording the operator's voice once, so their speech can be told from the
 * client's (PRD FR-1.5).
 *
 * **This is not a meeting, and that is the whole reason it is separate from
 * `captureSession`.** A meeting's session outlives its screen, books a
 * meeting, holds a consent gate and uploads chunk by chunk under a sequence
 * the service refuses to see gaps in. An enrolment does none of that: it opens
 * a device, keeps at most sixty seconds in memory, sends them in one request,
 * and releases everything. Routing it through the meeting session would mean
 * enrolling could book a meeting, and a recording started here would show up
 * as one.
 *
 * The samples are held in a ref rather than in state deliberately. They arrive
 * about twelve times a second and nothing renders them; putting them in state
 * would re-render the screen on every buffer to change a number nobody reads.
 * What state does hold is the elapsed second, which is what the operator
 * watches.
 *
 * Everything the browser provides is injectable for the same reason the rest
 * of this directory does it: the paths worth testing are a refused microphone,
 * a service that rejects the sample, and the sixty-second cap — none of which
 * are reachable against a real device.
 */

/** What the service says about the enrolment, as `GET` returns it. */
export interface EnrolmentStatus {
  readonly enrolled: boolean;
  readonly sample_seconds: number | null;
  readonly embedding_model: string | null;
  readonly enrolled_at: string | null;
  readonly max_sample_seconds: number;
  readonly min_sample_seconds: number;
  readonly usable: boolean;
}

/**
 * Where the enrolment has got to.
 *
 * `saving` is a state rather than a flag because it is genuinely slow: the
 * service embeds a sixty-second sample in around a second, and a button that
 * looked idle for that long would be pressed twice.
 */
export type EnrolmentPhase = 'idle' | 'recording' | 'saving';

export interface UseEnrolment {
  readonly phase: EnrolmentPhase;
  /** The last answer from the service, or `null` before it has given one. */
  readonly status: EnrolmentStatus | null;
  /** Whole seconds recorded so far in this attempt. Zero unless recording. */
  readonly seconds: number;
  /** The cap this attempt will stop itself at. */
  readonly maxSeconds: number;
  /** Why the last attempt failed, in the operator's terms. */
  readonly error: string | null;
  /** Why enrolment cannot be started at all here, or `null` when it can. */
  readonly blockedReason: string | null;
  /**
   * Records from one input. The empty string — which is what a browser hands
   * back for a device it has not been given permission to name — asks for the
   * default microphone rather than pinning an id that can never match.
   */
  readonly start: (sourceId?: string) => void;
  readonly stop: () => void;
  readonly cancel: () => void;
}

export interface EnrolmentDeps {
  readonly environment?: () => BrowserAudioEnvironment;
  readonly pcmContext?: () => (() => PcmContextLike) | null;
  readonly fetch?: typeof fetch;
}

const PATH = '/api/operator/voiceprint';

/** Until the service answers, assume the cap the service actually enforces. */
const FALLBACK_MAX_SECONDS = 60;

async function failureMessage(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === 'string' && body.detail !== '') return body.detail;
  } catch {
    // A body that is not JSON tells us nothing the status has not.
  }
  return `The service answered ${response.status}.`;
}

export function useEnrolment(deps: EnrolmentDeps = {}): UseEnrolment {
  const {
    environment = currentAudioEnvironment,
    pcmContext = currentPcmContextFactory,
    fetch: fetchImpl = fetch,
  } = deps;

  const [phase, setPhase] = useState<EnrolmentPhase>('idle');
  const [status, setStatus] = useState<EnrolmentStatus | null>(null);
  const [seconds, setSeconds] = useState(0);
  const [error, setError] = useState<string | null>(null);

  /**
   * Everything the running recording owns, in one ref.
   *
   * One ref rather than several because they are released together and must
   * not be released twice: the cap fires from a timer while Stop fires from a
   * click, and both end the same recording.
   */
  const recording = useRef<{
    samples: Int16Array[];
    total: number;
    close: () => void;
  } | null>(null);

  const maxSeconds = status?.max_sample_seconds ?? FALLBACK_MAX_SECONDS;

  const refresh = useCallback(async () => {
    try {
      const response = await fetchImpl(PATH, { headers: { Accept: 'application/json' } });
      if (!response.ok) return;
      setStatus((await response.json()) as EnrolmentStatus);
    } catch {
      // A status that cannot be read leaves the screen on its last answer.
      // The enrolment control still works, and pressing it reports properly.
    }
  }, [fetchImpl]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  /** Releases the device and hands back what was recorded, exactly once. */
  const release = useCallback((): { samples: Int16Array[]; total: number } | null => {
    const open = recording.current;
    if (open === null) return null;
    recording.current = null;
    open.close();
    return { samples: open.samples, total: open.total };
  }, []);

  const submit = useCallback(
    async (samples: Int16Array[], total: number) => {
      const joined = new Int16Array(total);
      let offset = 0;
      for (const chunk of samples) {
        joined.set(chunk, offset);
        offset += chunk.length;
      }

      setPhase('saving');
      try {
        const response = await fetchImpl(PATH, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
          body: JSON.stringify({ pcm: base64OfInt16(joined) }),
        });
        if (!response.ok) {
          setError(await failureMessage(response));
          return;
        }
        setStatus((await response.json()) as EnrolmentStatus);
        setError(null);
      } catch {
        setError('The service could not be reached, so nothing was enrolled.');
      } finally {
        setPhase('idle');
        setSeconds(0);
      }
    },
    [fetchImpl],
  );

  const stop = useCallback(() => {
    const held = release();
    if (held === null) return;
    // Nothing recorded is not an error worth a message: the operator pressed
    // start and stop, and the service would refuse it anyway with something
    // less useful than the screen's own "record at least three seconds".
    if (held.total === 0) {
      setPhase('idle');
      setSeconds(0);
      return;
    }
    void submit(held.samples, held.total);
  }, [release, submit]);

  const cancel = useCallback(() => {
    release();
    setPhase('idle');
    setSeconds(0);
  }, [release]);

  const start = useCallback((sourceId = '') => {
    if (recording.current !== null) return;
    setError(null);

    const env = environment();
    const blocked = browserCaptureBlockedReason(env);
    if (blocked !== null || env.mediaDevices === undefined) {
      setError(blocked ?? 'This browser does not offer microphone access.');
      return;
    }
    const makeContext = pcmContext();
    if (makeContext === null) {
      setError(
        'This browser cannot read the microphone’s samples, so a voice sample ' +
          'cannot be recorded here.',
      );
      return;
    }

    const media = env.mediaDevices;
    setPhase('recording');
    setSeconds(0);

    void (async () => {
      let session;
      try {
        // An empty id is not a device — it is the browser declining to name
        // one — and `openBrowserCapture` reads it as "the default
        // microphone". Which is exactly right before the first permission
        // grant, when no input has an id to be chosen by.
        session = await openBrowserCapture(media, sourceId);
      } catch (cause) {
        setPhase('idle');
        setError(cause instanceof Error ? cause.message : 'The microphone could not be opened.');
        return;
      }

      // Registered before the tap is opened, so a recording cancelled between
      // the two still releases the device rather than leaving it lit.
      let tap: { close: () => void } | null = null;
      const close = () => {
        tap?.close();
        session.stop();
      };
      recording.current = { samples: [], total: 0, close };

      try {
        tap = openPcmTap(makeContext(), session.stream, (chunk) => {
          const open = recording.current;
          if (open === null) return;
          // The cap is enforced on the samples themselves, not on the clock:
          // what the service is handed is this array, and a timer that fired
          // late would send more than sixty seconds of it.
          const room = TARGET_SAMPLE_RATE * maxSeconds - open.total;
          if (room <= 0) return;
          const kept = chunk.length <= room ? chunk : chunk.subarray(0, room);
          open.samples.push(kept);
          open.total += kept.length;
        });
      } catch {
        close();
        recording.current = null;
        setPhase('idle');
        setError('The microphone opened but its samples could not be read.');
      }
    })();
  }, [environment, maxSeconds, pcmContext]);

  // The clock the operator watches, and the cap that ends the recording.
  //
  // Driven off the samples actually captured rather than off wall time. A
  // backgrounded tab throttles timers, and a countdown that kept running while
  // the audio did not would stop a recording that was still seconds short.
  useEffect(() => {
    if (phase !== 'recording') return;
    const timer = setInterval(() => {
      const open = recording.current;
      if (open === null) return;
      setSeconds(Math.floor(open.total / TARGET_SAMPLE_RATE));
      if (open.total >= TARGET_SAMPLE_RATE * maxSeconds) stop();
    }, 250);
    return () => clearInterval(timer);
  }, [maxSeconds, phase, stop]);

  // A screen that unmounts mid-recording must not leave the device open — the
  // browser's recording indicator would stay lit with nothing behind it.
  useEffect(() => () => void release(), [release]);

  return {
    phase,
    status,
    seconds,
    maxSeconds,
    error,
    blockedReason: browserCaptureBlockedReason(environment()),
    start,
    stop,
    cancel,
  };
}
