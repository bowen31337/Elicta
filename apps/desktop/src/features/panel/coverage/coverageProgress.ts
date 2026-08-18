import type { CoverageSummary } from './types';

/** Sections filled versus the template total (PRD FR-6.5). */
export function countFilledSlots(summary: CoverageSummary): { filled: number; total: number } {
  return {
    filled: summary.slots.filter((slot) => slot.filled).length,
    total: summary.slots.length,
  };
}

/**
 * Renders a duration as `m:ss` for the persistent coverage indicator's time
 * remaining (PRD FR-6.5). Negative durations clamp to zero rather than
 * displaying a negative time, since "time remaining" past the meeting's end
 * has no meaningful value to show.
 */
export function formatTimeRemaining(ms: number): string {
  const totalSeconds = Math.max(0, Math.round(ms / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${seconds.toString().padStart(2, '0')}`;
}
