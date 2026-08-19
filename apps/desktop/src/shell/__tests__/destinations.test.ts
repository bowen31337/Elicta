import { describe, expect, it } from 'vitest';

import { DESTINATIONS, bySection, buildDestinations, humanize } from '../destinations';

/**
 * The source list is built from whatever the router globbed, not from a
 * hand-written list of screens. These assert the two ways that can go wrong:
 * a screen that exists but never appears, and a screen that appears in a
 * place nobody chose for it.
 */

describe('building the source list', () => {
  it('keeps the order of the table rather than the order features were found', () => {
    const built = buildDestinations(['about', 'prep', 'panel']);
    expect(built.map((destination) => destination.feature)).toEqual(['prep', 'panel', 'about']);
  });

  it('lists a feature nobody has named yet instead of dropping it', () => {
    const built = buildDestinations(['prep', 'triage']);
    const triage = built.find((destination) => destination.feature === 'triage');

    expect(triage).toBeDefined();
    expect(triage?.title).toBe('Triage');
    expect(triage?.section).toBe('more');
  });

  it('orders unnamed features alphabetically, so two of them do not swap between builds', () => {
    const built = buildDestinations(['zebra', 'aardvark']);
    expect(built.map((destination) => destination.feature)).toEqual(['aardvark', 'zebra']);
  });

  it('omits a table entry whose feature is not in this build', () => {
    const built = buildDestinations(['prep']);
    expect(built).toHaveLength(1);
    expect(built[0].feature).toBe('prep');
  });

  it('gives every screen in the table a caption, because the toolbar shows one', () => {
    for (const destination of DESTINATIONS) {
      expect(destination.caption.length).toBeGreaterThan(0);
    }
  });
});

describe('grouping', () => {
  it('drops sections that ended up with nothing in them', () => {
    const groups = bySection(buildDestinations(['prep', 'consent']));
    expect(groups).toHaveLength(1);
    expect(groups[0].title).toBe('Before the meeting');
    expect(groups[0].items.map((item) => item.feature)).toEqual(['prep', 'consent']);
  });
});

describe('naming an unnamed feature', () => {
  it('reads as words, not as a directory name', () => {
    expect(humanize('debrief-chat')).toBe('Debrief chat');
    expect(humanize('live_session')).toBe('Live session');
  });
});
