import { shellAvailable } from './shell';

import {
  browserCaptureBlockedReason,
  currentAudioEnvironment,
  listBrowserSources,
  openBrowserCapture,
  type BrowserAudioEnvironment,
  type BrowserCaptureSession,
} from '../features/capture/browserCapture';
import { int16OfBase64 } from '../features/capture/pcm';
import {
  currentPcmContextFactory,
  openPcmTap,
  type PcmContextLike,
  type PcmTap,
} from '../features/capture/pcmTap';
import { defaultAudioBridge, type AudioBridge } from './audioBridge';
import {
  currentAudioContextFactory,
  meterPosition,
  openLevelReader,
  pushHistory,
  SILENCE,
  type AudioContextLike,
  type AudioLevel,
  type LevelReader,
} from '../features/capture/levelMeter';

/**
 * The capture session, owned by the module rather than by whichever screen
 * happened to start it.
 *
 * **This exists because the two backends had two different lifetimes.** In the
 * desktop shell the session lives in Rust, in a `CaptureManager` held as Tauri
 * state: it survives navigation, and `capture_status` re-reads it whenever a
 * screen mounts. In a browser it lived in a `useRef` inside `useCapture`,
 * whose unmount effect stopped the device — so the same interface meant "your
 * session outlives the screen" on one platform and "your session dies with the
 * screen" on the other. That was invisible while exactly one screen used it.
 * The consent screen now opens the device and then navigates to the capture
 * screen, which walks straight through the difference.
 *
 * So the browser gets the store the shell always had, and both backends sit
 * behind one surface. `useCapture` subscribes to it; nothing else holds a
 * session.
 *
 * Written over injected `MediaDevices`-shaped and `invoke`-shaped
 * dependencies, exactly like `browserCapture` and `levelMeter`, so every
 * branch is reachable with no browser, no device and no permission prompt.
 */

/**
 * One input device within a capture path.
 *
 * The packaged app offered no device choice at all until this existed: it
 * listed two *kinds* and opened whatever the OS called the default input, so
 * an operator with an interface plugged in beside a built-in microphone had no
 * way to say which one to record. The browser build had been enumerating and
 * offering real devices the whole time, which is the wrong way round — the
 * packaged app is the one that ships.
 */
export interface CaptureInputDevice {
  readonly id: string;
  readonly name: string;
  readonly isDefault: boolean;
  /** Mixes the room into one stream (FR-1.2) — the built-in microphone. */
  readonly degraded: boolean;
}

export interface CaptureSourceOption {
  readonly id: string;
  readonly label: string;
  readonly degraded: boolean;
  /** Empty when the path takes no device, as the loopback tap does. */
  readonly devices?: readonly CaptureInputDevice[];
}

export interface CaptureStatus {
  /**
   * `checking` is the green room: the device is open and the meter is live,
   * and nothing is being recorded. It exists because a browser withholds
   * device ids and labels until the first permission grant, so a picker drawn
   * before that grant is a list of placeholders rather than a choice — and
   * because the choice is binding, `start` refusing while a session runs on
   * both backends.
   */
  readonly state: 'idle' | 'checking' | 'capturing' | 'paused';
  readonly source: CaptureSourceOption | null;
  readonly frames: number;
}

export const IDLE: CaptureStatus = { state: 'idle', source: null, frames: 0 };

