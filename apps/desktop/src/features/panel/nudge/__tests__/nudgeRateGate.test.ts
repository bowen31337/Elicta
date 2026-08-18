import { describe, expect, it } from 'vitest';
import { NUDGE_SURFACE_WINDOW_MS, canSurfaceNudge } from '../nudgeRateGate';

describe('canSurfaceNudge', () => {
  it('admits the first nudge when nothing has surfaced yet', () => {
    expect(canSurfaceNudge(0, null)).toBe(true);
  });

  it('rejects a nudge inside the 60s window', () => {
    expect(canSurfaceNudge(59_999, 0)).toBe(false);
  });

  it('admits a nudge exactly at the window boundary', () => {
    expect(canSurfaceNudge(NUDGE_SURFACE_WINDOW_MS, 0)).toBe(true);
  });

  it('admits a nudge after the window has elapsed', () => {
    expect(canSurfaceNudge(60_001, 0)).toBe(true);
  });

  it('honors a custom window', () => {
    expect(canSurfaceNudge(4_999, 0, 5_000)).toBe(false);
    expect(canSurfaceNudge(5_000, 0, 5_000)).toBe(true);
  });
});
