import '../prep/screens.css';
import './capture.css';

import { ScreenEyebrow } from '../../ui/Mark';
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
  unavailableReason,
}: CaptureScreenProps) {
  const copy = STATE_COPY[state];
  const acoustic = sources.find((source) => source.active && source.kind === 'acoustic');

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
        <button
          type="button"
          className="btn btn--filled capture-toggle"
          onClick={onTogglePause}
          disabled={Boolean(unavailableReason)}
        >
          {state === 'paused' ? 'Resume recording' : 'Pause recording'}
        </button>
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
      elapsed="00:00"
      sources={capture.sources.map((source) => ({
        label: source.label,
        kind: source.degraded ? 'acoustic' : source.id === 'loopback' ? 'loopback' : 'wired',
        active: capture.status.source?.id === source.id,
      }))}
      operatorEnrolled={false}
      enrolmentSeconds={0}
      onTogglePause={() => {
        void (capture.status.state === 'paused' ? capture.resume() : capture.pause());
      }}
      unavailableReason={
        capture.available
          ? undefined
          : 'Audio capture is unavailable outside the desktop app, so nothing is being recorded.'
      }
    />
  );
}