/** What every subscriber reads. Replaced wholesale, never mutated. */
export interface CaptureSnapshot {
  readonly status: CaptureStatus;
  readonly sources: readonly CaptureSourceOption[];
  /** Why capture cannot begin here, in words the operator can act on. */
  readonly blockedReason: string | null;
  /** The last failure from trying to open a device, if any. */
  readonly error: string | null;
  /**
   * How long this recording has been running, in whole seconds, not counting
   * time spent paused. Zero when nothing is recording.
   */
  readonly elapsedSeconds: number;
  /**
   * How loud the open input is right now, or `null` when there is no reading
   * to be had. `null` rather than a zero, because the two mean opposite
   * things: zero is "the room is silent", which is a finding an operator acts
   * on, and a meter drawn at zero for want of a meter would be that finding
   * invented.
   */
  readonly level: AudioLevel | null;
  /**
   * Whether a level is impossible on this backend, as opposed to not having
   * arrived. Only the browser path can answer yes: it knows when there is no
   * Web Audio to open. In the shell the level comes from Rust, and its
   * absence is always "none yet" — which may mean the device is opening, or
   * that it is producing nothing at all.
   */
  readonly levelUnmeasurable: boolean;
  /** Recent levels, oldest first, for the scrolling wave. Empty when idle. */
  readonly waveform: readonly number[];
  /**
   * What the operator needs to know about where this recording is going, or
   * `null` when it is going where they would expect.
   *
   * Audio only leaves the machine for a meeting whose consent gate allows it
   * (`audioBridge`), and every other case records locally and uploads nothing.
   * That difference is invisible on screen — the meter moves either way — so
   * the reason is carried here and shown, rather than being discovered later
   * from a meeting that has no transcript.
   */
  readonly uploadNote: string | null;
}

/** Bars in the scrolling wave. At the sample rate below, about five seconds. */
const WAVEFORM_BARS = 48;

/**
 * How often the meter is sampled, in milliseconds.
 *
 * 20 readings a second: fast enough that the bar tracks a syllable, slow
 * enough to cost nothing. Deliberately an interval rather than
 * `requestAnimationFrame` — a backgrounded tab throttles both, and the meter
 * is the one thing nobody is looking at when it is hidden.
 */
const METER_INTERVAL_MS = 50;

export interface CaptureDeps {
  shellAvailable(): boolean;
  environment(): BrowserAudioEnvironment;
  invoke<T>(command: string, args?: Record<string, unknown>): Promise<T>;
  /** Injected so the recording clock is testable without waiting for one. */
  now(): number;
  /** The page's `AudioContext` factory, or `null` where there is no Web Audio. */
  audioContext(): (() => AudioContextLike) | null;
  /** The page's 16kHz `AudioContext` factory, for reading actual samples. */
  pcmContext(): (() => PcmContextLike) | null;
  /** The bridge to the service. Injected so no test uploads anything. */
  createBridge(onNote: (note: string | null) => void): AudioBridge;
  listen(
    name: string,
    handler: (event: { payload: unknown }) => void,
  ): Promise<() => void>;
  /** Where `pagehide` is heard. The window, outside a test. */
  pageEvents: { addEventListener(type: string, handler: () => void): void };
}

export interface CaptureStore {
  subscribe(listener: () => void): () => void;
  getSnapshot(): CaptureSnapshot;
  /** Re-reads the device list, and the shell's session if there is one. */
  refresh(): Promise<void>;
  /**
   * Opens the device without recording, so the operator can see it working.
   *
   * `deviceId` names one input within that path, from the source's `devices`.
   * Omitted, the OS's own preference opens — which is all this could ever do
   * before, and is why an operator with an interface plugged in beside a
   * built-in microphone had no way to say which one was recording.
   */
  check(sourceId?: string, deviceId?: string): Promise<void>;
  /**
   * Records on the device that is already open, promoting a check rather than
   * re-opening it — a second `getUserMedia` prompts again on some browsers and
   * certainly leaves a gap where the device is shut.
   */
  beginRecording(): Promise<void>;
  /** Opens a device and records on it, in one step. */
  start(sourceId?: string, deviceId?: string): Promise<void>;
  pause(): Promise<void>;
  resume(): Promise<void>;
  /** Releases the device. The only thing that does, now that no unmount will. */
  stop(): Promise<void>;
}

const EMPTY: CaptureSnapshot = {
  status: IDLE,
  sources: [],
  blockedReason: null,
  error: null,
  elapsedSeconds: 0,
  level: null,
  levelUnmeasurable: false,
  waveform: [],
  uploadNote: null,
};

/** Whether this bundle is running inside the desktop shell at all. */
export function defaultShellAvailable(): boolean {
  return shellAvailable();
}

