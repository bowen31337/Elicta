/**
 * The short form of a question — what the panel puts above the phrasing.
 *
 * The panel has always been built in two tiers: a glanceable stub over the
 * full question, heavier than it, because an operator mid-meeting is looking
 * at a client rather than at this. The compiler has always been asked for the
 * stub. It arrived empty every time — the field was never declared on either
 * `BankCandidate`, and pydantic drops an undeclared keyword in silence — so on
 * a real state file 554 candidates carried 554 empty stubs, against phrasings
 * averaging 112 characters and reaching 240.
 *
 * That is fixed at the source, but a fix at the source only helps a bank
 * compiled after it. Every bank an operator already has was drafted without
 * one, and a recompile is minutes of model calls and a real bill. So the short
 * form is derived here when the compile did not supply one: the operator's
 * existing banks read short today, and nothing had to be recompiled to make
 * them.
 *
 * Derivation is deliberately keywords rather than a shortened sentence. A
 * trimmed sentence still has to be *read*; keywords are taken in at a glance,
 * which is the entire difference the tier exists for. A model-written stub
 * still reads better than a derived one, which is why a supplied stub is
 * always preferred and never re-derived.
 */

/**
 * Words that distinguish nothing on a card where every entry is a question.
 *
 * Interrogative openers are the worst of them: half a bank begins "How many",
 * "What is" or "Which of", so a stub that keeps them spends its first two
 * words saying only that this is a question — which the operator can see.
 */
const STOPWORDS = new Set([
  // interrogatives and their auxiliaries
  'how', 'what', 'which', 'who', 'whom', 'whose', 'when', 'where', 'why',
  'do', 'does', 'did', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
  'can', 'could', 'will', 'would', 'shall', 'should', 'may', 'might', 'must',
  'have', 'has', 'had',
  // articles, conjunctions, pronouns
  'a', 'an', 'the', 'and', 'or', 'but', 'so', 'if', 'then', 'than', 'that',
  'this', 'these', 'those', 'it', 'its', 'we', 'us', 'our', 'you', 'your',
  'they', 'them', 'their', 'i', 'me', 'my', 'he', 'she', 'his', 'her',
  // prepositions and common filler
  'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'from', 'as', 'into',
  'about', 'over', 'under', 'across', 'through', 'between', 'during',
  'there', 'here', 'any', 'some', 'all', 'each', 'every', 'much', 'many',
  'more', 'most', 'other', 'else', 'own', 'same', 'just', 'only', 'also',
  'not', 'no', 'nor', 'too', 'very', 'now', 'still', 'yet', 'like',
]);

/**
 * At most five, because that is what the compiler is instructed to draft and
 * the two forms should not disagree about what "short" means. Five is already
 * the ceiling rather than the target: three reads better than five, and the
 * derivation stops early whenever the phrasing gives it the chance.
 */
const MAX_WORDS = 5;

/** Trailing punctuation left by a mid-clause cut, which reads as a typo. */
const DANGLING = /[\s,;:.!?—–-]+$/;

/**
 * The first sentence of a phrasing, which is where its subject sits.
 *
 * Many drafted questions open by naming the ground they stand on — "The pack
 * says booking a slot should be fast. If we watched someone book one…" — and
 * that opening clause is what identifies the question on a card. The
 * interrogative half is the part every card has.
 */
function firstSentence(phrasing: string): string {
  const [first] = phrasing.split(/(?<=[.!?])\s+/, 1);
  return (first ?? phrasing).trim() || phrasing.trim();
}

function words(text: string): string[] {
  return text
    .split(/\s+/)
    .map((word) => word.replace(/^[^\p{L}\p{N}]+|[^\p{L}\p{N}%]+$/gu, ''))
    .filter((word) => word.length > 0);
}

/**
 * Reduce a question to the keywords that identify it.
 *
 * Never returns an empty string. A phrasing with no content words at all
 * ("Why?", "Is it?") falls back to itself unpunctuated: a rough tier is worth
 * more than a blank one, and blank is what the panel has been showing.
 */
export function keywordStub(phrasing: string): string {
  const sentence = firstSentence(phrasing);
  const kept = words(sentence)
    .filter((word) => !STOPWORDS.has(word.toLowerCase()))
    .slice(0, MAX_WORDS);

  if (kept.length === 0) {
    // Every word was a stopword, which happens on the shortest questions —
    // exactly the ones that least need shortening.
    return words(sentence).slice(0, MAX_WORDS).join(' ').replace(DANGLING, '') || phrasing.trim();
  }

  const stub = kept.join(' ').replace(DANGLING, '');
  // Sentence case rather than the original's: a keyword lifted from mid-clause
  // arrives lowercase, and a card of stubs that each start differently reads
  // as inconsistent rather than as faithful.
  return stub.charAt(0).toUpperCase() + stub.slice(1);
}

export interface HasQuestionText {
  /** What the compile drafted, or `''` for a bank compiled before it did. */
  readonly stub?: string | null;
  /** The full wording, read aloud by the operator. */
  readonly phrasing: string;
}

/**
 * The short form to show for one question.
 *
 * A stub the compile supplied is preferred whole and never re-derived — the
 * model wrote it for this purpose and reads better than anything lifted
 * mechanically out of a sentence. It is still capped, because the instruction
 * to draft five words is an instruction rather than a schema constraint: a
 * stub one word over must not fail a pass of a hundred and fifty questions,
 * which is the same reading the citation offsets take.
 */
export function stubFor({ stub, phrasing }: HasQuestionText): string {
  const supplied = (stub ?? '').trim();
  if (supplied) {
    return words(supplied).length > MAX_WORDS ? keywordStub(supplied) : supplied;
  }
  return keywordStub(phrasing);
}
