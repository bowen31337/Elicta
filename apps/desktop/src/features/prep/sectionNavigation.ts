/**
 * The page's own table of contents, and the rule for "you are here".
 *
 * Preparation is the longest screen in the product and the only one whose
 * length is data rather than design: a compiled bank is around seventy
 * questions in eight template sections. Measured on the running app that is
 * 3,452px with one section open and 11,021px with all of them open — twelve
 * viewports, with the Meetings section, which is the next thing an operator
 * does, starting at 10,235px.
 *
 * This module holds the two things that are decisions rather than markup: what
 * the index lists, and which of its entries is the one the reader is in.
 */

/** One row of the index. `count` is shown at the trailing edge when present. */
export interface IndexEntry {
  /** The `id` of the element the row scrolls to. */
  readonly id: string;
  readonly label: string;
  readonly count?: number;
  readonly children?: readonly IndexEntry[];
  /** Accessible name for the nested list, when there is one. */
  readonly childrenLabel?: string;
}

/** Where a section starts, in the scroll container's own coordinates. */
export interface SectionTop {
  readonly id: string;
  readonly top: number;
}

/**
 * The section the reader is in: the last one whose top has passed the line the
 * page is read from.
 *
 * `pinLine` is that line, and it is not the top of the scrollport — content
 * passes *under* the toolbar here, so a heading is level with the scrollport's
 * edge while still hidden behind glass. Measuring from the edge flips the
 * index one section early, which is worse than not marking one at all: the
 * reader is looking at one section and being told they are in the next.
 *
 * Before anything has scrolled the answer is the first section rather than
 * nothing, so the index arrives with a mark on it.
 */
export function currentSectionId(
  tops: readonly SectionTop[],
  scrollTop: number,
  pinLine: number,
): string | null {
  if (tops.length === 0) return null;

  let current = tops[0].id;
  for (const section of tops) {
    // A pixel of slack, because scroll offsets are not integers on a trackpad
    // or a scaled display — and because a jump lands a section exactly on this
    // line by construction, so the boundary is a case that happens on purpose
    // rather than an edge that never comes up.
    if (section.top - scrollTop <= pinLine + 1) current = section.id;
  }
  return current;
}

/**
 * Whether a jump to another part of the page is animated.
 *
 * Animation earns its place when it shows the reader how two things relate.
 * Across this page's whole length it shows nothing readable: measured, the
 * smooth scroll from the top to the Meetings section covers 10,219px and takes
 * about a second and a half of blur. A jump that far should simply have
 * happened — the reader asked to be somewhere else, not to travel.
 *
 * Two viewports is the line. Under it the reader can still see where the old
 * position went, which is the whole argument for animating at all.
 */
export function jumpBehaviour(
  distance: number,
  viewportHeight: number,
  reducedMotion: boolean,
): ScrollBehavior {
  if (reducedMotion) return 'auto';
  return Math.abs(distance) <= viewportHeight * 2 ? 'smooth' : 'auto';
}

/** Every row of the index, flattened, in the order they are rendered. */
export function flattenEntries(entries: readonly IndexEntry[]): IndexEntry[] {
  return entries.flatMap((entry) => [entry, ...flattenEntries(entry.children ?? [])]);
}

/** The `id` of a bank section's disclosure, so the index can point at one. */
export function bankSectionId(templateSection: string): string {
  return `bank-section-${templateSection.replace(/\W+/g, '-').toLowerCase()}`;
}

/**
 * Where the capsule bar has to be scrolled to for a row to be visible in it.
 *
 * Returns the offset unchanged when the row already fits inside the visible
 * span, so a bar that does not scroll at all — the rail at desk width — is
 * left entirely alone rather than being nudged every time the mark moves.
 *
 * `gutter` is the breathing room either side, which is also the width the
 * bar's ends are faded over: a capsule scrolled to exactly the edge sits under
 * the fade and reads as half-drawn.
 */
export function revealOffset(
  rowStart: number,
  rowWidth: number,
  offset: number,
  viewWidth: number,
  gutter: number,
): number {
  const overshoot = rowStart + rowWidth + gutter - (offset + viewWidth);
  if (overshoot > 0) return Math.max(0, offset + overshoot);

  const shortfall = offset + gutter - rowStart;
  if (shortfall > 0) return Math.max(0, offset - shortfall);

  return offset;
}
