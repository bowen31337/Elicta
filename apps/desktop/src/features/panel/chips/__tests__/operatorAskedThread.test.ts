import { describe, expect, it } from 'vitest';
import { isOperatorAskingThreadQuestion } from '../operatorAskedThread';
import type { Thread } from '../types';

const thread: Thread = {
  id: 'budget',
  question: 'What is your budget for this project?',
  operatorAskedAt: null,
};

describe('isOperatorAskingThreadQuestion', () => {
  it('matches a verbatim recitation of the question', () => {
    expect(isOperatorAskingThreadQuestion('What is your budget for this project?', thread)).toBe(
      true,
    );
  });

  it('matches a reasonable paraphrase that keeps the content words', () => {
    expect(
      isOperatorAskingThreadQuestion(
        "So, what's the budget looking like for this project?",
        thread,
      ),
    ).toBe(true);
  });

  it('is case- and punctuation-insensitive', () => {
    expect(isOperatorAskingThreadQuestion('WHAT IS YOUR BUDGET FOR THIS PROJECT', thread)).toBe(
      true,
    );
  });

  it('does not match an unrelated remark', () => {
    expect(
      isOperatorAskingThreadQuestion('Let me pull up the agenda for today.', thread),
    ).toBe(false);
  });

  it('does not match when only some content words are present', () => {
    expect(isOperatorAskingThreadQuestion('This project is going well so far.', thread)).toBe(
      false,
    );
  });

  it('never matches a question with no significant words', () => {
    const emptyThread: Thread = { id: 'filler', question: 'What is it?', operatorAskedAt: null };
    expect(isOperatorAskingThreadQuestion('What is it exactly?', emptyThread)).toBe(false);
  });
});
