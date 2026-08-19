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
export function NudgeStack({ active, history, operatorLanguage }: NudgeStackProps) {
  const chrome = getNudgeChromeCopy(operatorLanguage);

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
        <ol className="nudge-stack__history" aria-label={chrome.historyLabel}>
          {history.map((nudge, index) => (
            <li
              key={nudge.id}
              className="nudge-stack__history-item"
              style={{ opacity: historyOpacity(index) }}
            >
              <span className="nudge-stack__history-stub">{nudge.stub}</span>
              <span className="nudge-stack__history-reason">{nudge.triggerReason}</span>
            </li>
          ))}
        </ol>
      ) : null}
    </div>
  );
}
