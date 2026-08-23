import '../prep/screens.css';
import './capture.css';

import { useState } from 'react';

import { ScreenEyebrow } from '../../ui/Mark';
import { formatElapsed } from './elapsed';
import { decibels, meterPosition, type AudioLevel } from './levelMeter';
import type { CaptureStore } from '../../services/captureSession';
import { useCapture } from './useCapture';
import { useEnrolment } from './useEnrolment';
import { useRecordingStart } from './useRecordingStart';

/**
 * Journey 11 — controlling capture mid-meeting.
 *
 * Two things on this screen are safety features rather than conveniences, and
 * they set its whole shape:
 *
 * **Pause is one tap and cannot be missed** (FR-1.3). An operator reaches for
 * it when a client says "can we go off the record" — a control that needs
 * hunting for, or a confirmation dialog, fails at exactly that moment.
 *
 * **The state is unambiguous at a glance** (FR-1.4). Believing you are paused
 * while still recording is the worst failure this product has, so the state is
 * carried by colour, an explicit word, and the button's own label together —
 * never by colour alone (WCAG 1.4.1).
 */
export type CaptureState = 'capturing' | 'paused' | 'checking' | 'stopped';

export interface CaptureSource {
  /** The device to open. Defaults to the label for the fixed journey scenes,
   *  which render a source list but never start one. */
  readonly id?: string;
  readonly label: string;
  readonly kind: 'wired' | 'loopback' | 'acoustic';
  readonly active: boolean;
}

/**
 * A live reading of the open input, for the meter.
 *
 * Three states, not two, and the difference matters on screen. The whole prop
 * being **absent** means this render was never given a meter — the fixed
 * journey scenes, and any moment when nothing is recording. A present prop
 * with a **null** level means a meter was attempted and there is no reading to
 * be had. Collapsing those two would make every documentation screenshot
 * announce that the browser cannot measure sound.
 */
export interface CaptureMetering {
  /** The current reading, or `null` where none can be taken. */
  readonly level: AudioLevel | null;
  /** Recent meter positions, oldest first, for the scrolling wave. */
  readonly waveform: readonly number[];
}

/**
 * The enrolment control, when this render has a live one.
 *
 * Absent on the fixed journey scenes, which show the enrolled and not-enrolled
 * states as pictures and must never open a microphone to do it. Its absence is
 * what keeps the button inert there, and the screen otherwise identical.
 */
export interface CaptureEnrolment {
  readonly phase: 'idle' | 'recording' | 'saving';
  /** Whole seconds recorded in this attempt so far. */
  readonly seconds: number;
  /** Where this attempt stops itself, as the service reported it. */
  readonly maxSeconds: number;
  /** The shortest sample the service will accept. */
  readonly minSeconds: number;
  /**
   * Whether the enrolled sample can still be compared against live audio.
   *
   * Enrolled and verifying nothing is a real state — a print left behind by an
   * embedder no longer running — and it looks exactly like a working one
   * unless the screen says otherwise.
   */
  readonly usable: boolean;
  /** Why the last attempt failed, in the operator's terms. */
  readonly error?: string | null;
  /** Why enrolling cannot be started here at all. Disables the control. */
  readonly blockedReason?: string | null;
  /**
   * A live reading of the microphone being enrolled from. Present only while
   * recording — the same three-state distinction the recording meter makes,
   * where an absent prop is "no meter was asked for" and a present one holding
   * `null` is "a meter was attempted and there is no reading to be had".
   */
  readonly metering?: CaptureMetering;
  /** Starts recording from one input, named as `CaptureSource.id` names it. */
  readonly onStart?: (sourceId: string) => void;
  readonly onStop?: () => void;
  readonly onCancel?: () => void;
}

