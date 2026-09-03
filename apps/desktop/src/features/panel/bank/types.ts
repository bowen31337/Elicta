/**
 * One question from the meeting's bank, as the panel holds it.
 *
 * Defined here rather than imported from the prep screen's types: this feature
 * owns what the panel needs of a candidate, which is the short form, the
 * wording and enough to record having asked it. The bank's own shape carries
 * a good deal more — provenance, authority, trigger types — that no decision
 * on this screen turns on.
 */
export interface BankQuestion {
  readonly id: string;
  /** The wording, read aloud by the operator. */
  readonly phrasing: string;
  /**
   * The compiled short form, or `''` for a bank compiled before the stub
   * reached the panel. Empty is a real state and stays one: the rail derives
   * keywords rather than the service inventing a stub, so a bank that would
   * genuinely read better recompiled can still be told apart from one that
   * would not.
   */
  readonly stub: string;
  /** Lower ranks higher, matching the bank's own convention. */
  readonly priority: number;
  readonly templateSection: string;
  /** Carried forward from a prior meeting's open question. */
  readonly inherited: boolean;
}
