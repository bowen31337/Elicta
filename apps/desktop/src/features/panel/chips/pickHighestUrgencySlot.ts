import type { CoverageSlot, CoverageSummary } from '../coverage/types';

/**
 * Picks the unfilled section the `What am I missing?` chip should surface
 * (PRD FR-6.6; coverage urgency per architecture §3.7 / PRD FR-8.2:
 * "unfilled section × time pressure").
 *
 * The core's `coverage::urgency` scorer weighs an empty section above a
 * partially-filled one, then scales by how little meeting time is left. The
 * wire contract this panel receives (`CoverageSlot.filled`) collapses that
 * down to a single boolean and carries no per-slot fill gradient, and
 * `timeRemainingMs` applies the same multiplier to every unfilled slot
 * alike -- so every unfilled slot ties under that formula given what this
 * panel actually has. Template order is the tiebreaker, and doubles as the
 * only ranking signal available here: the first unfilled slot in
 * `summary.slots` is the highest-urgency one.
 */
export function pickHighestUrgencySlot(summary: CoverageSummary): CoverageSlot | null {
  return summary.slots.find((slot) => !slot.filled) ?? null;
}
