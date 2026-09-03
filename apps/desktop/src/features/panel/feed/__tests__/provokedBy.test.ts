import { describe, expect, it } from 'vitest';

import { provokedBy } from '../provokedBy';
import type { Nudge } from '../../nudge/types';

function said(seq: number, text: string, at: number | null) {
  return { seq, text, speaker: null, at };
}

function nudge(createdAt: number): Nudge {
  return { id: 'n-1', stub: 'S', question: 'Q?', triggerReason: 'r', createdAt };
}

describe('the line a question reacted to', () => {
  it('is the last one said before it was raised', () => {
    const line = said(1, 'A few, usually.', 200);
    expect(provokedBy(nudge(250), [said(0, 'Earlier.', 100), line, said(2, 'After.', 300)])).toBe(
      line,
    );
  });

  it('includes a line raised in the same instant', () => {
    // The gate evaluates one utterance and raises the nudge from it in the
    // same tick, so equal timestamps are the ordinary case, not an edge one.
    const line = said(0, 'It has to be fast.', 500);
    expect(provokedBy(nudge(500), [line])).toBe(line);
  });

  it('is nothing when the question predates everything heard', () => {
    // A nudge restored from a previous session, or one the operator typed.
    // Naming a line it could not have reacted to would be a fabrication.
    expect(provokedBy(nudge(50), [said(0, 'Later.', 100)])).toBeNull();
  });

  it('skips a line with no clock rather than guessing where it fell', () => {
    // `at` is nullable on the wire, and attributing a question to a sentence
    // nobody can place is worse than attributing it to none.
    const placed = said(0, 'Placed.', 100);
    expect(provokedBy(nudge(400), [placed, said(1, 'Unplaced.', null)])).toBe(placed);
  });

  it('is nothing when nothing has been heard at all', () => {
    expect(provokedBy(nudge(100), [])).toBeNull();
  });
});
