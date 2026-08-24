import { describe, expect, it } from 'vitest';

import { currentSectionId, jumpBehaviour, revealOffset } from '../sectionNavigation';

/**
 * Which section the reader is in, from where the scroll is.
 *
 * A section index that does not say where you are is a menu, not a map — and
 * on an eleven-thousand-pixel page the "you are here" is the part that stops
 * the reader guessing. The rule is the one the eye uses: the section you are
 * in is the last one whose top has passed the line the page is read from,
 * which sits just under the pinned chrome rather than at the very top of the
 * scrollport.
 */
const TOPS = [
  { id: 'documents', top: 122 },
  { id: 'vocabulary', top: 663 },
  { id: 'bank', top: 879 },
  { id: 'meetings', top: 10235 },
];

describe('reading the current section off the scroll', () => {
  it('is the first section before anything has scrolled', () => {
    expect(currentSectionId(TOPS, 0, 54)).toBe('documents');
  });

  it('is the section whose top has most recently passed the reading line', () => {
    expect(currentSectionId(TOPS, 700, 54)).toBe('vocabulary');
    expect(currentSectionId(TOPS, 4000, 54)).toBe('bank');
    expect(currentSectionId(TOPS, 10400, 54)).toBe('meetings');
  });

  it('counts a heading that has slid behind the chrome as passed', () => {
    // Content passes *under* the toolbar here rather than starting below it,
    // so at this scroll the vocabulary heading is 23px down — inside the
    // scrollport and invisible behind 54px of glass. The reader cannot see it
    // and is reading what is under it. Measuring from the scrollport's edge
    // instead of the pin line would keep claiming the section above for
    // another 54px, while its heading is nowhere on screen.
    expect(currentSectionId(TOPS, 640, 54)).toBe('vocabulary');
    expect(currentSectionId(TOPS, 640, 0)).toBe('documents');
  });

  it('does not claim a section that is still below the fold', () => {
    expect(currentSectionId(TOPS, 500, 54)).toBe('documents');
  });

  it('has nothing to report when the page has no sections', () => {
    expect(currentSectionId([], 0, 54)).toBeNull();
  });
});

/**
 * Whether a jump is animated.
 *
 * Animation earns its place when it shows the reader how two things relate —
 * where the thing they asked for sits relative to where they were. Across this
 * page's full length it shows nothing: measured, a smooth scroll from the top
 * of the preparation screen to the Meetings section covers 10,219px and takes
 * about 1.5 seconds, none of it readable. A jump that long should simply have
 * happened. A short one is the case animation is for.
 */
describe('whether a jump is worth animating', () => {
  const VIEWPORT = 900;

  it('animates a jump the reader could have followed', () => {
    expect(jumpBehaviour(600, VIEWPORT, false)).toBe('smooth');
    expect(jumpBehaviour(1700, VIEWPORT, false)).toBe('smooth');
  });

  it('does not animate one nobody can read on the way past', () => {
    expect(jumpBehaviour(10219, VIEWPORT, false)).toBe('auto');
  });

  it('never animates when the reader has asked for less motion', () => {
    expect(jumpBehaviour(600, VIEWPORT, true)).toBe('auto');
  });

  it('measures the distance either way, because a jump back up is the same jump', () => {
    expect(jumpBehaviour(-10219, VIEWPORT, false)).toBe('auto');
    expect(jumpBehaviour(-600, VIEWPORT, false)).toBe('smooth');
  });
});

describe('a section resting exactly on the reading line', () => {
  it('is the current one, which is where a jump puts it', () => {
    // The jump lands a section on the line by construction — `scroll-margin-top`
    // and the pin line are the same number. Landing there and *not* counting as
    // current is the visible failure: you ask for Meetings, you arrive at
    // Meetings, and the index still says the section above.
    expect(currentSectionId([{ id: 'a', top: 0 }, { id: 'b', top: 1000 }], 930, 70)).toBe('b');
  });

  it('tolerates a fractional scroll position', () => {
    // Scroll offsets are not integers on a trackpad or a scaled display, and a
    // third of a pixel is not a reason to name a different section.
    expect(currentSectionId([{ id: 'a', top: 0 }, { id: 'b', top: 1000 }], 929.7, 70)).toBe('b');
  });
});

/**
 * Keeping the marked row where it can be seen.
 *
 * Where there is no margin the index is a row of capsules that scrolls
 * sideways, and the marked one drifts out of it as the reader moves down the
 * page: on a 390px display, reading the Question bank, the capsule saying so
 * sat off the right-hand edge. An index whose "you are here" is off screen is
 * not answering the question it exists to answer.
 */
describe('bringing the marked row back into the bar', () => {
  const VIEW = 390;
  const GUTTER = 20;

  it('leaves a row that is already in view where it is', () => {
    expect(revealOffset(100, 120, 0, VIEW, GUTTER)).toBe(0);
  });

  it('scrolls just far enough to show one that has run off the end', () => {
    // Row spans 500..640 while the bar shows 0..390. Its end plus the gutter
    // has to reach the right-hand edge: 640 + 20 - 390.
    expect(revealOffset(500, 140, 0, VIEW, GUTTER)).toBe(270);
  });

  it('scrolls back for one that has run off the start', () => {
    expect(revealOffset(60, 140, 300, VIEW, GUTTER)).toBe(40);
  });

  it('never scrolls past the beginning', () => {
    expect(revealOffset(0, 140, 300, VIEW, GUTTER)).toBe(0);
  });

  it('does nothing at all when the whole row fits', () => {
    // The rail at desk width is not a scroller, and asking it to scroll
    // sideways would be a silent no-op at best and a jitter at worst.
    expect(revealOffset(100, 120, 0, 1000, GUTTER)).toBe(0);
  });
});
