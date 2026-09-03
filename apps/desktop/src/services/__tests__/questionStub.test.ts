import { describe, expect, it } from 'vitest';

import { keywordStub, stubFor } from '../questionStub';

describe('the stub a compile drafted', () => {
  it('is used as it stands, because the model wrote it for this', () => {
    expect(stubFor({ stub: 'Monthly arrivals', phrasing: 'How many arrivals a month?' })).toBe(
      'Monthly arrivals',
    );
  });

  it('is still trimmed when the model ran long, rather than the card being widened', () => {
    // Instructed to five words and not enforced by the schema, because a stub
    // one word over must not fail a pass of 150 questions — the same reading
    // the citation offsets take.
    const long = 'How many arrivals do you handle across all three sites each month';
    expect(keywordStub(long).split(/\s+/).length).toBeLessThanOrEqual(5);
  });
});

describe('a bank compiled before the stub reached the panel', () => {
  // 554 candidates on a real state file, every stub empty. They are the banks
  // an operator has today, and none of them are worth a recompile to read.
  it('gets a short form derived from the phrasing', () => {
    const phrasing =
      'How many arrivals do you handle in a month, across all three sites, and '
      + 'how much does that move between peak and trough?';
    const stub = stubFor({ stub: '', phrasing });

    expect(stub.split(/\s+/).length).toBeLessThanOrEqual(5);
    expect(stub.toLowerCase()).toContain('arrivals');
  });

  it('drops the interrogative opener, which is the same on half the bank', () => {
    // "How many...", "What is...", "Which of..." — leading words that
    // distinguish nothing when every card starts with one.
    expect(keywordStub('What is the current process for booking a slot?').toLowerCase()).not.toMatch(
      /^what\b/,
    );
    expect(keywordStub('Which systems does this need to integrate with?').toLowerCase()).not.toMatch(
      /^which\b/,
    );
  });

  it('keeps the first clause, where the subject of a question actually sits', () => {
    const stub = keywordStub(
      'The pack says booking a slot should be fast. If we watched someone book a slot, what would we see?',
    );
    expect(stub.toLowerCase()).toContain('booking');
  });

  it('never returns nothing, because an empty tier is worse than a rough one', () => {
    expect(keywordStub('Why?')).not.toBe('');
    expect(stubFor({ stub: '', phrasing: 'Is it?' })).not.toBe('');
  });

  it('leaves no dangling punctuation to read as a typo on a card', () => {
    expect(keywordStub('So, what happens when a vessel is late,')).not.toMatch(/[,;:—-]$/);
  });
});
