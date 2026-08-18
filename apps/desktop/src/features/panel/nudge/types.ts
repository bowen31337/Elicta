/**
 * A single surfaced nudge (PRD FR-6.2/6.3).
 *
 * `stub` is the 3-5 word glanceable headline; `question` is the full
 * question text rendered beneath it at smaller weight. Both fields belong
 * here (rather than being derived) because two-tier rendering is decided
 * upstream, where language and phrasing are chosen (PRD §8.2b).
 */
export interface Nudge {
  id: string;
  stub: string;
  question: string;
  triggerReason?: string;
  createdAt: number;
}