/**
 * What went wrong, in the shell's own words.
 *
 * Tauri rejects a failing command with the `String` the `Result` carried, so
 * the three refusals `start_capture` can give — already running, unknown
 * source, and the device's own disconnect reason — arrive here as the message
 * to show. They used to be caught and discarded.
 */
function shellFailureMessage(cause: unknown): string {
  if (typeof cause === 'string' && cause !== '') return cause;
  if (cause instanceof Error && cause.message !== '') return cause.message;
  return 'The desktop shell refused to open the microphone.';
}

export function createCaptureStore(deps: Partial<CaptureDeps> = {}): CaptureStore {
  const now = deps.now ?? (() => Date.now());
  const shellAvailable = deps.shellAvailable ?? defaultShellAvailable;
  const environment = deps.environment ?? currentAudioEnvironment;
  const audioContext = deps.audioContext ?? currentAudioContextFactory;
  const pcmContext = deps.pcmContext ?? currentPcmContextFactory;
  const createBridge = deps.createBridge ?? defaultAudioBridge;
  const listen =
    deps.listen ??
    (async (name: string, handler: (event: { payload: unknown }) => void) => {
      const events = await import('@tauri-apps/api/event');
      return await events.listen(name, handler as never);
    });
  const invoke =
    deps.invoke ??
    (async <T,>(command: string, args?: Record<string, unknown>): Promise<T> => {
      const core = await import('@tauri-apps/api/core');
      return await core.invoke<T>(command, args);
    });

  const pageEvents =
    deps.pageEvents ?? (typeof window === 'undefined' ? null : window);

  const listeners = new Set<() => void>();
  let snapshot: CaptureSnapshot = EMPTY;
  let session: BrowserCaptureSession | null = null;
  // Read once: whether the page is secure and whether the API exists cannot
  // change without a navigation.
  const env = environment();
  // `undefined` until the first enumeration, because "not asked" and "asked,
  // none" are different claims — see `browserCaptureBlockedReason`.
  let inputCount: number | undefined;
  let reader: LevelReader | null = null;
  let tap: PcmTap | null = null;
  let bridge: AudioBridge | null = null;
  /** Whether samples reaching the tap are passed on — false while paused. */
  let feeding = false;
  /** Samples seen since the watchdog last looked. */
  let samplesSinceCheck = 0;
  let silenceTimer: ReturnType<typeof setInterval> | null = null;

  /**
   * How long a recording may read nothing before the screen says so.
   *
   * Samples arrive several times a second, so this is many missed buffers
   * rather than a slow one — long enough that opening the graph, or a device
   * that takes a moment to deliver its first frame, does not raise a false
   * alarm, and short enough that an operator learns inside the first exchange
   * of a meeting rather than after it.
   */
  const SILENCE_CHECK_MS = 5_000;

  /** Counts one arrival of audio, from either backend. */
  function sawSamples(): void {
    samplesSinceCheck += 1;
  }

  function startSilenceWatch(): void {
    stopSilenceWatch();
    samplesSinceCheck = 0;
    silenceTimer = setInterval(() => {
      if (samplesSinceCheck > 0) {
        samplesSinceCheck = 0;
        // Taken back down only if it is ours. A warning left standing over a
        // recording that is now uploading is the same lie in the other
        // direction — and clearing indiscriminately would wipe the uploader's
        // own note, which is about a different problem and still true.
        if (snapshot.uploadNote === NO_AUDIO_READ) publish({ uploadNote: null });
        return;
      }
      if (snapshot.uploadNote !== NO_AUDIO_READ) publish({ uploadNote: NO_AUDIO_READ });
    }, SILENCE_CHECK_MS);
  }

  function stopSilenceWatch(): void {
    if (silenceTimer === null) return;
    clearInterval(silenceTimer);
    silenceTimer = null;
    samplesSinceCheck = 0;
  }
  let meterTimer: ReturnType<typeof setInterval> | null = null;
  let clockTimer: ReturnType<typeof setInterval> | null = null;

  /**
   * The recording clock.
   *
   * Recorded time, not wall time: `recordedMs` banks whatever a run
   * accumulated when it paused, and `runningSince` is the start of the run in
   * progress. Deriving the total from the two on every read — rather than
   * incrementing a counter — keeps it honest when a tick is throttled, which
   * a background tab does routinely.
   */
  let recordedMs = 0;
  let runningSince: number | null = null;

  function currentElapsed(): number {
    const total = recordedMs + (runningSince === null ? 0 : now() - runningSince);
    return Math.max(0, Math.floor(total / 1000));
  }

  /**
   * Ticking is what makes the clock reach the screen.
   *
   * Recomputing on read keeps the value right, but a subscriber only re-renders
   * when a listener fires — so without this a recording would display the
   * second it started at for its whole length. Published only when the whole
   * second actually changes, so this costs one render a second and not four.
   */
  function startTicking(): void {
    if (clockTimer !== null) return;
    clockTimer = setInterval(() => {
      if (currentElapsed() !== snapshot.elapsedSeconds) publish({});
    }, 250);
  }

  function stopTicking(): void {
    if (clockTimer === null) return;
    clearInterval(clockTimer);
    clockTimer = null;
  }

  /** Starts a run, or resumes one. Idempotent, so a re-entrant call cannot
   *  silently restart the clock and lose the time already banked. */
  function startClock(): void {
    if (runningSince === null) runningSince = now();
    startTicking();
  }

  /** Ends the run in progress and banks what it accumulated. */
  function bankClock(): void {
    stopTicking();
    if (runningSince === null) return;
    recordedMs += now() - runningSince;
    runningSince = null;
  }

  function resetClock(): void {
    stopTicking();
    recordedMs = 0;
    runningSince = null;
  }

  function publish(next: Partial<CaptureSnapshot>): void {
    snapshot = { ...snapshot, ...next, elapsedSeconds: currentElapsed() };
    for (const listener of [...listeners]) listener();
  }

  /**
   * The meter, sampled once for the whole application.
   *
   * It lives beside the session rather than in the hook because there is one
   * analyser and there can be several screens: the panel floats over the
   * capture screen, and a timer per subscriber would read the same analyser
   * twice and draw two different waves from it.
   */
  function pushLevel(next: AudioLevel): void {
    publish({
      level: next,
      waveform: pushHistory(snapshot.waveform, meterPosition(next.rms), WAVEFORM_BARS),
    });
  }

  function startMeter(): void {
    if (meterTimer !== null || reader === null) return;
    const open = reader;
    meterTimer = setInterval(() => pushLevel(open.read()), METER_INTERVAL_MS);
  }

  function stopMeter(): void {
    if (meterTimer === null) return;
    clearInterval(meterTimer);
    meterTimer = null;
  }

  function closeMeter(): void {
    stopMeter();
    reader?.close();
    reader = null;
    publish({ level: null, waveform: [] });
  }

  /**
   * Paused reads a flat zero, and that is deliberate in both backends.
   *
   * In a browser it is also physically true — pause disables the track, which
   * emits real silence. In the shell it has to be imposed: a paused session
   * drops each frame *before* emitting it, so a level driven by those events
   * would freeze at its last value and leave a bar showing sound still
   * arriving at the exact moment somebody went off the record.
   */
  function flattenMeter(): void {
    stopMeter();
    publish({ level: SILENCE, waveform: snapshot.waveform.map(() => 0) });
  }

  function blocked(): string | null {
    if (shellAvailable()) return null;
    return browserCaptureBlockedReason({ ...env, inputCount });
  }

  /**
   * The shell's own channel, opened once for the application.
   *
   * A build too old to carry the frame event leaves the meter absent rather
   * than pinned at zero — which would read as a silent room rather than as an
   * unmeasured one. An event channel that cannot be opened costs the screen
   * its meter, and must not cost it the meeting.
   */
  let shellChannel: Promise<void> | null = null;
  /** Set when the event channel could not be opened; see the catch below. */
  let channelRefused = false;
  function openShellChannel(): Promise<void> {
    if (!shellAvailable()) return Promise.resolve();
    // Returned rather than fired and forgotten, because a recording started
    // from a screen that never refreshed has to be able to wait for it: the
    // consent screen does exactly that, and without the wait the shell would
    // record with nothing listening for its audio and no sign of it anywhere.
    if (shellChannel === null) {
      shellChannel = (async () => {
        try {
          await listen('capture://frame', (event) => {
            const { rms, peak } = (event.payload ?? {}) as { rms?: number; peak?: number };
            if (typeof rms !== 'number' || typeof peak !== 'number') return;
            pushLevel({ rms, peak });
          });
          await listen('capture://pcm', (event) => {
            // Gated on `feeding` as well as on Rust having dropped the frame
            // already: two independent guards on the one promise the pause
            // banner makes, and this is the cheaper of them.
            const open = bridge;
            if (!feeding || open === null) return;
            const { pcm } = (event.payload ?? {}) as { pcm?: string };
            if (typeof pcm !== 'string' || pcm === '') return;
            sawSamples();
            open.push(int16OfBase64(pcm));
          });
          await listen('capture://disconnected', (event) => {
            // A device pulled mid-meeting has to reach the operator: the
            // session is over either way, and silently showing "recording"
            // would be a lie.
            resetClock();
            closeMeter();
            publish({
              status: IDLE,
              error:
                typeof event.payload === 'string' && event.payload !== ''
                  ? event.payload
                  : 'The audio device was disconnected.',
            });
          });
        } catch {
          // Not rethrown: the note above is right that a dead channel must
          // not stop the meeting being recorded, and a recording held on the
          // machine is worth more than no recording.
          //
          // Silence was the mistake. `capture://frame` is the meter and can
          // degrade to absent, but `capture://pcm` is the only path a desktop
          // recording reaches the service by — losing it means nothing is
          // uploaded while the screen shows a healthy recording throughout,
          // which is the shape of failure this whole module is written
          // against. So the meeting continues and the operator is told.
          channelRefused = true;
        }
      })();
    }
    return shellChannel;
  }

  /**
   * Why a recording in this browser is going nowhere but the room.
   *
   * The meter degrades to absent when there is no Web Audio; the upload cannot
   * degrade to anything, because reading the samples is the only way to send
   * them. An operator who is not told finds out from a meeting that produced
   * no transcript, which reads as a broken product rather than as a browser.
   */
  /**
   * Said when a recording is reading nothing, which no other signal shows.
   *
   * Every visible sign of a working microphone can be present while not one
   * sample is read: the device is open so the state word says Recording, and
   * the level meter moves because it polls an analyser of its own rather than
   * waiting for the audio graph to be pumped. The uploader announces its own
   * failures; this is the absence of anything to upload, and the only way to
   * notice it is to wait for it.
   */
  const NO_AUDIO_READ =
    'The microphone is open but no audio is being read from it, so nothing is ' +
    'being uploaded and this meeting will not be transcribed. Stop and start ' +
    'the recording again.';

  const NO_EVENT_CHANNEL =
    'The recording is running, but this app could not open the channel that ' +
    'carries its audio, so nothing is being uploaded and this meeting will ' +
    'not be transcribed. The audio is not lost — stop, restart the app, and ' +
    'record again.';

  const NO_PCM_TAP =
    'This browser cannot read the recorded audio, so nothing is being uploaded ' +
    'and this meeting will not be transcribed. Use the desktop app, or a ' +
    'browser with Web Audio, if you need a transcript.';

  /**
   * Opens the path to the service for a recording that has just begun.
   *
   * Deliberately not part of opening the device, and not part of *checking*
   * one either: a check is the operator looking at the meter, and audio read
   * during it belongs to nobody's meeting. Only a recording uploads.
   *
   * The device is already open and the screen already says Recording when this
   * runs, because whether the audio may be *sent* is a question for the
   * consent gate and the network — and nobody should watch a spinner over a
   * microphone that is working.
   */
  /**
   * Creates the bridge and lets it ask the consent gate.
   *
   * Whether it goes on to upload anything is the bridge's decision and not
   * this module's: capture opens devices, and what may leave the machine is a
   * question about a meeting.
   */
  async function startBridge(): Promise<AudioBridge> {
    const open = createBridge((note) => publish({ uploadNote: note }));
    bridge = open;
    await open.start();
    feeding = true;
    return open;
  }

  async function openUploadPath(): Promise<void> {
    if (bridge !== null || tap !== null) return;

    // In the shell there is nothing to tap: Rust normalises the audio in the
    // capture pipeline and emits it as `capture://pcm`, already at 16kHz mono.
    if (shellAvailable()) {
      // The channel carries this recording's audio, so it has to be listening
      // before the bridge is told there is any.
      await openShellChannel();
      await startBridge();
      if (channelRefused) {
        // Said once, here, rather than waited for: the silence watch below
        // would report "no audio is being read" five seconds later, which is
        // true and describes the symptom rather than the cause. An operator
        // told the channel was refused knows to restart the app; one told the
        // microphone is delivering nothing goes looking at the microphone.
        publish({ uploadNote: NO_EVENT_CHANNEL });
        return;
      }
      // Watched on this backend too. The cause differs — a Rust device that
      // opens and then emits nothing rather than a graph that will not run --
      // and what the operator needs told is the same either way.
      startSilenceWatch();
      return;
    }

    // A browser has to read the samples itself, and cannot always.
    if (session === null) return;
    const makeContext = pcmContext();
    if (makeContext === null) {
      publish({ uploadNote: NO_PCM_TAP });
      return;
    }
    const stream = session.stream;
    const open = await startBridge();
    try {
      // The tap is opened after the gate has answered rather than before, so
      // no samples are read and silently dropped while the question of whether
      // they may be sent is still open.
      tap = openPcmTap(makeContext(), stream, (samples) => {
        // Counted before the pause gate: a paused recording still reads
        // samples — the track is disabled, which makes the graph produce
        // digital silence rather than stopping it — so counting after the
        // gate would raise the alarm on every pause.
        sawSamples();
        if (feeding) open.push(samples);
      });
      startSilenceWatch();
    } catch {
      // A context that will not open costs the transcript, not the meeting.
      tap = null;
      publish({ uploadNote: NO_PCM_TAP });
    }
  }

  /**
   * Stops reading samples, and hands back the bridge to be finished off.
   *
   * Split from the finishing because of `pagehide`: an unloading page runs
   * what is synchronous and is under no obligation to run what comes after an
   * `await`. Detaching the tap and releasing the device therefore happen
   * before anything is awaited, and the flush — which is a network call, and
   * was never going to survive an unload — happens after.
   */
  function detachTap(): AudioBridge | null {
    feeding = false;
    stopSilenceWatch();
    tap?.close();
    tap = null;
    const open = bridge;
    bridge = null;
    return open;
  }

  /**
   * Opens one device, on whichever backend this is, and leaves it open.
   *
   * Shared by checking and recording precisely so that the device a check
   * opened is the device that records.
   */
  async function openDevice(sourceId?: string, deviceId?: string): Promise<void> {
    // Refused rather than restarted, which is the answer the shell has always
    // given. Two sessions on one device is a state the operator can neither
    // see nor get out of.
    if (session !== null || snapshot.status.state !== 'idle') {
      throw new Error('capture is already running');
    }

    if (shellAvailable()) {
      try {
        const next = await invoke<CaptureStatus>('start_capture', { sourceId, deviceId });
        publish({ status: next, error: null });
      } catch (cause) {
        const message = shellFailureMessage(cause);
        publish({ error: message });
        throw new Error(message);
      }
      return;
    }

    // Refused rather than quietly doing nothing: a start that no-ops would let
    // the caller go on to book a meeting against a recording that cannot
    // exist. The reason is the one the screen is already showing.
    const reason = blocked();
    if (reason !== null) {
      publish({ error: reason });
      throw new Error(reason);
    }
    const media = env.mediaDevices;
    if (media === undefined) return;
    const chosen = sourceId ?? snapshot.sources[0]?.id;
    if (chosen === undefined) {
      const message = 'No microphone is available to record from.';
      publish({ error: message });
      throw new Error(message);
    }
    try {
      session = await openBrowserCapture(media, chosen);
    } catch (cause) {
      session = null;
      const message =
        cause instanceof Error ? cause.message : 'The microphone could not be opened.';
      // Recorded *and* rethrown: the screen reads the snapshot, and a caller
      // sequencing a service call after this must not go on.
      publish({ error: message });
      throw new Error(message);
    }
    // Metering is optional and recording is not, so a browser without Web
    // Audio — or one that refuses a context — records with no meter rather
    // than failing to record.
    const makeContext = audioContext();
    if (makeContext !== null) {
      try {
        reader = openLevelReader(makeContext(), session.stream);
      } catch {
        reader = null;
      }
    }
    // Recorded rather than left to be guessed from an absent reading. Without
    // it the screen has one fact — no level — and two possible causes, and it
    // used to assert the wrong one in the shell, where this path is not even
    // the one in use.
    publish({ levelUnmeasurable: reader === null });
    publish({
      status: {
        ...snapshot.status,
        source: snapshot.sources.find((source) => source.id === chosen) ?? null,
        frames: 0,
      },
      error: null,
    });
  }

  /**
   * Re-reads the device list now that permission has been granted.
   *
   * Ids and labels are both withheld until it is, so the list read before the
   * prompt was a set of placeholders — which is the whole reason the check
   * step exists. The status is still holding one of those placeholders, whose
   * empty id matches nothing in the list that just came back, so the row that
   * is live would carry no marker until this re-points it.
   */
  async function nameTheDevice(): Promise<void> {
    const media = env.mediaDevices;
    if (shellAvailable() || media === undefined) return;
    const named = await listBrowserSources(media);
    inputCount = named.length;
    const opened = session?.deviceId ?? null;
    publish({
      sources: named,
      status: {
        ...snapshot.status,
        source:
          opened === null
            ? snapshot.status.source
            : (named.find((source) => source.id === opened) ?? snapshot.status.source),
      },
    });
  }

  const store: CaptureStore = {
    subscribe(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },

    getSnapshot() {
      // Recomputed on read so the clock is live, but the object is replaced
      // only when the whole-second value actually changes — `useSyncExternalStore`
      // re-renders on every new reference, and a fresh object per read would
      // spin.
      const seconds = currentElapsed();
      if (seconds !== snapshot.elapsedSeconds) {
        snapshot = { ...snapshot, elapsedSeconds: seconds };
      }
      return snapshot;
    },

    async refresh() {
      if (shellAvailable()) {
        await openShellChannel();
        const [sources, current] = await Promise.all([
          // Tolerated rather than propagated: a screen mounting against a
          // shell that cannot answer should render empty, not throw. This is
          // the one place the old swallow was right.
          invoke<CaptureSourceOption[]>('list_audio_sources').catch(() => []),
          invoke<CaptureStatus>('capture_status').catch(() => null),
        ]);
        publish({
          sources,
          blockedReason: null,
          // Adopting whatever Rust is holding is what lets an operator start
          // on one screen and arrive at another with the session intact.
          ...(current === null ? {} : { status: current }),
        });
        return;
      }
      const media = env.mediaDevices;
      const sources = media === undefined ? [] : await listBrowserSources(media);
      inputCount = sources.length;
      publish({ sources, blockedReason: blocked() });
    },

    async check(sourceId?: string, deviceId?: string) {
      await openDevice(sourceId, deviceId);
      // Deliberately no clock: nothing is being recorded, so there is nothing
      // for it to have been recorded for.
      startMeter();
      publish({ status: { ...snapshot.status, state: 'checking' } });
      await nameTheDevice();
    },

    async beginRecording() {
      if (snapshot.status.state === 'capturing' || snapshot.status.state === 'paused') {
        throw new Error('capture is already running');
      }
      // A check already holds the device; anything else has to open one.
      if (snapshot.status.state !== 'checking') {
        await openDevice();
        await nameTheDevice();
      }
      startClock();
      startMeter();
      // `uploadNote` is cleared here rather than left: the last recording's
      // warning, still on screen through a recording that is uploading
      // perfectly well, is worse than no warning at all.
      publish({
        status: { ...snapshot.status, state: 'capturing' },
        error: null,
        uploadNote: null,
      });
      await openUploadPath();
    },

    async start(sourceId?: string, deviceId?: string) {
      await openDevice(sourceId, deviceId);
      startClock();
      startMeter();
      publish({
        status: { ...snapshot.status, state: 'capturing' },
        error: null,
        uploadNote: null,
      });
      await nameTheDevice();
      await openUploadPath();
    },

    async pause() {
      if (shellAvailable()) {
        const next = await invoke<CaptureStatus>('pause_capture').catch(() => null);
        if (next === null) return;
        // Rust drops paused frames before it emits them, so this should never
        // have anything to stop. It is set anyway: the promise the pause
        // banner makes is the one thing on that screen that must not depend on
        // both sides of an IPC boundary agreeing.
        feeding = false;
        // Stopped, not merely ignored. The watch asks whether a recording
        // that should be delivering audio is delivering any; a paused one
        // should not be. On this backend Rust drops paused frames before it
        // emits them, so a pause left watched raised "no audio is being read"
        // five seconds in — true, exactly what the operator asked for, and
        // indistinguishable on screen from a dead microphone.
        stopSilenceWatch();
        bankClock();
        publish({ status: next });
        flattenMeter();
        return;
      }
      if (session === null) return;
      session.pause();
      // Pausing disables the track, which does not stop the audio graph — it
      // makes it produce digital silence. Left feeding, a meeting somebody
      // asked to take off the record would upload the silence where it
      // happened, timed and dated. The shell drops paused frames in Rust
      // before they are emitted; this is the browser doing the same.
      feeding = false;
      stopSilenceWatch();
      bankClock();
      publish({ status: { ...snapshot.status, state: 'paused' } });
      flattenMeter();
    },

    async resume() {
      if (shellAvailable()) {
        const next = await invoke<CaptureStatus>('resume_capture').catch(() => null);
        if (next === null) return;
        feeding = bridge !== null;
        if (bridge !== null) startSilenceWatch();
        startClock();
        publish({ status: next });
        return;
      }
      if (session === null) return;
      session.resume();
      feeding = tap !== null;
      if (tap !== null) startSilenceWatch();
      startClock();
      startMeter();
      publish({ status: { ...snapshot.status, state: 'capturing' } });
    },

    async stop() {
      // Synchronous, and first: see `detachTap`.
      const upload = detachTap();
      if (shellAvailable()) {
        // Tolerated: "no capture session is running" is the answer when the
        // operator stops something already stopped, and idle is where they
        // wanted to be either way.
        const next = await invoke<CaptureStatus>('stop_capture').catch(() => null);
        resetClock();
        closeMeter();
        publish({ status: next ?? IDLE, uploadNote: null });
        await upload?.stop();
        return;
      }
      session?.stop();
      session = null;
      resetClock();
      closeMeter();
      publish({ status: IDLE, uploadNote: null });
      // Last: the tail chunk goes, and the record path is asked for a
      // transcript of what was sent.
      await upload?.stop();
    },
  };

  // The protection the hook's unmount effect used to give. An open microphone
  // keeps the browser's recording indicator lit, which tells an operator they
  // are being recorded when they are not — and no unmount stops the session
  // any more, by design.
  pageEvents?.addEventListener('pagehide', () => {
    void store.stop();
  });

  return store;
}

/**
 * The session this application is running, if any.
 *
 * One per bundle, deliberately: the consent screen starts it and the capture
 * screen displays it, and a second store would mean the second screen looking
 * at a device nobody opened.
 */
export const captureSession: CaptureStore = createCaptureStore();
