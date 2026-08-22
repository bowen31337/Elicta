import { describe, expect, it } from 'vitest';

import { formatElapsed } from '../elapsed';

/**
 * The recording clock.
 *
 * The screen had the prop, the tabular-numeral styling and a CSS class for
 * this from the day it was built, and the route passed the literal `"00:00"`.
 * Nothing computed a value, so a meeting recorded for forty minutes displayed
 * the same two zeroes it showed before it started — which reads as capture
 * having silently failed.
 */
describe('formatting a recording length', () => {
  it('starts at two zeroes, which is what the screen showed before', () => {
    expect(formatElapsed(0)).toBe('00:00');
  });

  it('pads seconds so the digits do not jump', () => {
    expect(formatElapsed(5)).toBe('00:05');
    expect(formatElapsed(65)).toBe('01:05');
  });

  it('keeps minutes past sixty rather than wrapping', () => {
    // A requirements meeting runs over an hour often enough that wrapping to
    // 00:01 would be a lie told at exactly the wrong moment.
    expect(formatElapsed(3600)).toBe('1:00:00');
    expect(formatElapsed(3661)).toBe('1:01:01');
    expect(formatElapsed(7325)).toBe('2:02:05');
  });

  it('never renders a negative or fractional clock', () => {
    // A clock is driven by wall time, and wall time can step backwards.
    expect(formatElapsed(-4)).toBe('00:00');
    expect(formatElapsed(9.7)).toBe('00:09');
  });
});
