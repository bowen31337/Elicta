import { stubFor } from '../../../services/questionStub';
import type { BankQuestion } from './types';
import './BankRail.css';

/**
 * The questions the operator meant to ask, on the screen they are already on.
 *
 * The bank was reviewable only on the Preparation screen. Mid-meeting that is
 * a different route — so a question an operator had compiled, read and
 * intended to ask was, at the moment of asking it, behind a navigation they
 * could not make while looking at a client. In practice the bank stopped
 * existing the moment the meeting started, and the panel showed only what the
 * trigger gate happened to surface: most of a requirements meeting fires no
 * trigger at all (FR-5.7).
 *
 * Keywords rather than wording, and that is the whole reason this can sit on
 * the panel at all. A compiled phrasing averages 112 characters — a sentence,
 * which has to be read. The stub is three or four words, which is taken in at
 * a glance, and glancing is the entire budget an operator has here.
 *
 * Tapping one promotes it into the panel's single prominent slot rather than
 * asking it there and then, so everything already built around a live question
 * — `Asked it`, `Park it`, `Go deeper`, the coverage tick — works on it
 * unchanged. FR-6.3 constrains prominence to one question at a time; this
 * changes which question that is, not how many.
 */

/**
 * How many the rail offers.
 *
 * A compiled bank runs to three hundred questions. All of them is a document,
 * and reading a document is exactly what this panel exists to avoid — so the
 * rail is a shortlist, and scrolling it is a deliberate act rather than the
 * only way to use it. Twelve is about two screens of chips at panel width,
 * which is as far as an operator will reasonably thumb mid-sentence.
 */
export const RAIL_LIMIT = 12;

export interface UpcomingOptions {
  /** Question ids the operator has already dealt with this meeting. */
  readonly asked: ReadonlySet<string>;
}

/**
 * The shortlist, in the bank's own ranking.
 *
 * Sorted by priority rather than left in compile order: the bank's whole claim
 * is that it knows which question earns the room's attention first, and a rail
 * that ignored that would be a list of whatever was compiled earliest.
 *
 * Already-asked questions are dropped rather than marked. This is the list of
 * what to ask *next*; a question still sitting in it after it was asked is one
 * the operator has to remember not to repeat, which is the work the panel is
 * meant to be doing for them.
 */
export function upcoming(
  questions: readonly BankQuestion[],
  { asked }: UpcomingOptions,
): readonly BankQuestion[] {
  return questions
    .filter((question) => !asked.has(question.id))
    .slice()
    .sort((left, right) => left.priority - right.priority)
    .slice(0, RAIL_LIMIT);
}

export interface BankRailProps {
  readonly questions: readonly BankQuestion[];
  /** Promote this question into the panel's prominent slot. */
  readonly onAsk: (question: BankQuestion) => void;
}

export function BankRail({ questions, onAsk }: BankRailProps) {
  if (questions.length === 0) {
    // An empty rail and a bank that never compiled look identical on screen,
    // and one of those is something the operator can still fix.
    return (
      <div className="bank-rail bank-rail--idle" role="group" aria-label="Question bank">
        <p className="t-footnote">No questions in this meeting's bank yet.</p>
      </div>
    );
  }

  return (
    <div className="bank-rail" role="group" aria-label="Question bank">
      <ul className="bank-rail-list">
        {questions.map((question) => (
          <li key={question.id}>
            <button
              type="button"
              className={
                question.inherited ? 'bank-chip bank-chip--inherited' : 'bank-chip'
              }
              // The wording, for anyone using this without seeing it — and as
              // the hover reading for anyone who wants the whole question
              // before committing the room to it. The visible label is the
              // glance; this is the question that actually gets asked.
              //
              // A carried-forward question says so here rather than only in
              // the dot beside it: the dot is a glance, and its standing —
              // the client has already left this unanswered once — is worth a
              // sentence to anyone who stops to read.
              title={
                question.inherited
                  ? `Carried forward from your last meeting — ${question.phrasing}`
                  : question.phrasing
              }
              onClick={() => onAsk(question)}
            >
              {/* A dot rather than a tint on the chip, because presence and
                  absence is a difference in shape: colour is never the only
                  indicator here. Hidden from the accessible name, which
                  already says "carried forward" in words. */}
              {question.inherited ? (
                <span className="bank-chip-mark" aria-hidden="true" />
              ) : null}
              {stubFor(question)}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
