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
        <span className="coverage-indicator__count" aria-label="Sections asked about">
          — / —
        </span>
      </div>
    );
  }

  const { filled, total } = countFilledSlots(summary);
  const unfilled = summary.slots.filter((slot) => !slot.filled);

  return (
    <div
      className="coverage-indicator"
      role="group"
      aria-label={`${filled} of ${total} sections asked about`}
      /* The tooltip carries what will not fit on one line of a 420px panel:
         which sections are still open, and what the count is a count of. It
         is the second answer, not the first — an operator glancing away from
         a client for half a second cannot hover, so the line itself has to
         read without it. The second sentence is the one that matters: what
         the operator raised and what the client answered are different
         claims, and this meter spent a long time making the stronger one on
         evidence for the weaker. */
      title={
        unfilled.length === 0
          ? 'You have asked about every section. Whether the client answered is not measured here.'
          : `Still to raise: ${unfilled.map((slot) => slot.label).join(', ')}. Counts what you have asked, not what the client answered.`
      }
    >
      <span className="coverage-indicator__count">
        {filled} of {total}
      </span>
      {/* The word is the whole fix. Two bare numbers and a row of dashes
          said the same thing twice and neither said what it counted — and
          when it did acquire a word, "covered" was a claim about the client
          that nothing had measured. */}
      <span className="coverage-indicator__unit">asked about</span>
      {summary.timeRemainingMs !== null ? (
        <span className="coverage-indicator__time">
          {formatTimeRemaining(summary.timeRemainingMs)} left
        </span>
      ) : null}
    </div>
  );
}
