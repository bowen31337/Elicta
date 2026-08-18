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

/**
 * A consultation thread as `useOperatorAskedThread` needs it (PRD FR-6.10).
 * Named `thread` rather than reusing `Nudge` (`../nudge/types`): FR-6.8's
 * `Park it` chip already talks about "deferring the thread", and FR-6.10 is
 * the same referent -- the surfaced question the operator can resolve
 * either by tapping a chip or by asking the client themselves. Only the
 * fields that resolution needs travel here; the two-tier stub/trigger-
 * reason shape belongs to whichever caller renders it.
 *
 * `operatorAskedAt` is null until the operator's own speech is recognised
 * as asking `question` (FR-6.10's "operator_asked marker"), at which point
 * it holds the timestamp of the utterance that resolved it -- mirroring how
 * `CoverageSlot.filled` records resolution as a fact set once and never
 * unset.
 */
export interface Thread {
  readonly id: string;
  readonly question: string;
  readonly operatorAskedAt: number | null;
}

/**
 * One finalised, operator-tagged utterance as `useOperatorAskedThread`
 * needs it. Deliberately narrow, mirroring `trigger-gate`'s
 * `FinalisedUtterance`: speaker attribution has already happened upstream
 * by the time speech reaches this hook, since FR-6.10 only ever considers
 * utterances tagged `operator` -- the same tag that `trigger-gate`'s
 * `evaluate_utterance` excludes from the gate (architecture §3.5's
 * refinement of FR-5.1). This hook is the other half of that split: the
 * operator's own speech isn't evaluated as a trigger, it's evaluated as
 * implicit input against the threads still open.
 */
export interface OperatorUtterance {
  readonly text: string;
  readonly finalizedAt: number;
}
