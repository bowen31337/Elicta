import type { SessionStreamUtterance } from '../coverage/types';
import { getNudgeChromeCopy } from '../nudge/chromeCopy';
import type { Nudge } from '../nudge/types';
import { provokedBy } from './provokedBy';
// The nudge card's type scale, the receded row's layout and the trigger
// reason's ink are solved in this stylesheet. This panel reuses those class
// names rather than re-solving them, so it owns the import now that the
// component it was written for is gone — without it the stub stops being
// prominent and the receded rows run their two lines together, which is
// exactly what shipped for one build.
import '../nudge/NudgeStack.css';
import './QuestionPanel.css';

/**
 * What to ask, and what it is about.
 *
 * A panel of its own, beside the transcript rather than inside it. Merged into
 * one stream the questions were buried by the conversation within a minute —
 * an hour of speech is hundreds of lines and every one of them pushed the
 * question the operator is meant to ask further up the scroll.
 *
 * What the separation would otherwise cost is the reason to trust a
 * suggestion. A question about an unquantified amount earns its interruption
 * because somebody just said "a few"; standing alone it is a question from
 * nowhere, and judging it means holding the last thirty seconds in your head —
 * which is the work this product exists to do for you. So each question
 * carries the line it reacted to (`provokedBy`) instead of relying on being
 * next to it.
 *
 * That quoted line is also the only place the operator can see the failure
 * this product is meant to avoid: with no enrolled voiceprint the gate cannot
 * tell who spoke, so it will sometimes react to the operator's own sentence.
 * Quoted, that is obvious. Unquoted it is invisible.
 *
 * FR-6.3 is unchanged: exactly one question is prominent, the rest recede and
 * stay one press from coming back.
 */
export interface QuestionPanelProps {
  readonly active: Nudge | null;
  readonly history: readonly Nudge[];
  /** For quoting the line each question reacted to. */
  readonly transcript: readonly SessionStreamUtterance[];
  /** BCP-47 tag for the operator's own interface language (FR-2.26). */
  readonly operatorLanguage?: string;
  /**
   * Bring a question that has receded back to the front. Optional, because a
   * fixed scene has nothing to press.
   */
  readonly onSelect?: (nudge: Nudge) => void;
}

/* The floor is a contrast constraint, not a taste one.
 *
 * Element opacity multiplies whatever ink the text already has, so a receded
 * entry composites toward the background twice over. Measured on this
 * product's grounds, the text stops clearing WCAG 1.4.3 below ~0.76.
 */
const MIN_OPACITY = 0.78;
const OPACITY_STEP = 0.06;
const MAX_OPACITY = 0.95;

/** Older questions dim further, floored so every one stays legible. */
export function recededOpacity(stepsBack: number): number {
  return Math.max(MIN_OPACITY, MAX_OPACITY - stepsBack * OPACITY_STEP);
}

/** What the operator did with it, in a word. Only where they did something:
 *  a mark on every row would make the marked ones invisible. */
const DISPOSITION_MARK: Record<NonNullable<Nudge['disposition']>, string> = {
  taken: 'Asked',
  parked: 'Parked',
};

function DispositionMark({ nudge }: { nudge: Nudge }) {
  if (!nudge.disposition) return null;
  return (
    <span className={`nudge-stack__history-mark nudge-stack__history-mark--${nudge.disposition}`}>
      {DISPOSITION_MARK[nudge.disposition]}
    </span>
  );
}

/** The line the question reacted to, quoted under it. */
function Provocation({
  nudge,
  transcript,
}: {
  readonly nudge: Nudge;
  readonly transcript: readonly SessionStreamUtterance[];
}) {
  const line = provokedBy(nudge, transcript);
  if (line === null) return null;
  return (
    <p className="ask-because t-caption">
      <span className="ask-because-mark" aria-hidden="true" />
      <q className="ask-because-said">{line.text}</q>
    </p>
  );
}

export function QuestionPanel({
  active,
  history,
  transcript,
  operatorLanguage,
  onSelect,
}: QuestionPanelProps) {
  const chrome = getNudgeChromeCopy(operatorLanguage);
  // Counted off the disposition rather than the length: a question recedes
  // because a newer one arrived, not because it was answered, so most of the
  // history is usually still owed an answer.
  const waiting = history.filter((nudge) => !nudge.disposition).length;

  return (
    <section className="ask" aria-label="Questions to ask">
      {active ? (
        <article className="nudge-stack__active" aria-live="polite">
          <p className="nudge-stack__stub">{active.stub}</p>
          <p className="nudge-stack__question">{active.question}</p>
          {/* FR-5.11: the reason travels with the question wherever it is
              shown, so trust survives it receding. */}
          <p className="nudge-stack__reason">{active.triggerReason}</p>
          <Provocation nudge={active} transcript={transcript} />
        </article>
      ) : (
        <p className="nudge-stack__empty">{chrome.emptyState}</p>
      )}

      {history.length > 0 ? (
        <>
          {/* Visible, not only an accessible name. Every entry is a button and
              nothing said so: a sighted operator saw a dim column of
              near-identical stubs with no heading and no affordance, and
              reported there was no way to reach them. A way that cannot be
              found is not a way. */}
          <p className="ask-earlier-heading t-caption">
            {onSelect ? chrome.historyHint : chrome.historyLabel}
            {/* Silent at zero rather than showing "0 still waiting": a count
                always on screen is one nobody reads. */}
            {waiting > 0 ? (
              <span className="nudge-stack__history-waiting">
                {chrome.historyWaiting.replace('{n}', String(waiting))}
              </span>
            ) : null}
          </p>
          <ol
            className="ask-earlier"
            aria-label={chrome.historyLabel}
            /* Scrolls, and with no `onSelect` its rows are plain text with
               nothing to tab to — the same `scrollable-region-focusable`
               failure the transcript had. */
            tabIndex={onSelect === undefined ? 0 : undefined}
          >
            {history.map((nudge, index) => (
              <li
                key={nudge.id}
                className="ask-earlier-item nudge-stack__history-item"
                style={{ opacity: recededOpacity(index) }}
              >
                {onSelect === undefined ? (
                  <>
                    <span className="nudge-stack__history-stub">
                      {nudge.stub}
                      <DispositionMark nudge={nudge} />
                    </span>
                    <span className="nudge-stack__history-reason">{nudge.triggerReason}</span>
                  </>
                ) : (
                  <button
                    type="button"
                    className="nudge-stack__history-button"
                    /* Named by what pressing it does, not by the stub alone:
                       read out of context "Second" says nothing about the
                       consequence, and several stubs can be identical. */
                    aria-label={`Bring back ${nudge.stub}`}
                    onClick={() => onSelect(nudge)}
                  >
                    <span className="nudge-stack__history-stub">
                      {nudge.stub}
                      <DispositionMark nudge={nudge} />
                    </span>
                    <span className="nudge-stack__history-reason">{nudge.triggerReason}</span>
                  </button>
                )}
              </li>
            ))}
          </ol>
        </>
      ) : null}
    </section>
  );
}
