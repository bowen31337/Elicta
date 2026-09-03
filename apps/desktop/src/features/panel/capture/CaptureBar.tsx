import { useEffect, useState } from 'react';

import { formatElapsed } from '../../capture/elapsed';
import './CaptureBar.css';

/**
 * What the microphone is doing, on the screen the operator is already on.
 *
 * Capture could only be started, watched or stopped from its own screen, so
 * mid-meeting the one question an operator asks most — *is this still
 * recording?* — cost a navigation away from the client's face. This is that
 * answer, docked to the live panel: the state, the running time, and the ways
 * to interrupt it.
 *
 * Shaped after meetily's recording bar — a state line above a floating pill,
 * the wave at the left, elapsed time, then Pause and Stop.
 *
 * **The waveform is real, and this component refused to draw one for a
 * build.** The reasoning was that the panel is a second screen (architecture
 * §7: the desktop captures, the phone renders) with no access to the audio, so
 * a wave drawn from nothing would assert a live microphone — the exact lie
 * this bar exists to stop telling. That is true of a second screen and wrong
 * about the ordinary case: `services/captureSession` is one store per bundle,
 * so when the capture is running in this window the panel already holds the
 * same levels the Capture screen draws. The rule that survives is the honest
 * half — `waveform` is empty whenever there is no local reading, and an empty
 * waveform draws nothing at all rather than a flat line, because a flat line
 * is a claim of silence and absence is not silence.
 *
 * The clock has the same shape of problem. `since` is the service's view of
 * when this run began, which is all a second screen has; it is wall-clock, and
 * wall-clock over-counts a recording that was paused. `elapsedSeconds` comes
 * from the local store, which does not count paused time, so it wins wherever
 * there is one.
 */
export interface CaptureBarProps {
  /** Whether audio is arriving right now. */
  readonly capturing: boolean;
  /**
   * When this run of capture began, in milliseconds since the epoch, or
   * `null` when nothing is being captured. The recording's clock, not the
   * meeting's — and wall-clock, so `elapsedSeconds` beats it where there is
   * one.
   */
  readonly since: number | null;
  /**
   * The local session's own clock, which excludes time spent paused. `null`
   * or absent when the capture is not running in this window.
   */
  readonly elapsedSeconds?: number | null;
  /**
   * Recent input levels, oldest first, each 0–1. Empty when there is no local
   * reading to draw — a second screen, or a device that cannot be metered.
   */
  readonly waveform?: readonly number[];
  /**
   * Whether anything *could* be transcribed — is a speech credential
   * configured. Audio is still recorded without one; only the live
   * transcription and the questions that react to it are lost.
   */
  readonly transcribing?: boolean;
  /** Paused: the device is held, and nothing is being recorded through it. */
  readonly paused?: boolean;
  /** Hold the recording. Absent where there is no local session to hold. */
  readonly onPause?: () => void;
  /** Take it off hold. */
  readonly onResume?: () => void;
  /** End the meeting. Absent where there is nothing to end. */
  readonly onStop?: () => void;
  /** True while the stop request is in flight. */
  readonly stopping?: boolean;
  /**
   * True when the last stop did not go through.
   *
   * Shown, and that is the whole point of it. Stopping failed on every press
   * for as long as this bar existed — the route it posts to was never mounted
   * in the service — and the panel had nowhere to put that, so the button
   * reverted to enabled and the clock carried on. A control whose failure is
   * indistinguishable from its success is a control an operator presses
   * again, and then presses harder.
   */
  readonly stopFailed?: boolean;
  /** Overridable so a test and a fixed scene need no wall clock. */
  readonly now?: () => number;
}

/**
 * How long the bar waits before re-reading the clock.
 *
 * One second, because it displays seconds. Anything faster redraws a value
 * that has not changed; anything slower makes the clock visibly stutter, and a
 * stuttering clock reads as a stalling recording.
 */
const TICK_MS = 1000;

/**
 * How many of the store's levels this bar draws.
 *
 * The store keeps 48, which is right for the Capture screen's full-width
 * meter and far too many for a pill. Drawn all 48 at the width below, each bar
 * fell under a pixel — so they stopped shrinking at their floor and the row
 * **overflowed its own box and painted across the clock and both buttons**.
 * That is the failure mode of `flex: 1 1 0` with a `min-inline-size`: a flex
 * row does not compress past the floor, it overflows, and an overflowing row
 * of absolutely-tiny elements does not look like a layout bug — it looks like
 * a glitching waveform.
 *
 * Slicing here rather than only widening there, because the width available
 * to this pill is not something this component gets to decide.
 */
const BARS = 28;

