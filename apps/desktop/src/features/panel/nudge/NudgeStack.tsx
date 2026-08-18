import type { Nudge } from './types';
import './NudgeStack.css';

export interface NudgeStackProps {
  active: Nudge | null;
  history: Nudge[];
}

const MIN_HISTORY_OPACITY = 0.25;
const HISTORY_OPACITY_STEP = 0.12;
const MAX_HISTORY_OPACITY = 0.6;

/** Older entries dim further, floored so nothing disappears entirely. */
export function historyOpacity(index: number): number {
  return Math.max(MIN_HISTORY_OPACITY, MAX_HISTORY_OPACITY - index * HISTORY_OPACITY_STEP);
}

/**
 * Renders exactly one nudge prominently; every prior nudge recedes into a
 * dimmed, most-recent-first history list beneath it (PRD FR-6.3). The
 * trigger reason is shown alongside both the active nudge and every history
 * entry, not just the active one, so trust calibration survives a nudge
 * receding into history (PRD FR-5.11).
 */
export function NudgeStack({ active, history }: NudgeStackProps) {
  return (
    <div className="nudge-stack">
      {active ? (
        <article key={active.id} className="nudge-stack__active" aria-live="polite">
          <p className="nudge-stack__stub">{active.stub}</p>
          <p className="nudge-stack__question">{active.question}</p>
          <p className="nudge-stack__reason">{active.triggerReason}</p>
        </article>
      ) : (
        <p className="nudge-stack__empty">No active nudge</p>
      )}

      {history.length > 0 ? (
        <ol className="nudge-stack__history" aria-label="Prior nudges">
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
