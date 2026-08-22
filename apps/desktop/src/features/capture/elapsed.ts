/**
 * How long the current recording has been running, as the operator reads it.
 *
 * A separate module because it is pure and the clock that drives it is not:
 * every rounding and padding decision here is testable without a timer, a
 * device or a rendered screen.
 */

/**
 * Seconds as `mm:ss`, or `h:mm:ss` once a recording passes the hour.
 *
 * Minutes are not wrapped at sixty. A requirements meeting runs over an hour
 * often enough that a clock reading `00:01` after sixty-one minutes would be
 * telling its worst lie at the worst moment — the point where an operator is
 * most likely to be checking that capture is still alive.
 *
 * A negative or fractional input is floored to a whole second and never below
 * zero: the caller derives this from wall-clock time, and wall-clock time can
 * step backwards.
 */
export function formatElapsed(seconds: number): string {
  const total = Number.isFinite(seconds) ? Math.max(0, Math.floor(seconds)) : 0;
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  const pad = (value: number) => String(value).padStart(2, '0');

  // The hour is unpadded on purpose: `1:01:01` is how a clock is read aloud,
  // and padding it would suggest a two-digit field that has never been needed.
  return hours > 0
    ? `${hours}:${pad(minutes)}:${pad(secs)}`
    : `${pad(minutes)}:${pad(secs)}`;
}
