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

/** One input device within a capture path, for the picker. */
export interface CaptureSourceDevice {
  readonly id: string;
  readonly name: string;
  readonly isDefault: boolean;
  /** The machine's own microphone: mixes the room into one stream (FR-1.2). */
  readonly degraded: boolean;
}

export interface CaptureSource {
  /** The device to open. Defaults to the label for the fixed journey scenes,
   *  which render a source list but never start one. */
  readonly id?: string;
  readonly label: string;
  readonly kind: 'wired' | 'loopback' | 'acoustic';
  readonly active: boolean;
  /**
   * The inputs this path can be pointed at.
   *
   * Absent or empty means it takes no device — the loopback tap is the
   * machine's output — or that this build cannot enumerate them, in which case
   * the OS's own preference opens. The packaged app was in the second case
   * for every path, so it listed two kinds and no devices while the browser
   * build listed the real ones.
   */
  readonly devices?: readonly CaptureSourceDevice[];
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
  /** The current reading, or `null` where there is none. */
  readonly level: AudioLevel | null;
  /** Recent meter positions, oldest first, for the scrolling wave. */
  readonly waveform: readonly number[];
  /**
   * Whether a reading is impossible here, as opposed to not having arrived.
   *
   * The two look identical on screen and are not the same thing. Impossible
   * means the meter is gone for this session and the operator should carry
   * on without it. Not arrived means the device is still opening, or is
   * producing nothing at all — which during a meeting is the more expensive
   * of the two to misread.
   *
   * Absent means not known, which is treated as not arrived: claiming a
   * capability is missing is a stronger statement than the screen is
   * entitled to make.
   */
  readonly unmeasurable?: boolean;
}

/**
 * The enrolment control, when this render has a live one.
 *
 * Absent on the fixed journey scenes, which show the enrolled and not-enrolled
 * states as pictures and must never open a microphone to do it. Its absence is
 * what keeps the button inert there, and the screen otherwise identical.
 */
