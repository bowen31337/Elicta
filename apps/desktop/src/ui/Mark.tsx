/**
 * The Elicta mark.
 *
 * Traced from `docs/brand/elicta-mark.svg`, which is the source of truth — the
 * concentric-arc aperture on a 32-unit grid, seams alternating vertical and
 * horizontal so the rings read as woven rather than as a target.
 *
 * `stroke="currentColor"` on purpose: the mark inherits whatever colour it sits
 * in, so it works on light, dark and glass without a second asset. Stroke width
 * scales with the box, so it stays optically even at any size.
 *
 * **Where this belongs, and where it does not.** It marks the full screens —
 * prep, consent, review, debrief, settings — where a person is reading a
 * document and a moment of identity is welcome. It is deliberately absent from
 * the meeting panel: that surface exists to hold one question the operator can
 * read at a glance while looking at a client, and a logo there would compete
 * with the only thing on screen that matters. Chrome loses to content.
 *
 * Below ~24px the four-ring mark loses its seams and smears into a disc, which
 * is why `docs/brand/elicta-mark-16.svg` exists as a two-ring simplification —
 * `small` renders that variant instead of shrinking this one.
 */
export interface MarkProps {
  /** Rendered size in px. Under 24, the two-ring simplification is used. */
  readonly size?: number;
  /** Accessible name. Omit for a decorative mark beside a visible wordmark. */
  readonly title?: string;
}

export function Mark({ size = 28, title }: MarkProps) {
  const small = size < 24;
  const labelled = title !== undefined;

  return (
    <svg
      width={size}
      height={size}
      viewBox={small ? '0 0 16 16' : '0 0 32 32'}
      fill="none"
      stroke="currentColor"
      strokeWidth={small ? 2 : 1.5}
      strokeLinecap="round"
      role={labelled ? 'img' : undefined}
      aria-hidden={labelled ? undefined : true}
      aria-label={title}
      className="mark"
    >
      {small ? (
        <>
          <circle cx="8" cy="8" r="3" />
          <path d="M1.68 6.5A6.5 6.5 0 0 1 14.32 6.5" />
          <path d="M1.68 9.5A6.5 6.5 0 0 0 14.32 9.5" />
        </>
      ) : (
        <>
          <path d="M17.5 11.23A5 5 0 0 1 17.5 20.77" />
          <path d="M14.5 11.23A5 5 0 0 0 14.5 20.77" />
          <path d="M8.14 14.5A8 8 0 0 1 23.86 14.5" />
          <path d="M8.14 17.5A8 8 0 0 0 23.86 17.5" />
          <path d="M17.5 5.1A11 11 0 0 1 17.5 26.9" />
          <path d="M14.5 5.1A11 11 0 0 0 14.5 26.9" />
          <path d="M2.08 14.5A14 14 0 0 1 29.92 14.5" />
          <path d="M2.08 17.5A14 14 0 0 0 29.92 17.5" />
        </>
      )}
    </svg>
  );
}

/**
 * The mark paired with the eyebrow line that names the screen — the standard
 * header treatment for every full screen, so identity appears once, in the
 * same place, rather than being re-improvised per surface.
 */
export function ScreenEyebrow({ children }: { children: React.ReactNode }) {
  return (
    <p className="eyebrow-row t-section">
      <Mark size={26} title="Elicta" />
      <span>{children}</span>
    </p>
  );
}
