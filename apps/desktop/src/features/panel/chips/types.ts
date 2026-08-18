/**
 * A question typed through the escape hatch (PRD FR-6.9). Distinct from a
 * `Nudge` (`../nudge/types`): this is operator-authored free text, not a
 * system-surfaced suggestion, so it carries none of the stub/trigger-reason
 * shape a nudge does.
 */
export interface EscapeHatchQuery {
  text: string;
  submittedAt: number;
}
