import { describe, expect, it } from 'vitest';

import { compileNotice, compileRunning, compileStages, compileTone } from '../usePrep';

/**
 * A compile waiting on its batch is not a compile that stopped.
 *
 * The Analyst pass is submitted as a batch and collected minutes or hours
 * later, so the chain returns at `batch-collection` having done everything
 * asked of it. Recorded as a stop, that told the operator — forty seconds
 * after a submission that had just succeeded — that the compile "stopped
 * while collecting the drafted questions" and "the drafting itself did not
 * produce a usable bank". Every clause of it wrong, and arriving while the
 * provider was still working.
 */
describe('a compile waiting on the provider', () => {
  const awaiting = {
    state: 'awaiting',
    complete: false,
    stages_completed: ['extraction', 'structuring', 'batch-submission'],
    stopped_at: null,
    reason: null,
    cause: null,
  } as const;

  it('says the job is with the provider, not that it failed', () => {
    const said = compileNotice(awaiting);

    expect(said).not.toBeNull();
    expect(said).not.toMatch(/stopped|did not produce/i);
    expect(said).toMatch(/sent off|with the provider|drafting job/i);
  });

  it('says how long it may take, because it is not minutes', () => {
    // A batch can take hours. An operator told "minutes, not seconds" and
    // then left waiting reads the wait as a fault.
    expect(compileNotice(awaiting)).toMatch(/hour/i);
  });

  it('is not the spinner state — nothing is being worked on here', () => {
    expect(compileRunning(awaiting)).toBe(false);
  });

  it('still reports a real stop as a stop', () => {
    const stopped = {
      state: 'stopped',
      complete: false,
      stages_completed: ['extraction'],
      stopped_at: 'structuring',
      reason: null,
      cause: 'failed',
    } as const;

    expect(compileNotice(stopped)).toMatch(/stopped while/i);
  });
});

describe('what the Preparation screen is given about a compile', () => {
  it('reports the stages the service says are done', () => {
    // The meter draws these. Dropping them on the floor is why "Compiling"
    // said the same thing at ten seconds and at six minutes.
    expect(
      compileStages({
        state: 'running',
        complete: false,
        stages_completed: ['extraction', 'structuring'],
        stopped_at: null,
        reason: null,
        cause: null,
      }),
    ).toEqual(['extraction', 'structuring']);
  });

  it('has an empty list to draw before anything has run', () => {
    expect(compileStages(null)).toEqual([]);
  });

  it('calls a run that stopped an error', () => {
    expect(
      compileTone({
        state: 'stopped',
        complete: false,
        stages_completed: [],
        stopped_at: 'structuring',
        reason: null,
        cause: 'failed',
      }),
    ).toBe('error');
  });

  it('calls a run that finished and drafted nothing a warning', () => {
    // Nothing broke. The pass ran and produced no usable bank, which an
    // operator acts on differently from a stage that could not run at all.
    expect(
      compileTone({
        state: 'complete',
        complete: true,
        stages_completed: ['extraction'],
        stopped_at: null,
        reason: null,
        cause: null,
      }),
    ).toBe('warning');
  });

  it('calls a compile still going a working notice', () => {
    expect(
      compileTone({
        state: 'awaiting',
        complete: false,
        stages_completed: [],
        stopped_at: null,
        reason: null,
        cause: null,
      }),
    ).toBe('working');
  });
});
