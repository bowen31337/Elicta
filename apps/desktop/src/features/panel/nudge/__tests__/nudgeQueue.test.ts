import { describe, expect, it } from 'vitest';
import { createNudgeQueue, enqueueNudge, renderNudgeQueue } from '../nudgeQueue';

describe('enqueueNudge', () => {
  it('accepts every candidate regardless of timing, never dropping at generation time', () => {
    let state = createNudgeQueue<string>();
    state = enqueueNudge(state, 'a');
    state = enqueueNudge(state, 'b');
    state = enqueueNudge(state, 'c');

    expect(state.pending).toEqual(['a', 'b', 'c']);
  });
});

describe('renderNudgeQueue', () => {
  it('returns null on an empty queue', () => {
    const state = createNudgeQueue<string>();
    const result = renderNudgeQueue(state, 0);

    expect(result.surfaced).toBeNull();
    expect(result.state).toBe(state);
  });

  it('surfaces the oldest pending candidate when the window allows', () => {
    let state = createNudgeQueue<string>();
    state = enqueueNudge(state, 'a');

    const result = renderNudgeQueue(state, 0);

    expect(result.surfaced).toBe('a');
    expect(result.state.pending).toEqual([]);
    expect(result.state.lastSurfacedAt).toBe(0);
  });

  it('does not surface a burst of candidates faster than the rate limit allows', () => {
    let state = createNudgeQueue<string>();
    state = enqueueNudge(state, 'a');
    state = enqueueNudge(state, 'b');
    state = enqueueNudge(state, 'c');

    const first = renderNudgeQueue(state, 0);
    expect(first.surfaced).toBe('a');

    const second = renderNudgeQueue(first.state, 1_000);
    expect(second.surfaced).toBeNull();
    // The burst candidates are retained, not dropped, so they remain eligible later.
    expect(second.state.pending).toEqual(['b', 'c']);
  });

  it('surfaces the next retained candidate once the window elapses', () => {
    let state = createNudgeQueue<string>();
    state = enqueueNudge(state, 'a');
    state = enqueueNudge(state, 'b');

    const first = renderNudgeQueue(state, 0);
    const stillGated = renderNudgeQueue(first.state, 1_000);
    const afterWindow = renderNudgeQueue(stillGated.state, 60_000);

    expect(afterWindow.surfaced).toBe('b');
    expect(afterWindow.state.pending).toEqual([]);
    expect(afterWindow.state.lastSurfacedAt).toBe(60_000);
  });

  it('leaves the queue and lastSurfacedAt untouched when suppressed', () => {
    let state = createNudgeQueue<string>();
    state = enqueueNudge(state, 'a');
    const surfaced = renderNudgeQueue(state, 0);

    let laterState = surfaced.state;
    laterState = enqueueNudge(laterState, 'b');
    const suppressed = renderNudgeQueue(laterState, 500);

    expect(suppressed.surfaced).toBeNull();
    expect(suppressed.state.lastSurfacedAt).toBe(0);
    expect(suppressed.state.pending).toEqual(['b']);
  });

  it('honors a custom window', () => {
    let state = createNudgeQueue<string>();
    state = enqueueNudge(state, 'a');
    state = enqueueNudge(state, 'b');

    const first = renderNudgeQueue(state, 0, 5_000);
    const tooSoon = renderNudgeQueue(first.state, 4_999, 5_000);
    const onTime = renderNudgeQueue(first.state, 5_000, 5_000);

    expect(first.surfaced).toBe('a');
    expect(tooSoon.surfaced).toBeNull();
    expect(onTime.surfaced).toBe('b');
  });
});
