/**
 * A single surfaced nudge (PRD FR-6.2/6.3).
 *
 * `stub` is the 3-5 word glanceable headline; `question` is the full
 * question text rendered beneath it at smaller weight. Both fields belong
 * here (rather than being derived) because two-tier rendering is decided
 * upstream, where language and phrasing are chosen (PRD §8.2b).
 *
 * `triggerReason` is required, not optional: every surfaced nudge must be
 * shown with the reason it fired so the operator can calibrate trust in the
 * system, including after it has receded into history (PRD FR-5.11).
 */
/** What the operator did with a nudge, once they have. */
export type NudgeDisposition = 'taken' | 'parked';

export interface Nudge {
  id: string;
  stub: string;
  question: string;
  triggerReason: string;
  createdAt: number;
  /**
   * Absent until the operator answers, which is a state rather than a
   * default — a nudge nobody got to is not one that was ignored. It is what
   * lets a question already asked look different from one still waiting,
   * which matters most where several carry near-identical wording.
   */
  disposition?: NudgeDisposition | null;
}
