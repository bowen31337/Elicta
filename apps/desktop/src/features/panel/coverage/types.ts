/**
 * One requirements-template section tracked by the live coverage tracker
 * (PRD FR-6.5, FR-6.7). `filled` reflects whether at least one sourced
 * client statement has landed against it; that decision is made by the
 * coverage tracker in the core, this panel only ever renders it.
 */
export interface CoverageSlot {
  readonly id: string;
  readonly label: string;
  readonly filled: boolean;
}

/**
 * The persistent coverage indicator's full state (PRD FR-6.5): every
 * tracked section plus time remaining in the meeting. `timeRemainingMs`
 * travels as a duration rather than a deadline timestamp, so the panel
 * never has to reason about clock skew between the service and the device
 * it renders on -- the second-screen client included.
 */
export interface CoverageSummary {
  readonly slots: readonly CoverageSlot[];
  readonly timeRemainingMs: number | null;
}

/**
 * A nudge as it arrives on the session stream. Defined independently of
 * `panel/nudge`'s `Nudge` type rather than imported, because this feature
 * owns the stream's wire contract, not the nudge domain -- a caller that
 * wants to feed these into the nudge queue converts at the composition
 * root, not here.
 */
export interface SessionStreamNudge {
  readonly id: string;
  readonly stub: string;
  readonly question: string;
  readonly triggerReason: string;
  readonly createdAt: number;
}

/**
 * The two event shapes carried on `GET /api/meetings/{id}/session/stream`
 * (architecture §7: "desktop captures; phone renders nudges", carried over
 * a service-tier sync channel to the second screen).
 */
export type SessionStreamEvent =
  | { readonly type: 'coverage'; readonly coverage: CoverageSummary }
  | { readonly type: 'nudge'; readonly nudge: SessionStreamNudge };
