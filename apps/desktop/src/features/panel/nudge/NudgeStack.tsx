import type { Nudge } from './types';
import { getNudgeChromeCopy } from './chromeCopy';
import './NudgeStack.css';

export interface NudgeStackProps {
  active: Nudge | null;
  history: Nudge[];
  /**
   * BCP-47 tag for the operator's language, independent of whichever
   * language the meeting is in (PRD FR-2.26). Governs only the static
   * interface chrome this component renders itself — the empty state and
   * the history list's label. `stub` and `triggerReason` on each `Nudge`
   * are expected to already be phrased in this language by the time they
   * reach here (PRD FR-2.25), same as `question` arrives pre-phrased in
   * the meeting language (FR-2.24). Defaults to English.
   */
  operatorLanguage?: string;
  /**
   * Bring a nudge that has receded back to the front.
   *
   * Every chip acts on the active nudge, and a history entry used to be two
   * spans in a list item — not focusable, not pressable. So the moment a
   * second nudge arrived the first became unactionable for good, and in a
   * meeting where one can arrive every minute that is most of them.
   *
   * FR-6.3 constrains prominence, not reachability: one shown prominently at
   * a time. This keeps exactly one; it lets the operator choose which.
   *
   * Optional because a fixed scene has nothing to press. Given none, the
   * entries render as the plain list they were.
   */
  onSelect?: (nudge: Nudge) => void;
}

/* The floor is a contrast constraint, not a taste one.
 *
 * Element opacity multiplies whatever ink the text already has, so a dimmed
 * history entry composites toward the background twice over. Measured on this
 * product's grounds, the text stops clearing WCAG 1.4.3 below ~0.76 — the
 * earlier 0.25 floor rendered at 2.35:1, less than half the required ratio.
 *
 * The recession FR-6.3 asks for is still there: history entries step down in
 * opacity, and they are already a size below the active nudge, which is where
 * most of the visual hierarchy comes from anyway.
 */
const MIN_HISTORY_OPACITY = 0.78;
const HISTORY_OPACITY_STEP = 0.06;
const MAX_HISTORY_OPACITY = 0.95;

/** Older entries dim further, floored so every entry stays legible. */
export function historyOpacity(index: number): number {
  return Math.max(MIN_HISTORY_OPACITY, MAX_HISTORY_OPACITY - index * HISTORY_OPACITY_STEP);
}

/**
 * Renders exactly one nudge prominently; every prior nudge recedes into a
 * dimmed, most-recent-first history list beneath it (PRD FR-6.3). The
 * active nudge itself is two-tier: the glanceable stub renders above the
 * full question, at a heavier weight than it, so an operator can register
 * the gist without reading the whole question (PRD FR-6.2). The trigger
 * reason is shown alongside both the active nudge and every history
 * entry, not just the active one, so trust calibration survives a nudge
 * receding into history (PRD FR-5.11).
 *
 * The active nudge is read straight off `active` and painted whole — stub,
 * question, and trigger reason together — in the same render pass with no
 * local state, timers, or effects of its own. There is nothing in this
 * component that could reveal a nudge incrementally: streaming is disabled
 * in live mode by the component simply not having a mechanism for it (PRD
 * FR-6.4), matching the design system's "no typing animation, no streaming"
 * rule for nudge entry.
 */
/** What the operator did, in a word. Only where they did something: a mark
 *  on every row would make the marked ones invisible. */
const DISPOSITION_MARK: Record<NonNullable<Nudge['disposition']>, string> = {
  taken: 'Asked',
  parked: 'Parked',
};

/**
 * What the operator already did with this one, when they did anything.
 *
 * Rendered for every history row, interactive or not: the mark is what stops
 * a question being asked twice, and a read-only stack is exactly where the
 * operator has no other way to tell.
 */
function DispositionMark({ nudge }: { nudge: Nudge }) {
  if (!nudge.disposition) return null;
  return (
    <span className={`nudge-stack__history-mark nudge-stack__history-mark--${nudge.disposition}`}>
      {DISPOSITION_MARK[nudge.disposition]}
    </span>
  );
}

export function NudgeStack({
  active,
  history,
  operatorLanguage,
  onSelect,
}: NudgeStackProps) {
  const chrome = getNudgeChromeCopy(operatorLanguage);
  // Counted off the disposition rather than off the length: a question
  // recedes because a newer one arrived, not because it was answered, so
  // most of the history is usually still owed an answer.
  const waiting = history.filter((nudge) => !nudge.disposition).length;

  return (
    <div className="nudge-stack">
      {active ? (
        <article key={active.id} className="nudge-stack__active" aria-live="polite">
          <p className="nudge-stack__stub">{active.stub}</p>
          <p className="nudge-stack__question">{active.question}</p>
          <p className="nudge-stack__reason">{active.triggerReason}</p>
        </article>
      ) : (
        <p className="nudge-stack__empty">{chrome.emptyState}</p>
      )}

      {history.length > 0 ? (
        <>
          {/* Visible, not only an accessible name. Every entry is a button
              and nothing said so: a sighted operator saw a dim column of
              near-identical stubs under an empty state, with no heading and
              no affordance, and reported that there was no way to reach
              them. There was. A way that cannot be found is not a way. */}
          <p className="nudge-stack__history-heading t-caption">
            {onSelect ? chrome.historyHint : chrome.historyLabel}
            {/* The backlog, beside the questions it is about. Silent at zero
                rather than showing "0 still waiting": a count that is always
                on screen is one nobody sees, and there is nothing to act on
                when everything has been dealt with. */}
            {waiting > 0 ? (
              <span className="nudge-stack__history-waiting">
                {chrome.historyWaiting.replace('{n}', String(waiting))}
              </span>
            ) : null}
          </p>
          <ol className="nudge-stack__history" aria-label={chrome.historyLabel}>
          {history.map((nudge, index) => (
            <li
              key={nudge.id}
              className="nudge-stack__history-item"
              style={{ opacity: historyOpacity(index) }}
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
                     read out of context, "Second" says nothing about the
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
    </div>
  );
}
