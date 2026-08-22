import '../prep/screens.css';
import './capture.css';

import { useState } from 'react';

import { ScreenEyebrow } from '../../ui/Mark';
import { formatElapsed } from './elapsed';
import { useCapture } from './useCapture';

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
export type CaptureState = 'capturing' | 'paused' | 'stopped';

export interface CaptureSource {
  /** The device to open. Defaults to the label for the fixed journey scenes,
   *  which render a source list but never start one. */
  readonly id?: string;
  readonly label: string;
  readonly kind: 'wired' | 'loopback' | 'acoustic';
  readonly active: boolean;
}

export interface CaptureScreenProps {
  readonly state: CaptureState;
  readonly elapsed: string;
  readonly sources: readonly CaptureSource[];
  readonly operatorEnrolled: boolean;
  readonly enrolmentSeconds: number;
  /** Fired by the pause/resume control. Omitted by the fixed journey scenes. */
  readonly onTogglePause?: () => void;
  /** Opens the chosen input. Omitted by the fixed journey scenes. */
  readonly onStart?: (sourceId: string) => void;
  /** Releases the device. Omitted by the fixed journey scenes. */
  readonly onStop?: () => void;
  /** A failure from trying to open the microphone, in the operator's terms. */
  readonly captureError?: string | null;
  /** Shown when the audio backend is unreachable, so "not recording" is
   *  never left looking like a choice the operator made. */
  readonly unavailableReason?: string;
}

const STATE_COPY: Record<CaptureState, { word: string; detail: string; pill: string }> = {
  capturing: {
    word: 'Recording',
    detail: 'Audio is being captured and transcribed.',
    pill: 'pill pill--alert',
  },
  paused: {
    word: 'Paused',
    detail: 'No audio is reaching the transcriber. Nothing said now is captured.',
    pill: 'pill pill--warn',
  },
  stopped: {
    word: 'Stopped',
    detail: 'Capture has ended for this meeting.',
    pill: 'pill',
  },
};

export function CaptureScreen({
  state,
  elapsed,
  sources,
  operatorEnrolled,
  enrolmentSeconds,
  onTogglePause,
  onStart,
  onStop,
  captureError,
  unavailableReason,
}: CaptureScreenProps) {
  const copy = STATE_COPY[state];
  const acoustic = sources.find((source) => source.active && source.kind === 'acoustic');
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
        {state === 'stopped' ? (
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
                  {sources.map((source) => (
                    <option key={sourceId(source)} value={sourceId(source)}>
                      {source.label}
                    </option>
                  ))}
                </select>
              </>
            ) : null}
            <button
              type="button"
              className="btn btn--filled capture-toggle"
              onClick={() => (selected === null ? undefined : onStart?.(selected))}
              disabled={blocked || selected === null}
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
        <p className="t-footnote hint">
          Pausing takes effect immediately — there is no buffered audio to flush.
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
          <div className="row">
            <div className="row-main">
              <span className="t-body">
                {operatorEnrolled ? 'Enrolled' : 'Not enrolled'}
              </span>
              <span className="t-footnote">
                {operatorEnrolled
                  ? `${enrolmentSeconds}s sample. Your speech is tagged as yours, so a question you ask is not mistaken for a client requirement.`
                  : 'Record up to 60 seconds so your own speech can be told apart from the client’s.'}
              </span>
            </div>
            <button type="button" className="btn">
              {operatorEnrolled ? 'Re-record' : 'Enrol'}
            </button>
          </div>
        </div>
      </section>
    </main>
  );
}

export default function CaptureRoute() {
  const capture = useCapture();

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
      operatorEnrolled={false}
      enrolmentSeconds={0}
      onTogglePause={() => {
        void (capture.status.state === 'paused' ? capture.resume() : capture.pause());
      }}
      onStart={(sourceId) => void capture.start(sourceId)}
      onStop={() => void capture.stop()}
      captureError={capture.error}
      // `blockedReason` is the whole message now, not a flag the screen turns
      // into one: the old sentence blamed the desktop app for a page served
      // over plain HTTP, which is neither true nor something an operator can
      // act on.
      unavailableReason={capture.blockedReason ?? undefined}
    />
  );
}
