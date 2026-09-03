import { useEffect, useRef } from 'react';

import type { SessionStreamUtterance } from '../coverage/types';
import './TranscriptPanel.css';

/**
 * The meeting, written down, in a panel of its own.
 *
 * It has to be its own panel because of scale: an hour of speech is hundreds
 * of lines, and while the transcript shared a stream with the proposed
 * questions it buried every one of them inside a minute. Two panels, two
 * scrolls — the conversation can run as long as it likes without pushing the
 * question the operator is meant to ask off the screen.
 *
 * What the separation would otherwise cost is the link between them: a
 * question about an unquantified amount is worth asking because somebody just
 * said "a few", and standing alone it is a question from nowhere. That link is
 * kept by the *question* carrying its line (`provokedBy`) rather than by the
 * two sitting next to each other.
 *
 * Laid out after meetily's live transcript: an elapsed-time gutter down the
 * left, turns spaced like paragraphs rather than table rows, a comfortable
 * reading measure, and the live state trailing the last line where new text
 * appears. What Elicta keeps that meetily has not got is who said each line.
 */
export interface TranscriptPanelProps {
  readonly transcript: readonly SessionStreamUtterance[];
  /**
   * Whether anything said *could* be transcribed — is a speech credential
   * configured. Not the same as whether anything is being captured.
   */
  readonly transcribing?: boolean;
  /**
   * Whether audio is arriving right now.
   *
   * A credential is not a microphone, and the panel said otherwise: before
   * Capture was pressed it showed a pulsing "Transcribing", which asserts the
   * room is being written down when nothing is being captured at all. Three
   * states were collapsed into two, and the label claimed the strongest of
   * them.
   */
  readonly receivingAudio?: boolean;
  /**
   * How many lines are kept in the DOM. An hour of speech is thousands of
   * four-second windows, and rendering all of them spends a meeting's worth of
   * layout on text nobody is scrolled to. What happened earlier is the record
   * path's transcript, which is the authoritative one anyway.
   */
  readonly limit?: number;
  /**
   * Which recogniser is listening, as the service's wire name, or `null`
   * where it does not know.
   *
   * Shown because the model is read per window and can be changed
   * mid-meeting — which is exactly when an operator changes it, the
   * transcript being poor is the reason — and there is otherwise no evidence
   * anywhere that the change took. It is also where "this is running on my
   * machine" becomes visible in the room, which for some engagements is the
   * condition of holding the meeting at all.
   */
  readonly model?: string | null;
  /**
   * Why nothing said here will be written down, in the service's own words.
   *
   * Taken from the service rather than written here, because the two ways to
   * be unready have opposite remedies and only the service knows which
   * applies: a vendor model wants a key, a local one wants the address of a
   * server the operator is running. This panel used to state the first for
   * both cases — it told an operator running Parakeet on their own machine
   * that no speech credential was configured, which is true, irrelevant, and
   * points at the one action that would cost them money and change nothing.
   *
   * `null` falls back to the old sentence, so a panel against a service that
   * predates the field still says something rather than nothing.
   */
  readonly blockedBecause?: string | null;
}

const DEFAULT_LIMIT = 120;

/**
 * What to call each recogniser on screen.
 *
 * Written out rather than prettified from the wire name, because "nova-3" is
 * a product and "whisper-large-v3-turbo" is not a phrase. An unknown name
 * falls through as itself: a model this build has not heard of is still the
 * model that is listening, and printing it is more use than printing nothing.
 */
const MODEL_LABEL: Record<string, string> = {
  'nova-3': 'Nova-3',
  'nova-2': 'Nova-2',
  enhanced: 'Enhanced',
  'whisper-large-v3-turbo': 'Whisper large v3 turbo',
  'whisper-medium': 'Whisper medium',
  'whisper-small': 'Whisper small',
  'parakeet-tdt-0.6b-v2': 'Parakeet 0.6b',
};

/** The models that run on this machine — the same set the service holds. */
const LOCAL_MODELS = new Set([
  'whisper-large-v3-turbo',
  'whisper-medium',
  'whisper-small',
  'parakeet-tdt-0.6b-v2',
]);

/**
 * The service's reason, made to read as the start of a sentence.
 *
 * It is written lower-case there because it is a clause — it is also logged,
 * and joined into other messages — and this is the one place it leads.
 */
export function sentenceCase(reason: string): string {
  return reason.charAt(0).toUpperCase() + reason.slice(1);
}

export function modelLabel(model: string): string {
  const name = MODEL_LABEL[model] ?? model;
  // The suffix is the point for a local model: it is the difference between
  // a meeting whose audio left the building and one whose did not, and it
  // should not require knowing which product names are which.
  return LOCAL_MODELS.has(model) ? `${name} · on this machine` : name;
}

/**
 * How a speaker is labelled.
 *
 * Live verification answers exactly three things: the operator, not the
 * operator, or it could not tell. `null` is reported as unattributed rather
 * than guessed at — nobody enrolled is the ordinary deployment, and this panel
 * is read back precisely to settle who said what, so a name it cannot stand
 * behind is worse than no name.
 */
export function speakerLabel(speaker: string | null): string {
  if (speaker === null || speaker.trim() === '') return 'Unattributed';
  if (speaker === 'operator') return 'You';
  // `other` means only "not the operator" — one window compared against one
  // enrolled voiceprint, not diarisation. "Client" would be a claim: the voice
  // could belong to a second person on our own side.
  if (speaker === 'other') return 'Someone else';
  return speaker.charAt(0).toUpperCase() + speaker.slice(1);
}