export interface CaptureScreenProps {
  readonly state: CaptureState;
  readonly elapsed: string;
  readonly sources: readonly CaptureSource[];
  readonly operatorEnrolled: boolean;
  readonly enrolmentSeconds: number;
  /** Fired by the pause/resume control. Omitted by the fixed journey scenes. */
  readonly onTogglePause?: () => void;
  /** Opens the chosen input without recording, so it can be seen working. */
  readonly onCheck?: (sourceId: string) => void;
  /** Why recording cannot begin for consent reasons. Disables the control. */
  readonly consentBlocked?: string | null;
  /** Opens the chosen input. Omitted by the fixed journey scenes. */
  readonly onStart?: (sourceId: string) => void;
  /** Releases the device. Omitted by the fixed journey scenes. */
  readonly onStop?: () => void;
  /** A failure from trying to open the microphone, in the operator's terms. */
  readonly captureError?: string | null;
  /** Shown when the audio backend is unreachable, so "not recording" is
   *  never left looking like a choice the operator made. */
  readonly unavailableReason?: string;
  /**
   * Where this recording's audio is going, when that is not where the operator
   * would assume.
   *
   * A recording that is being uploaded for transcription and one that is not
   * look identical here — same word, same clock, same meter. The difference
   * surfaces afterwards as a meeting with no transcript, which reads as a
   * broken product rather than as the consent gate doing its job. Absent when
   * there is nothing to say: a line confirming the ordinary case on every
   * recording is one more thing to read past.
   */
  readonly uploadNote?: string | null;
  /** A live reading of the open input. Omitted when there is no meter. */
  readonly metering?: CaptureMetering;
  /** The live enrolment control. Omitted by the fixed journey scenes. */
  readonly enrolment?: CaptureEnrolment;
}

const STATE_COPY: Record<CaptureState, { word: string; detail: string; pill: string }> = {
  checking: {
    word: 'Checking the microphone',
    detail:
      'Nothing is being recorded. Say something and watch the level move, then start recording.',
    pill: 'pill pill--warn',
  },
  capturing: {
    word: 'Recording',
    // Not "and transcribed": nothing transcribes during a meeting here.
    // The audio uploaded from this screen becomes a transcript on the
    // record path afterwards, and an operator told otherwise would go
    // looking for a live transcript that does not exist.
    detail: 'Audio is being captured. It becomes a transcript after the meeting, not during it.',
    pill: 'pill pill--alert',
  },
  paused: {
    word: 'Paused',
    detail: 'No audio is reaching the recording. Nothing said now is kept.',
    pill: 'pill pill--warn',
  },
  stopped: {
    word: 'Stopped',
    detail: 'Capture has ended for this meeting.',
    pill: 'pill',
  },
};

/**
 * How loud the open input is, right now.
 *
 * This is the answer to the one question the rest of the screen cannot
 * answer: *is sound actually arriving?* Without it, a muted microphone and a
 * working one produce identical screens for the length of a meeting, and the
 * failure is only discovered in the transcript.
 *
 * **It is one bar, for one device, and says so.** The audio here is a single
 * mixed stream — `getUserMedia` opens one device, and the desktop session
 * holds one source — so there is nothing in it to separate per person. The
 * product does attribute speech to speakers, but it does that on finalised
 * transcript text, seconds behind and only ever "the operator or not", which
 * cannot drive a meter. A bar per participant would therefore be a drawn
 * number with nothing behind it, so the note under the bar says plainly what
 * the reading covers.
 */
function CaptureLevel({
  metering,
  device,
  note = 'One mixed stream — this room, not individual speakers.',
}: {
  metering: CaptureMetering;
  device: string;
  /**
   * What the reading covers. Defaulted to the meeting's caveat because that is
   * what this meter was built for, and overridden where it would be wrong:
   * enrolling is deliberately one person into one microphone, so warning that
   * the bar cannot separate speakers answers a question nobody asked.
   */
  note?: string;
}) {
  if (metering.level === null) {
    // Not a meter pinned at zero: zero says the room is silent, which is a
    // finding an operator would act on. "No reading" is a different claim.
    return (
      <p className="capture-meter-absent t-footnote" role="status">
        This browser cannot measure the input level. Recording is unaffected.
      </p>
    );
  }

  const fill = meterPosition(metering.level.rms);
  const peak = meterPosition(metering.level.peak);
  const db = decibels(metering.level.peak);
  const reading = db === null ? '—' : `${Math.round(db)} dB`;

  return (
    <div className="capture-meter">
      {/* Decorative: the same reading is carried by the meter below, and a
          wave announced sample by sample would be unusable to read. */}
      <div className="capture-meter-wave" aria-hidden="true">
        {metering.waveform.map((bar, index) => (
          <span
            key={index}
            className="capture-meter-bar"
            style={{ height: `${Math.max(2, bar * 100)}%` }}
          />
        ))}
      </div>
      <div className="capture-meter-row">
        <span className="capture-meter-device t-footnote">{device}</span>
        <div
          className="capture-meter-track"
          role="meter"
          aria-label="Input level"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(fill * 100)}
          aria-valuetext={db === null ? 'Silent' : `${Math.round(db)} decibels peak`}
        >
          <span className="capture-meter-fill" style={{ width: `${fill * 100}%` }} />
          {/* The peak sits ahead of the average and is what clipping shows up
              in, so it is marked rather than averaged away. */}
          <span className="capture-meter-peakmark" style={{ left: `${peak * 100}%` }} />
        </div>
        <span className="capture-meter-db t-footnote tabular">{reading}</span>
      </div>
      <p className="capture-meter-note t-footnote">{note}</p>
    </div>
  );
}

