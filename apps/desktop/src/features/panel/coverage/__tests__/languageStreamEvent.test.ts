import { describe, expect, it } from 'vitest';

import { parseSessionStreamEvent } from '../sessionStreamEvents';

/**
 * The frame that lights the language strip.
 *
 * The stream carried `lane`, `coverage` and `nudge` and nothing else, so the
 * panel's language list was initialised empty and stayed that way for every
 * meeting — while the service had already worked out which languages to
 * expect in the room and written them to the engagement.
 */
describe('a language frame off the session stream', () => {
  it('is parsed rather than ignored', () => {
    const event = parseSessionStreamEvent('language', '{"language":"zh","expected":true}');

    expect(event).toEqual({ type: 'language', language: 'zh', expected: true });
  });

  it('treats a frame that does not say as not expected, so it cannot over-claim', () => {
    const event = parseSessionStreamEvent('language', '{"language":"en"}');

    expect(event).toEqual({ type: 'language', language: 'en', expected: false });
  });

  it('still ignores a frame nobody has claimed yet', () => {
    expect(parseSessionStreamEvent('something-later', '{}')).toBeNull();
  });
});
