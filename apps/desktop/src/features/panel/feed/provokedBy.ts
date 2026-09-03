import type { SessionStreamUtterance } from '../coverage/types';
import type { Nudge } from '../nudge/types';

/**
 * The line a proposed question reacted to.
 *
 * The question and the transcript live in separate panels — the transcript
 * has hundreds of lines and needs its own scroll, and merging the two buried
 * every question in the conversation within a minute. But the connection
 * between them is the whole reason a suggestion is worth trusting: a question
 * about an unquantified amount earns its interruption because somebody just
 * said "a few". Separated without it, a question is a question from nowhere.
 *
 * So the question carries its line instead of sitting next to it, and the two
 * panels stay independent.
 *
 * The last utterance at or before the question was raised. The gate evaluates
 * one utterance and raises the nudge from it in the same tick, so "at or
 * before" is the relation, and the *last* such line is the one it saw.
 */
export function provokedBy(
  nudge: Nudge,
  transcript: readonly SessionStreamUtterance[],
): SessionStreamUtterance | null {
  let found: SessionStreamUtterance | null = null;
  for (const utterance of transcript) {
    // A line with no clock cannot be placed, and guessing would attribute a
    // question to a sentence nobody can check it against.
    if (utterance.at === null) continue;
    if (utterance.at <= nudge.createdAt) found = utterance;
    else break;
  }
  return found;
}