export function CaptureScreen({
  state,
  elapsed,
  sources,
  operatorEnrolled,
  enrolmentSeconds,
  enrolment,
  onTogglePause,
  onStart,
  onStop,
  onCheck,
  consentBlocked = null,
  captureError,
  unavailableReason,
  uploadNote,
  metering,
}: CaptureScreenProps) {
  const copy = STATE_COPY[state];
  const acoustic = sources.find((source) => source.active && source.kind === 'acoustic');

  /**
   * Which input the voice sample is recorded from, held apart from the one the
   * meeting records on.
   *
   * They are genuinely different choices. The meeting wants the cleanest feed
   * of the room — a wired input, or a silent join. Enrolling wants whichever
   * microphone is closest to the operator's own mouth, which is often a
   * headset the meeting is not being recorded through at all.
   *
   * So the meeting's input is deliberately *not* inherited. The default here
   * is the browser's own default device, which is the one this recorded from
   * before there was any choice to make — inheriting the meeting's instead
   * would silently move enrolment onto the room microphone, the worst input
   * for the one recording where a single voice is the entire point.
   *
   * Tracked by position rather than by id: before the first permission grant a
   * browser withholds every device id, so all of them are the empty string and
   * no value here could tell them apart. The position always can, and the id
   * it resolves to is still what gets asked for.
   */
  const [chosenVoiceInput, setChosenVoiceInput] = useState(0);
  const voiceInputId = sources[chosenVoiceInput]?.id ?? '';

  const recordingVoice = enrolment?.phase === 'recording';
  const savingVoice = enrolment?.phase === 'saving';
  // No live control, mid-save, or the browser cannot open a microphone here.
  const enrolBlocked =
    enrolment === undefined || savingVoice || (enrolment.blockedReason ?? null) !== null;
  const maxSeconds = enrolment?.maxSeconds ?? 60;
  const minSeconds = enrolment?.minSeconds ?? 3;

  // The count is said in words rather than only drawn: the operator is talking,
  // not watching, and the number is what tells them whether they have said
  // enough to be worth keeping.
  const enrolmentWord = recordingVoice
    ? `Recording — ${enrolment.seconds}s of ${maxSeconds}s`
    : savingVoice
      ? 'Saving your voice sample'
      : operatorEnrolled
        ? 'Enrolled'
        : 'Not enrolled';

  const enrolmentDetail = recordingVoice
    ? enrolment.seconds < minSeconds
      ? `Keep talking — at least ${minSeconds}s is needed. Stopping ends the recording and keeps it.`
      : 'Stopping ends the recording and keeps it. It stops on its own at the cap.'
    : savingVoice
      ? 'Working out the voiceprint. The recording itself is not kept.'
      : operatorEnrolled
        ? `${enrolmentSeconds}s sample. Your speech is tagged as yours, so a question you ask is not mistaken for a client requirement.`
        : `Record up to ${maxSeconds} seconds so your own speech can be told apart from the client’s.`;
  const blocked = Boolean(unavailableReason);
  const sourceId = (source: CaptureSource) => source.id ?? source.label;
  const [chosen, setChosen] = useState<string | null>(null);
  const selected = chosen ?? (sources.length > 0 ? sourceId(sources[0]) : null);

  return (
    <main className="screen" aria-labelledby="capture-title">
      <header className="screen-head">
        <ScreenEyebrow>Capture</ScreenEyebrow>
        <h1 className="t-large-title" id="capture-title">
          {copy.word}
        </h1>
      </header>

      {/* The state banner reads as state, not decoration: the word, the
          detail and the colour all say the same thing. */}
      <section aria-labelledby="state-title">
        <h2 className="t-section" id="state-title">
          State
        </h2>
        <div className={`capture-state capture-state--${state}`} role="status">
          <div className="row-main">
            <span className="t-title-3">{copy.word}</span>
            <span className="t-footnote">{copy.detail}</span>
          </div>
          <span className="t-body tabular capture-elapsed">{elapsed}</span>
        </div>
        {/* Directly under the banner, because it answers the banner's claim:
            "Recording" is what the software believes, and this is the
            evidence. Never shown when stopped -- there is no input open to
            take a reading from, and an empty meter beside "Stopped" would
            invite the reading that the room had gone quiet. */}
        {state !== 'stopped' && metering !== undefined ? (
          <CaptureLevel
            metering={metering}
            device={sources.find((source) => source.active)?.label ?? 'The open input'}
          />
        ) : null}
        {state === 'stopped' || state === 'checking' ? (
          <div className="row row--form capture-controls">
            {sources.length > 1 ? (
              <>
                <label className="sr-only" htmlFor="capture-input">
                  Which input to record from
                </label>
                <select
                  id="capture-input"
                  className="field field--inline"
                  value={selected ?? ''}
                  onChange={(event) => setChosen(event.target.value)}
                >
                  {/* Keyed by position, not by id. A browser withholds every
                      device id until the first permission grant, so before it
                      each of these is the empty string — React saw one key
                      twice and warned that it may duplicate or omit an option,
                      on the picker an operator uses precisely when they have
                      not yet granted anything. The value stays the id, which
                      being empty is the honest answer: with nothing to pin,
                      every one of them means "the default microphone". */}
                  {sources.map((source, index) => (
                    <option key={`${index}-${source.label}`} value={sourceId(source)}>
                      {source.label}
                    </option>
                  ))}
                </select>
              </>
            ) : null}
            {state === 'stopped' ? (
              // Before this is pressed, a browser has told us neither the ids
              // nor the labels of its inputs, so the list above is
              // placeholders. Granting is what fills it in — which is why the
              // check is a real step and not a nicety.
              <button
                type="button"
                className="btn"
                onClick={() => (selected === null ? undefined : onCheck?.(selected))}
                disabled={blocked || selected === null}
              >
                Check microphone
              </button>
            ) : (
              <button type="button" className="btn" onClick={onStop}>
                Stop checking
              </button>
            )}
            <button
              type="button"
              className="btn btn--filled capture-toggle"
              onClick={() => (selected === null ? undefined : onStart?.(selected))}
              disabled={blocked || selected === null || consentBlocked !== null}
            >
              Start recording
            </button>
          </div>
        ) : (
          <div className="row row--form capture-controls">
            <button
              type="button"
              className="btn btn--filled capture-toggle"
              onClick={onTogglePause}
              disabled={blocked}
            >
              {state === 'paused' ? 'Resume recording' : 'Pause recording'}
            </button>
            <button type="button" className="btn" onClick={onStop} disabled={blocked}>
              Stop recording
            </button>
          </div>
        )}
        {consentBlocked ? (
          // `status`, not `alert`: nothing has failed. This is the gate being
          // a gate, and it names the screen that opens it.
          <p className="capture-warning t-footnote" role="status">
            {consentBlocked}
          </p>
        ) : null}
        {captureError ? (
          <p className="capture-warning t-footnote" role="alert">
            {captureError}
          </p>
        ) : null}
        {unavailableReason ? (
          <p className="capture-warning t-footnote" role="status">
            {unavailableReason}
          </p>
        ) : null}
        {uploadNote ? (
          // `status`, like the consent gate above and unlike an error: the
          // recording is working, and what it is not doing is deliberate.
          <p className="capture-warning t-footnote" role="status">
            {uploadNote}
          </p>
        ) : null}
        {/* The hint has to match the controls actually on screen. While
            checking there is no pause to explain, and the thing worth saying
            is that the input being listened to is the one that will record. */}
        <p className="t-footnote hint">
          {state === 'checking'
            ? 'Nothing here is recorded. Starting records on this same input, without asking again.'
            : state === 'stopped'
              ? 'Checking opens the input and records nothing, so you can hear it working first.'
              : 'Pausing takes effect immediately — there is no buffered audio to flush.'}
        </p>
      </section>

      <section aria-labelledby="source-title">
        <h2 className="t-section" id="source-title">
          Input
        </h2>
        <div className="group">
          {sources.map((source) => (
            <div className="row" key={source.label}>
              <div className="row-main">
                <span className="t-body">{source.label}</span>
                <span className="t-footnote">
                  {source.kind === 'wired'
                    ? 'Wired — the cleanest signal, and the recommended source.'
                    : source.kind === 'loopback'
                      ? 'Loopback from a silent join — clean, and per-participant where the platform allows.'
                      : 'Room microphone — picks up echo and cross-talk, which costs accuracy.'}
                </span>
              </div>
              {source.active ? <span className="pill pill--ok">In use</span> : null}
            </div>
          ))}
        </div>
        {acoustic ? (
          <p className="capture-warning t-footnote" role="status">
            You are on a room microphone. Wired or loopback capture is
            noticeably more accurate — cross-talk is the single largest source
            of transcription error.
          </p>
        ) : null}
      </section>

      <section aria-labelledby="voice-title">
        <h2 className="t-section" id="voice-title">
          Your voice
        </h2>
        <div className="group">
          {/* Only when there is a choice to make. One input is not a decision,
              and a select holding a single option is a control that looks
              like it does something.

              Enabled even with no live enrolment control behind it, and
              disabled only while one is running: choosing an input is local
              state and works on its own, so a fixed journey scene showing this
              greyed out would depict a screen the operator never sees. */}
          {sources.length > 1 ? (
            <div className="row row--form">
              <label className="t-body" htmlFor="voice-input">
                Record from
              </label>
              <select
                id="voice-input"
                className="field field--inline"
                value={String(chosenVoiceInput)}
                disabled={recordingVoice || savingVoice}
                onChange={(event) => setChosenVoiceInput(Number(event.target.value))}
              >
                {sources.map((source, index) => (
                  <option key={`${index}-${source.label}`} value={String(index)}>
                    {source.label}
                  </option>
                ))}
              </select>
            </div>
          ) : null}
          {/* Under the count, above the controls: an operator recording a
              voice sample is looking at the number of seconds and needs the
              evidence beside it that the microphone is hearing them. Without
              it the only feedback a silent input gives is a refusal sixty
              seconds later, and they would have no idea which of the inputs
              above was the wrong one. */}
          {recordingVoice && enrolment?.metering !== undefined ? (
            <div className="enrol-meter">
              <CaptureLevel
                metering={enrolment.metering}
                device={sources[chosenVoiceInput]?.label ?? 'The open input'}
                note="If this is not moving while you talk, the wrong input is open."
              />
            </div>
          ) : null}
          <div className="row">
            <div className="row-main">
              <span className="t-body">{enrolmentWord}</span>
              <span className="t-footnote">{enrolmentDetail}</span>
            </div>
            {/* Recording puts two controls here rather than one. Stop keeps
                what was said; Discard throws it away — and an operator who
                has just recorded themselves saying the wrong thing needs the
                second one to exist, rather than having to enrol badly and
                enrol again. */}
            {recordingVoice ? (
              <div className="enrol-actions">
                <button type="button" className="btn btn--filled" onClick={enrolment?.onStop}>
                  Stop
                </button>
                <button type="button" className="btn" onClick={enrolment?.onCancel}>
                  Discard
                </button>
              </div>
            ) : (
              <button
                type="button"
                className="btn"
                onClick={() => enrolment?.onStart?.(voiceInputId)}
                disabled={enrolBlocked}
              >
                {savingVoice ? 'Saving…' : operatorEnrolled ? 'Re-record' : 'Enrol'}
              </button>
            )}
          </div>
        </div>
        {/* What this actually is, said once and not softened. The recogniser
            behind enrolment is a baseline built from the shape of a voice, not
            the learned speaker model the design calls for, and an operator told
            it "identifies you" would trust a tag it has not earned between two
            people who sound alike. */}
        <p className="t-footnote hint">
          Telling voices apart uses a built-in baseline. It separates voices
          that sound clearly different; two similar voices it may not, and it
          applies only while live transcription is running.
        </p>
        {/* Said here only when it is not already said above. What stops an
            enrolment is almost always what stops the recording — an insecure
            page, a browser with no microphone API — and the screen has
            explained that once at the top. Repeating it verbatim beside the
            Enrol button reads as a second, different problem. */}
        {enrolment?.blockedReason && enrolment.blockedReason !== unavailableReason ? (
          <p className="capture-warning t-footnote" role="status">
            {enrolment.blockedReason}
          </p>
        ) : null}
        {enrolment?.error ? (
          <p className="capture-warning t-footnote" role="alert">
            {enrolment.error}
          </p>
        ) : null}
        {operatorEnrolled && enrolment !== undefined && !enrolment.usable ? (
          // Enrolled and verifying nothing. Every other line in this section
          // reads as working, so this one is said outright.
          <p className="capture-warning t-footnote" role="status">
            This sample was recorded by a version of the voice model that is no
            longer running, so nothing is being told apart. Re-record to fix it.
          </p>
        ) : null}
      </section>
    </main>
  );
}

