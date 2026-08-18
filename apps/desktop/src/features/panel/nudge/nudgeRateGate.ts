/**
 * Rate limit governing how often a nudge may be surfaced (PRD FR-5.8): no
 * more than one per 60-second window, regardless of how many candidates pass
 * the upstream trigger gate in that window.
 */
export const NUDGE_SURFACE_WINDOW_MS = 60_000;

/**
 * True once at least `windowMs` has elapsed since the last surfaced nudge,
 * or nothing has surfaced yet.
 */
export function canSurfaceNudge(
  now: number,
  lastSurfacedAt: number | null,
  windowMs: number = NUDGE_SURFACE_WINDOW_MS,
): boolean {
  return lastSurfacedAt === null || now - lastSurfacedAt >= windowMs;
}
