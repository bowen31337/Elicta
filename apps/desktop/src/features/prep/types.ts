/**
 * The three tags a reference document can carry, and the only three the
 * service's `DocumentStatus` enum accepts. The tag is not filing: it decides
 * whether a contradiction against the document is worth interrupting for.
 */
export type DocumentStatus = 'ground truth' | 'hypothesis' | 'superseded';

/** The kinds of word the transcriber is told about, mirroring `VocabularyTermType`. */
export type VocabularyTermType = 'product_name' | 'internal_system' | 'acronym';

export interface ReferenceDocument {
  readonly id: string;
  readonly name: string;
  readonly status: DocumentStatus;
}

export interface BankCandidate {
  readonly id: string;
  readonly phrasing: string;
  /**
   * The question at a glance — what the panel puts above the phrasing during
   * the meeting, and the only tier an operator reads without breaking eye
   * contact with the client.
   *
   * `''` for a bank compiled before the compiler's stub reached the panel,
   * which is every bank compiled to date. Kept as empty rather than defaulted
   * to the phrasing: the reviewer derives a short form from it and can still
   * tell which banks would genuinely read better recompiled.
   */
  readonly stub: string;
  readonly priority: number;
  /**
   * The document this question was drafted from, or `null` where the Analyst
   * reasoned it out of the engagement rather than off a page.
   *
   * Null is a real answer here, not a missing one. It is what tells a
   * reviewer that a bank is inference rather than evidence — and a bank
   * drafted from a rich scoping pack and one reasoned out of a one-page
   * invite otherwise arrive looking identical.
   */
  readonly sourceDoc: string | null;
  /** The document statuses it rests on — `ground truth` is not `hypothesis`. */
  readonly authorityMatch: readonly string[];
}

export interface QuestionBankSection {
  readonly templateSection: string;
  readonly candidates: readonly BankCandidate[];
}

export interface QuestionBank {
  readonly sections: readonly QuestionBankSection[];
}

/** One keyterm, with the id a removal needs. */
export interface VocabularyEntry {
  readonly id: string;
  readonly term: string;
}

/** One meeting in the engagement being prepared. */
export interface PreparedMeeting {
  readonly id: string;
  readonly purpose: string | null;
  readonly captureMode: string;
  readonly state: string;
  readonly scheduledAt: string | null;
}

/**
 * How the audio reaches Elicta (PRD FR-1.1). Three, because those are the
 * three the product supports, and a free-text box here would let an operator
 * invent a fourth the capture path has never heard of.
 */
export const CAPTURE_MODES = [
  { value: 'line-in', label: 'Line-in from the meeting machine' },
  { value: 'silent-join', label: 'Silent join (loopback)' },
  { value: 'microphone', label: 'Microphone' },
] as const;
