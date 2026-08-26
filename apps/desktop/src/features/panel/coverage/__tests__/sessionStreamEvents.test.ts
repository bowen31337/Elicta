import { describe, expect, it } from 'vitest';
import { parseSessionStreamEvent } from '../sessionStreamEvents';

describe('parseSessionStreamEvent', () => {
  it('parses a coverage event', () => {
    const raw = JSON.stringify({
      slots: [
        { id: 'scope', label: 'Scope boundary', filled: true },
        { id: 'budget', label: 'Budget', filled: false },
      ],
      time_remaining_ms: 125_000,
    });

    expect(parseSessionStreamEvent('coverage', raw)).toEqual({
      type: 'coverage',
      coverage: {
        slots: [
          { id: 'scope', label: 'Scope boundary', filled: true },
          { id: 'budget', label: 'Budget', filled: false },
        ],
        timeRemainingMs: 125_000,
      },
    });
  });

  it('parses a coverage event with no time remaining', () => {
    const raw = JSON.stringify({ slots: [], time_remaining_ms: null });

    expect(parseSessionStreamEvent('coverage', raw)).toEqual({
      type: 'coverage',
      coverage: { slots: [], timeRemainingMs: null },
    });
  });

  it('parses a nudge event, converting wire snake_case to domain camelCase', () => {
    const raw = JSON.stringify({
      id: 'nudge-1',
      stub: 'Quantify "fast"',
      question: 'What does "fast" mean in milliseconds?',
      trigger_reason: 'vague adjective: fast',
      created_at: 1_700_000_000_000,
    });

    expect(parseSessionStreamEvent('nudge', raw)).toEqual({
      type: 'nudge',
      nudge: {
        id: 'nudge-1',
        stub: 'Quantify "fast"',
        question: 'What does "fast" mean in milliseconds?',
        triggerReason: 'vague adjective: fast',
        createdAt: 1_700_000_000_000,
        disposition: null,
      },
    });
  });

  it('returns null for an unrecognised event name', () => {
    expect(parseSessionStreamEvent('heartbeat', '{}')).toBeNull();
  });
});
