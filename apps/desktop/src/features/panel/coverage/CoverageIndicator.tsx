import { countFilledSlots, formatTimeRemaining } from './coverageProgress';
import type { CoverageSummary } from './types';
import './CoverageIndicator.css';

export interface CoverageIndicatorProps {
  summary: CoverageSummary | null;
}

/**
 * The persistent coverage indicator (PRD FR-6.5): sections filled out of
 * the template total, plus time remaining in the meeting. It stays visible
 * for the whole meeting rather than living in the transient nudge feed, so
 * a coverage gap is always one glance away regardless of which nudge is
 * currently showing -- on the desktop panel or the second-screen client.
 */
export function CoverageIndicator({ summary }: CoverageIndicatorProps) {
  if (summary === null) {
    return (
      <div className="coverage-indicator coverage-indicator--pending">
        <span className="coverage-indicator__count" aria-label="Sections filled">
          — / —
        </span>
      </div>
    );
  }

  const { filled, total } = countFilledSlots(summary);

  return (
    <div className="coverage-indicator">
      <span className="coverage-indicator__count" aria-label="Sections filled">
        {filled} / {total}
      </span>
      {summary.timeRemainingMs !== null ? (
        <span className="coverage-indicator__time" aria-label="Time remaining">
          {formatTimeRemaining(summary.timeRemainingMs)}
        </span>
      ) : null}
    </div>
  );
}
