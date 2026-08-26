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
  /**
   * What the operator already did with it, when they have. Carried on the
   * wire so a reconnect — or a restart — does not present a question they
   * have asked as one still waiting.
   */
  readonly disposition?: 'taken' | 'parked' | null;
  /**
   * The template section this nudge belongs to, or `null` when it belongs to
   * none. Resolved by the service from the candidate the nudge was drawn
   * from; a template fallback fires on a phrase and names nothing.
   */
  readonly templateSection?: string | null;
}

/**
 * The two event shapes carried on `GET /api/meetings/{id}/session/stream`
 * (architecture §7: "desktop captures; phone renders nudges", carried over
 * a service-tier sync channel to the second screen).
 */
export type SessionStreamEvent =
  | { readonly type: 'lane'; readonly lane: SessionStreamLane }
  | { readonly type: 'coverage'; readonly coverage: CoverageSummary }
  | { readonly type: 'nudge'; readonly nudge: SessionStreamNudge }
  // The languages this room is expected to use (FR-2.14), sent before
  // anything is transcribed. `expected` is what keeps the strip from
  // reporting a derivation as a detection.
  | { readonly type: 'language'; readonly language: string; readonly expected: boolean };

/**
 * Confirmation that `POST /api/meetings/{id}/session/stop` closed the
 * session and flushed its final coverage summary to the service tier.
 * `stoppedAt` travels as the ISO timestamp the service assigned when it
 * closed the session, mirroring how `session/start` hands back
 * `started_at` -- the panel does not stamp its own clock for either edge.
 */
export interface SessionStopResult {
  readonly sessionId: string;
  readonly meetingId: string;
  readonly stoppedAt: string;
}

/**
 * Whether the slow lane can currently reach a model (architecture §10).
 *
 * Carried on the session stream rather than polled, because the connection
 * that would tell the panel the answer is the same one that goes quiet when
 * the answer is "no" — a poll would have to guess at a timeout, and guess
 * differently from whatever the service already knows.
 */
export interface SessionStreamLane {
  readonly modelReachable: boolean;
  /** Plain-language cause, shown to the operator when degraded. */
  readonly reason: string | null;
}
