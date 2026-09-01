import { describe, expect, it } from 'vitest';

import { STAGE_SECONDS, compileFraction } from '../compileFraction';

/**
 * How far along a compile is, in a number that can move every frame.
 *
 * The service reports stage boundaries and nothing between them, and those
 * boundaries are about twenty seconds, twenty seconds, and two hundred
 * seconds apart. A bar that can only step at them stands still for minutes —
 * which is the state it exists to tell apart from being stuck, so a bar that
 * does it is worse than none.
 *
 * So the stages are weighted by how long they actually take, measured against
 * the provider, and the bar creeps within the current one against elapsed
 * time. Two properties keep that honest.
 *
 * It never completes a stage the service has not reported: the creep is
 * asymptotic, approaching the next boundary and never arriving. A stage that
 * runs long slows down rather than overtaking the truth.
 *
 * And it never goes backwards. A meter that retreats reads as a fault in
 * itself, whatever it is describing.
 */
const DIRECT = ['extraction', 'structuring', 'analyst-pass-direct'];

describe('how far along a compile is', () => {
  it('starts at nothing, not at a stage-sized jump', () => {
    expect(compileFraction({ stagesCompleted: [], elapsedMs: 0 })).toBe(0);
    expect(compileFraction({ stagesCompleted: [], elapsedMs: 1_000 })).toBeLessThan(0.05);
  });

  it('creeps while a stage runs, without the service saying anything', () => {
    const early = compileFraction({ stagesCompleted: [], elapsedMs: 3_000 });
    const later = compileFraction({ stagesCompleted: [], elapsedMs: 12_000 });

    expect(later).toBeGreaterThan(early);
  });

  it('never finishes a stage the service has not reported finished', () => {
    const stuck = compileFraction({ stagesCompleted: [], elapsedMs: 600_000 });
    const firstBoundary = STAGE_SECONDS[0] / STAGE_SECONDS.reduce((a, b) => a + b, 0);

    expect(stuck).toBeLessThan(firstBoundary);
  });

  it('is weighted by how long each stage takes, not by counting them', () => {
    const two = compileFraction({
      stagesCompleted: ['extraction', 'structuring'],
      elapsedMs: 45_000,
    });

    expect(two).toBeLessThan(0.5);
  });

  it('never goes backwards when a stage lands', () => {
    const justBefore = compileFraction({ stagesCompleted: [], elapsedMs: 24_000 });
    const justAfter = compileFraction({
      stagesCompleted: ['extraction'],
      elapsedMs: 25_000,
    });

    expect(justAfter).toBeGreaterThanOrEqual(justBefore);
  });

  it('is exactly one when the compile is done', () => {
    expect(
      compileFraction({ stagesCompleted: DIRECT, elapsedMs: 300_000, complete: true }),
    ).toBe(1);
  });

  it('does not creep while the job is with the provider', () => {
    const early = compileFraction({
      stagesCompleted: ['extraction', 'structuring', 'batch-submission'],
      elapsedMs: 60_000,
      awaiting: true,
    });
    const later = compileFraction({
      stagesCompleted: ['extraction', 'structuring', 'batch-submission'],
      elapsedMs: 600_000,
      awaiting: true,
    });

    expect(later).toBe(early);
  });

  it('falls back to the stage count when nothing said when it began', () => {
    const without = compileFraction({ stagesCompleted: ['extraction'], elapsedMs: null });

    expect(without).toBeGreaterThan(0);
    expect(without).toBeLessThan(1);
  });
});