export interface CaptureEnrolment {
  readonly phase: 'idle' | 'recording' | 'saving' | 'removing';
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
  readonly onStart?: (sourceId: string, deviceId?: string) => void;
  readonly onStop?: () => void;
  readonly onCancel?: () => void;
  /**
   * Erases the enrolled print.
   *
   * Separate from re-recording, because they answer different questions. An
   * operator who has moved to a new headset wants a better sample; an operator
   * handing the laptop on, or one who simply never agreed to leaving a
   * voiceprint on it, wants the sample *gone* — and re-recording over it
   * leaves biometric material behind either way.
   */
  readonly onForget?: () => void;
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
  readonly onCheck?: (sourceId: string, deviceId?: string) => void;
  /** Why recording cannot begin for consent reasons. Disables the control. */
  readonly consentBlocked?: string | null;
  /** Opens the chosen input. Omitted by the fixed journey scenes. */
  readonly onStart?: (sourceId: string, deviceId?: string) => void;
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
    // This line has been wrong in both directions, which is the argument for
    // it claiming nothing about transcription. It said "and transcribed" when
    // nothing transcribed during a meeting; that was corrected to "after the
    // meeting, not during it", and then the live path was built and made the
    // correction false the other way. Whether speech becomes words during the
    // meeting depends on a provider configured in Settings, which this screen
    // does not know about.
    //
    // Where the audio goes is true in every configuration, and when it stops
    // going there the watchdog says so — which is the pairing that matters.
    detail: 'Audio is being captured and sent to the service for this meeting.',
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
    //
    // And which of the two claims is made matters. This said "This browser
    // cannot measure the input level" in a desktop application, to an
    // operator who never opened a browser — naming an implementation detail
    // as the cause, and asserting a permanent incapacity from the single fact
    // that nothing had arrived yet.
    return (
      <p className="capture-meter-absent t-footnote" role="status">
        {metering.unmeasurable === true
          ? 'Elicta cannot measure the input level here. Recording is unaffected.'
          : 'No input level has arrived from the microphone. Recording is unaffected.'}
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
  const removingVoice = enrolment?.phase === 'removing';
  // No live control, mid-save, mid-removal, or the browser cannot open a
  // microphone here.
  const enrolBlocked =
    enrolment === undefined ||
    savingVoice ||
    removingVoice ||
    (enrolment.blockedReason ?? null) !== null;
  // Deliberately *not* `enrolBlocked`. That gate is about the microphone — an
  // insecure page, a browser with no capture API — and removal opens no
  // device. An operator who cannot record here can still have left a print on
  // this machine, and refusing to erase it because the microphone is
  // unavailable would strand biometric material behind an unrelated limit.
  const removeBlocked = enrolment === undefined || savingVoice || removingVoice || recordingVoice;

  /**
   * Whether Remove has been pressed once and is waiting to be meant.
   *
   * Every other Remove in this product is soft — the row stops loading and
   * nothing is erased — so those ask nothing before acting. This one is the
   * exception: `DELETE /api/operator/voiceprint` pops the record, no
   * `deleted_at` exists on the table, and nothing anywhere rebuilds a
   * voiceprint from anything else. A single tap that permanently destroys the
   * only copy of something is worth a second one.
   *
   * A dialog would be the usual answer and is the wrong one here: this screen
   * is the one an operator uses mid-meeting, and it is built on the rule that
   * nothing on it steals focus (FR-1.3). So the confirmation happens in the
   * row itself, replacing the same two buttons.
   */
  const [askedToRemove, setAskedToRemove] = useState(false);
  // Derived rather than cleared in an effect, so a recording started while the
  // question was on screen cannot leave a stale "are you sure" behind it.
  const confirmingRemoval = askedToRemove && operatorEnrolled && !removeBlocked;
  const maxSeconds = enrolment?.maxSeconds ?? 60;
  const minSeconds = enrolment?.minSeconds ?? 3;

  // The count is said in words rather than only drawn: the operator is talking,
  // not watching, and the number is what tells them whether they have said
  // enough to be worth keeping.
  const enrolmentWord = recordingVoice
    ? `Recording — ${enrolment.seconds}s of ${maxSeconds}s`
    : savingVoice
      ? 'Saving your voice sample'
      : removingVoice
        ? 'Removing your voice sample'
        : confirmingRemoval
          ? 'Remove your voice sample?'
          : operatorEnrolled
            ? 'Enrolled'
            : 'Not enrolled';

  const enrolmentDetail = recordingVoice
    ? enrolment.seconds < minSeconds
      ? `Keep talking — at least ${minSeconds}s is needed. Stopping ends the recording and keeps it.`
      : 'Stopping ends the recording and keeps it. It stops on its own at the cap.'
    : savingVoice
      ? 'Working out the voiceprint. The recording itself is not kept.'
      : removingVoice
        ? 'Erasing the voiceprint. Nothing here keeps a copy of it.'
        : confirmingRemoval
          ? // Said in full, because this is the one deletion on any screen here
            // that nothing can undo.
            'This erases the voiceprint for good — nothing brings it back. Your speech stops being told apart from the client’s until you record a new sample.'
          : operatorEnrolled
            ? `${enrolmentSeconds}s sample. Your speech is tagged as yours, so a question you ask is not mistaken for a client requirement.`
            : `Record up to ${maxSeconds} seconds so your own speech can be told apart from the client’s.`;
  const blocked = Boolean(unavailableReason);
  const sourceId = (source: CaptureSource) => source.id ?? source.label;
  const [chosen, setChosen] = useState<string | null>(null);
  const selected = chosen ?? (sources.length > 0 ? sourceId(sources[0]) : null);
  const selectedSource = sources.find((source) => sourceId(source) === selected) ?? null;
  const devices = selectedSource?.devices ?? [];
  // Held per source: switching path clears it, because a device id from one
  // path means nothing to another. `null` is "whatever the system prefers",
  // which is the only thing this screen could ask for before there was a list.
  const [chosenDevice, setChosenDevice] = useState<string | null>(null);
  const device = devices.some((entry) => entry.id === chosenDevice) ? chosenDevice : null;
  const roomMicrophone =
    devices.find((entry) => entry.id === device)?.degraded ??
    (device === null && (devices.find((entry) => entry.isDefault)?.degraded ?? false));

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
                  onChange={(event) => {
                    setChosen(event.target.value);
                    // A device id belongs to one path. Carried across, it
                    // either matches nothing or — worse — matches something
                    // else, and the operator records from a device they did
                    // not pick on a screen showing the one they did.
                    setChosenDevice(null);
                  }}
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
            {devices.length > 0 ? (
              <>
                <label className="sr-only" htmlFor="capture-device">
                  Which device to record from
                </label>
                <select
                  id="capture-device"
                  className="field field--inline"
                  value={device ?? ''}
                  onChange={(event) =>
                    setChosenDevice(event.target.value === '' ? null : event.target.value)
                  }
                >
                  {/* The empty value is a real choice, not a placeholder:
                      following the system default is what an operator who
                      changes it in System Settings expects, and it is what
                      every recording did before this picker existed. */}
                  <option value="">
                    {`System default${
                      devices.find((entry) => entry.isDefault)
                        ? ` (${devices.find((entry) => entry.isDefault)?.name})`
                        : ''
                    }`}
                  </option>
                  {devices.map((entry) => (
                    <option key={entry.id} value={entry.id}>
                      {entry.name}
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
                onClick={() => (selected === null ? undefined : onCheck?.(selected, device ?? undefined))}
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
              onClick={() => (selected === null ? undefined : onStart?.(selected, device ?? undefined))}
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
        {acoustic || roomMicrophone ? (
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
            ) : confirmingRemoval ? (
              /* The question replaces the buttons that asked it, in the same
                 two positions. Keep is second and plain rather than being the
                 filled default, because the row above already says what the
                 danger is and a filled Keep would put the visual weight on
                 the outcome the operator did not just ask for. */
              <div className="enrol-actions">
                <button
                  type="button"
                  className="btn btn--danger"
                  onClick={() => {
                    setAskedToRemove(false);
                    enrolment?.onForget?.();
                  }}
                >
                  Remove for good
                </button>
                <button type="button" className="btn" onClick={() => setAskedToRemove(false)}>
                  Keep
                </button>
              </div>
            ) : operatorEnrolled ? (
              /* Two actions once there is something to act on, because
                 re-recording and removing are different intentions and
                 re-recording is not a way to get rid of a voiceprint. */
              <div className="enrol-actions">
                <button
                  type="button"
                  className="btn"
                  onClick={() => enrolment?.onStart?.(voiceInputId)}
                  disabled={enrolBlocked}
                >
                  {savingVoice ? 'Saving…' : removingVoice ? 'Removing…' : 'Re-record'}
                </button>
                <button
                  type="button"
                  className="btn btn--danger"
                  onClick={() => setAskedToRemove(true)}
                  disabled={removeBlocked}
                >
                  Remove
                </button>
              </div>
            ) : (
              <button
                type="button"
                className="btn"
                onClick={() => enrolment?.onStart?.(voiceInputId)}
                disabled={enrolBlocked}
              >
                {savingVoice ? 'Saving…' : 'Enrol'}
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
        devices: source.devices?.map((found) => ({
          id: found.id,
          name: found.name,
          isDefault: found.isDefault,
          degraded: found.degraded,
        })),
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
        onForget: enrolment.forget,
      }}
      onTogglePause={() => {
        void (capture.status.state === 'paused' ? capture.resume() : capture.pause());
      }}
      // Not `capture.start`: starting a recording books the meeting, because
      // the meeting begins when the recording does.
      onStart={(sourceId, deviceId) => beginning.start(sourceId, deviceId)}
      onCheck={(sourceId, deviceId) => beginning.check(sourceId, deviceId)}
      onStop={() => void capture.stop()}
      consentBlocked={beginning.consentBlocked}
      captureError={beginning.error ?? capture.error}
      // Handed over only while something is open, so `level: null` always
      // means "no reading available" and never "nothing is recording".
      metering={
        state === 'stopped'
          ? undefined
          : {
              level: capture.level,
              waveform: capture.waveform,
              unmeasurable: capture.levelUnmeasurable,
            }
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