/** What the bar is doing, in the operator's words. */
export function stateLabel(capturing: boolean, paused: boolean): string {
  if (paused) return 'Paused';
  // "Listening", not "Recording": the microphone being open is the thing an
  // operator is checking for, and it is the claim this bar can stand behind
  // from where it sits.
  return capturing ? 'Listening…' : 'Not recording';
}

export function CaptureBar({
  capturing,
  since,
  elapsedSeconds = null,
  waveform = [],
  transcribing = true,
  paused = false,
  onPause,
  onResume,
  onStop,
  stopping = false,
  stopFailed = false,
  now = () => Date.now(),
}: CaptureBarProps) {
  const [tick, setTick] = useState(() => now());

  // Only while something is running, and not while it is held. A timer on a
  // settled screen wakes the panel every second of every meeting to redraw a
  // dash, and one on a paused recording redraws a number that is frozen.
  useEffect(() => {
    if (!capturing || paused || since === null) return;
    const timer = window.setInterval(() => setTick(Date.now()), TICK_MS);
    return () => window.clearInterval(timer);
  }, [capturing, paused, since]);

  const elapsed =
    elapsedSeconds !== null && elapsedSeconds !== undefined
      ? formatElapsed(elapsedSeconds)
      : capturing && since !== null
        ? formatElapsed(Math.max(0, (Math.max(tick, now()) - since) / 1000))
        : null;

  const live = capturing && !paused;

  return (
    <div className="capture-bar-dock">
      {/* The state reads above the pill rather than inside it, which is what
          keeps the pill to controls and a number. Never colour alone: the dot
          repeats what the word says, for the operator who cannot tell this
          red from this grey. */}
      <p className="capture-bar-state t-caption">
        <span
          className={live ? 'capture-bar__dot capture-bar__dot--live' : 'capture-bar__dot'}
          aria-hidden="true"
        />
        {stateLabel(capturing, paused)}
        {/* Audio is still captured without a speech credential — only the
            live transcript and the questions that react to it are lost.
            Saying which keeps an operator from stopping a recording that is
            working perfectly. */}
        {capturing && !transcribing ? (
          <span className="capture-bar__note">Not transcribing</span>
        ) : null}
        {stopFailed ? (
          // Red and announced, because it is a failed action rather than a
          // state: the operator asked for the recording to end and it has
          // not. The microphone is released first and separately, so this
          // says the meeting is still open in the service — not that the room
          // is still being recorded.
          <span className="capture-bar__failed" role="alert">
            Stop failed — try again
          </span>
        ) : null}
      </p>

      <section className="capture-bar glass" aria-label="Recording">
        {/* Decorative: it is the same reading as the state above it, and a
            wave announced bar by bar would be unusable. Absent rather than
            flat when there is nothing to draw — see the note on the props. */}
        {waveform.length > 0 ? (
          <div className="capture-bar__wave" aria-hidden="true">
            {waveform.slice(-BARS).map((bar, index) => (
              <span
                key={index}
                className="capture-bar__bar"
                style={{ height: `${Math.max(6, bar * 100)}%` }}
              />
            ))}
          </div>
        ) : null}

        {elapsed === null ? null : (
          <time className="capture-bar__elapsed t-footnote" aria-label="Recording time">
            {elapsed}
          </time>
        )}

        {onPause === undefined && onResume === undefined ? null : (
          <button
            type="button"
            className="capture-bar__button"
            onClick={paused ? onResume : onPause}
            disabled={!capturing || stopping}
          >
            <span className="capture-bar__glyph" aria-hidden="true">
              {paused ? (
                <svg viewBox="0 0 12 12" width="11" height="11" focusable="false">
                  <path d="M2.5 1.6 10 6l-7.5 4.4z" fill="currentColor" />
                </svg>
              ) : (
                <svg viewBox="0 0 12 12" width="11" height="11" focusable="false">
                  <rect x="2.2" y="1.8" width="2.9" height="8.4" rx="0.9" fill="currentColor" />
                  <rect x="6.9" y="1.8" width="2.9" height="8.4" rx="0.9" fill="currentColor" />
                </svg>
              )}
            </span>
            {paused ? 'Resume' : 'Pause'}
          </button>
        )}

        {onStop === undefined ? null : (
          <button
            type="button"
            className="capture-bar__button capture-bar__button--stop"
            onClick={onStop}
            disabled={!capturing || stopping}
          >
            <span className="capture-bar__glyph" aria-hidden="true">
              <svg viewBox="0 0 12 12" width="11" height="11" focusable="false">
                <rect x="2" y="2" width="8" height="8" rx="1.4" fill="currentColor" />
              </svg>
            </span>
            {stopping ? 'Stopping…' : 'Stop'}
          </button>
        )}
      </section>
    </div>
  );
}