/**
 * `store` is injectable only so a test drives a session of its own. The
 * router mounts this with no props, and the application's session is the
 * module's — the one the consent screen may already have started.
 */
export default function CaptureRoute({ store }: { store?: CaptureStore } = {}) {
  const capture = useCapture(store);
  const beginning = useRecordingStart(store);
  // Its own device, its own lifetime: enrolling is not a meeting, and routing
  // it through the capture session would let recording a voice sample book one.
  const enrolment = useEnrolment();

  // The shell reports `idle` before a meeting starts and after it ends; the
  // screen calls that `stopped`, because "idle" describes the software and
  // "stopped" describes what the operator did.
  const state: CaptureState = capture.status.state === 'idle' ? 'stopped' : capture.status.state;

  return (
    <CaptureScreen
      state={state}
      elapsed={formatElapsed(capture.elapsedSeconds)}
      sources={capture.sources.map((source) => ({
        id: source.id,
        label: source.label,
        kind: source.degraded ? 'acoustic' : source.id === 'loopback' ? 'loopback' : 'wired',
        active: capture.status.source?.id === source.id,
      }))}
      // Read from the service rather than hardcoded. These were `false` and
      // `0` on every render, so the section described an operator who had
      // never enrolled however many times they had.
      operatorEnrolled={enrolment.status?.enrolled ?? false}
      enrolmentSeconds={Math.round(enrolment.status?.sample_seconds ?? 0)}
      enrolment={{
        phase: enrolment.phase,
        seconds: enrolment.seconds,
        maxSeconds: enrolment.maxSeconds,
        minSeconds: enrolment.status?.min_sample_seconds ?? 3,
        usable: enrolment.status?.usable ?? false,
        error: enrolment.error,
        blockedReason: enrolment.blockedReason,
        onStart: (sourceId: string) => enrolment.start(sourceId),
        // Handed over only while something is open, so a `null` level always
        // means "no reading available" and never "nothing is recording".
        metering:
          enrolment.phase === 'recording'
            ? { level: enrolment.level, waveform: enrolment.waveform }
            : undefined,
        onStop: enrolment.stop,
        onCancel: enrolment.cancel,
      }}
      onTogglePause={() => {
        void (capture.status.state === 'paused' ? capture.resume() : capture.pause());
      }}
      // Not `capture.start`: starting a recording books the meeting, because
      // the meeting begins when the recording does.
      onStart={(sourceId) => beginning.start(sourceId)}
      onCheck={(sourceId) => beginning.check(sourceId)}
      onStop={() => void capture.stop()}
      consentBlocked={beginning.consentBlocked}
      captureError={beginning.error ?? capture.error}
      // Handed over only while something is open, so `level: null` always
      // means "no reading available" and never "nothing is recording".
      metering={
        state === 'stopped'
          ? undefined
          : { level: capture.level, waveform: capture.waveform }
      }
      // `blockedReason` is the whole message now, not a flag the screen turns
      // into one: the old sentence blamed the desktop app for a page served
      // over plain HTTP, which is neither true nor something an operator can
      // act on.
      unavailableReason={capture.blockedReason ?? undefined}
      uploadNote={capture.uploadNote}
    />
  );
}
