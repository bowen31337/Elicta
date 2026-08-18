import type { Thread } from './types';

/**
 * Words too common to signal that a thread's question was actually asked.
 * Filtering them out is what keeps `isOperatorAskingThreadQuestion` from
 * matching on shared filler alone ("what", "the", "you") when the operator
 * is talking about something else entirely.
 */
const STOPWORDS = new Set([
  'a',
  'about',
  'am',
  'an',
  'and',
  'any',
  'are',
  'as',
  'at',
  'be',
  'been',
  'by',
  'can',
  'could',
  'did',
  'do',
  'does',
  'for',
  'from',
  'had',
  'has',
  'have',
  'how',
  'i',
  'if',
  'in',
  'is',
  'it',
  'its',
  'me',
  'my',
  'of',
  'on',
  'or',
  'our',
  'over',
  'so',
  'that',
  'the',
  'their',
  'them',
  'there',
  'this',
  'to',
  'was',
  'we',
  'were',
  'what',
  'when',
  'where',
  'which',
  'who',
  'will',
  'with',
  'would',
  'you',
  'your',
]);

function significantWords(text: string): string[] {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, ' ')
    .split(/\s+/)
    .filter((word) => word.length > 0 && !STOPWORDS.has(word));
}

/**
 * Decides whether `utteranceText` -- one finalised, operator-tagged
 * utterance -- is the operator asking the client `thread.question` (PRD
 * FR-6.10). The meeting is the input channel, not a transcript to run NLP
 * over: this stays a deterministic word-overlap check, mirroring
 * `trigger-gate`'s lexicon matching rather than reaching for a model. A
 * question's stopwords (the "what", "the", "you" that any sentence shares)
 * carry no signal, so the check strips them and asks whether every
 * remaining, content-bearing word from the question surfaces somewhere in
 * the utterance -- verbatim recitation and reasonable paraphrase both pass,
 * an unrelated remark does not.
 *
 * A question with no significant words of its own (all stopwords, or
 * empty) can never be confirmed this way -- there is nothing distinctive to
 * match against, so it always reports `false` rather than matching
 * anything the operator says.
 */
export function isOperatorAskingThreadQuestion(utteranceText: string, thread: Thread): boolean {
  const questionWords = significantWords(thread.question);
  if (questionWords.length === 0) {
    return false;
  }

  const utteranceWords = new Set(significantWords(utteranceText));
  return questionWords.every((word) => utteranceWords.has(word));
}