/**
 * How far into the meeting something was said, as `M:SS`.
 *
 * Measured from the first line rather than a wall clock: the operator is
 * asking "how long ago was that", and a clock time makes them do the
 * subtraction. `null` where nothing said when — rendered as nothing rather
 * than `0:00`, which would claim it was said at the very start.
 */
export function elapsedStamp(at: number | null, since: number | null): string | null {
  if (at === null || since === null) return null;
  const seconds = Math.max(0, Math.round((at - since) / 1000));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}

/**
 * The three states this panel can honestly be in, and what each is called.
 *
 * They have different remedies, which is why they are three and not two:
 * an unconfigured credential is fixed in Settings, a meeting nobody has
 * started is fixed by pressing Capture, and a live one needs nothing.
 */
export type ScriptState = 'off' | 'idle' | 'live';

export function scriptState({
  transcribing,
  receivingAudio,
}: {
  readonly transcribing: boolean;
  readonly receivingAudio: boolean;
}): ScriptState {
  if (!transcribing) return 'off';
  return receivingAudio ? 'live' : 'idle';
}

const STATE_LABEL: Record<ScriptState, string> = {
  off: 'Not transcribing',
  // Named for what is missing rather than for what is fine: a configured
  // recogniser with no audio is a meeting nobody has started, and "Capture"
  // is the word on the control that starts it.
  idle: 'Not capturing',
  live: 'Transcribing',
};

export function TranscriptPanel({
  transcript,
  transcribing = true,
  receivingAudio = false,
  limit = DEFAULT_LIMIT,
  model = null,
  blockedBecause = null,
}: TranscriptPanelProps) {
  const state = scriptState({ transcribing, receivingAudio });
  const scroller = useRef<HTMLDivElement | null>(null);
  const shown = transcript.slice(-limit);
  // The meeting's own start, so trimming to `limit` never renumbers it and
  // makes the oldest line kept read 0:00.
  const since = transcript.find((entry) => entry.at !== null)?.at ?? null;

  // Follow the conversation. Written to this element's own `scrollTop` rather
  // than `scrollIntoView` on the last line: `scrollIntoView` walks up the
  // ancestor chain and can scroll more than this panel, and nothing here may
  // move the question panel or the controls beside it.
  useEffect(() => {
    const element = scroller.current;
    if (element === null) return;
    element.scrollTop = element.scrollHeight;
  }, [transcript.length]);

  return (
    <section className="script glass" aria-labelledby="script-heading">
      <header className="script-head">
        <h2 id="script-heading" className="t-section">
          Transcript
        </h2>
        {/* Beside the heading rather than trailing the last line, unlike the
            live state: this does not change while the meeting runs unless
            somebody changes it, so it is a label rather than an event. */}
        {model === null ? null : (
          <span className="script-model t-caption">{modelLabel(model)}</span>
        )}
        {/* Only the failure is pinned here. The working state trails the last
            line, where new text lands and the eye already is; a notice that
            has to be scrolled to is a notice nobody reads. */}
        {state !== 'live' ? (
          <span className={`script-state script-state--${state} t-caption`}>
            <span className={`script-dot script-dot--${state}`} aria-hidden="true" />
            {STATE_LABEL[state]}
          </span>
        ) : null}
      </header>

      {state === 'off' ? (
        <p className="script-notice t-footnote">
          {blockedBecause === null
            ? 'No speech credential is configured'
            : sentenceCase(blockedBecause)}
          , so nothing said here will be written down and no question can react
          to it. Settings.
        </p>
      ) : null}

      <div
        ref={scroller}
        className="script-body"
        role="log"
        aria-live="polite"
        aria-label="Meeting transcript"
        /* Focusable because it scrolls and holds nothing that can take focus:
           without this a keyboard user can reach every control on the panel
           and not the transcript, which is the one region that runs to
           hundreds of lines. Caught by the audit as
           `scrollable-region-focusable`, not by review. */
        tabIndex={0}
      >
        {shown.length === 0 ? (
          state === 'live' ? (
            <p className="script-idle t-subhead">Nothing heard yet.</p>
          ) : state === 'idle' ? (
            // Not "nothing heard yet", which implies something is listening.
            <p className="script-idle t-subhead">
              Nothing is being captured. Start the meeting on the Capture
              screen and what is said will appear here.
            </p>
          ) : null
        ) : (
          <ol className="script-lines">
            {shown.map((entry) => (
              <li key={entry.seq} className="script-line">
                <span className="script-at t-caption" aria-hidden="true">
                  {elapsedStamp(entry.at, since)}
                </span>
                <span
                  className={
                    entry.speaker === null
                      ? 'script-who script-who--unknown t-caption'
                      : 'script-who t-caption'
                  }
                >
                  {speakerLabel(entry.speaker)}
                </span>
                <span className="script-said t-subhead">{entry.text}</span>
              </li>
            ))}
          </ol>
        )}

        {/* The live state trails the last line, where new text lands. Only
            when it is actually live: a pulsing green dot on a meeting nobody
            has started is the very claim this panel was making wrongly. */}
        {state === 'live' ? (
          <p className="script-foot t-caption">
            <span className="script-dot script-dot--live" aria-hidden="true" />
            Transcribing
          </p>
        ) : null}
      </div>
    </section>
  );
}
