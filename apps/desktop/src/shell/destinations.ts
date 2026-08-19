/**
 * The source list.
 *
 * `router.tsx` still discovers screens by globbing `features/*​/route.tsx` — a
 * feature is mounted by existing, not by being registered. This table adds
 * only what a sidebar needs and a filename cannot carry: what to call the
 * screen, which part of the engagement it belongs to, and its symbol.
 *
 * A feature with no entry here is not dropped. It appears under "More" with a
 * title derived from its directory name, so the drop-in convention keeps
 * working and an unnamed screen is visibly unnamed rather than invisible.
 */
import type { GlyphName } from './Glyph';

/** Sections follow the arc of an engagement, which is how the operator
 *  thinks about the work — not the alphabet, and not our module layout. */
export type SectionId = 'before' | 'during' | 'after' | 'product' | 'more';

export const SECTION_TITLES: Record<SectionId, string> = {
  before: 'Before the meeting',
  during: 'In the meeting',
  after: 'After the meeting',
  product: 'Elicta',
  more: 'More',
};

export const SECTION_ORDER: readonly SectionId[] = ['before', 'during', 'after', 'product', 'more'];

export interface Destination {
  /** The `features/<feature>/route.tsx` directory this maps to. */
  readonly feature: string;
  /** Sidebar row and toolbar title. */
  readonly title: string;
  /** One line under the toolbar title: what the screen is for. */
  readonly caption: string;
  readonly glyph: GlyphName;
  readonly section: SectionId;
  /** The panel is a floating material, not a document; the pane stages it
   *  at its real width instead of letting it fill the window. */
  readonly floating?: boolean;
}

export const DESTINATIONS: readonly Destination[] = [
  {
    feature: 'prep',
    title: 'Preparation',
    caption: 'What you know going in, and the questions worth asking',
    glyph: 'doc',
    section: 'before',
  },
  {
    feature: 'consent',
    title: 'Consent',
    caption: 'On the record, and what happens to the audio',
    glyph: 'seal',
    section: 'before',
  },
  {
    feature: 'panel',
    title: 'Live panel',
    caption: 'Coverage, and the follow-up worth asking right now',
    glyph: 'waveform',
    section: 'during',
    floating: true,
  },
  {
    feature: 'capture',
    title: 'Capture',
    caption: 'The recording state, and which microphone is live',
    glyph: 'mic',
    section: 'during',
  },
  {
    feature: 'recording',
    title: 'Recording',
    caption: 'Two transcriptions, and where they disagreed',
    glyph: 'record',
    section: 'after',
  },
  {
    feature: 'debrief',
    title: 'Debrief',
    caption: 'The documents, and what was said versus worked out',
    glyph: 'pages',
    section: 'after',
  },
  {
    feature: 'debrief-chat',
    title: 'Ask about it',
    caption: 'Answers drawn from the transcript, each one cited',
    glyph: 'bubble',
    section: 'after',
  },
  {
    feature: 'arc',
    title: 'Engagement arc',
    caption: 'What survives into the next meeting',
    glyph: 'arc',
    section: 'after',
  },
  {
    feature: 'replay',
    title: 'Replay',
    caption: 'Whether the suggestions are any good, measured',
    glyph: 'replay',
    section: 'product',
  },
  {
    feature: 'settings',
    title: 'Settings',
    caption: 'Providers, credentials and transcription',
    glyph: 'sliders',
    section: 'product',
  },
  {
    feature: 'about',
    title: 'About',
    caption: 'This build, and what it is allowed to do',
    glyph: 'info',
    section: 'product',
  },
];

/** `debrief-chat` → `Debrief chat`. Only ever seen for a screen nobody has
 *  named yet, which is the point: it reads as a gap, not as a decision. */
export function humanize(feature: string): string {
  const spaced = feature.replace(/[-_]/g, ' ').trim();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/**
 * Orders the discovered features into the source list.
 *
 * Known features keep the order of the table above; anything else lands in
 * "More", alphabetically, so two unnamed screens do not swap places between
 * builds.
 */
export function buildDestinations(features: readonly string[]): Destination[] {
  const present = new Set(features);
  const known = DESTINATIONS.filter((destination) => present.has(destination.feature));
  const named = new Set(known.map((destination) => destination.feature));
  const unknown = [...features]
    .filter((feature) => !named.has(feature))
    .sort()
    .map<Destination>((feature) => ({
      feature,
      title: humanize(feature),
      caption: 'This screen has not been given a description yet.',
      glyph: 'default',
      section: 'more',
    }));
  return [...known, ...unknown];
}

/** Groups the source list for rendering, dropping empty sections. */
export function bySection(
  destinations: readonly Destination[],
): { section: SectionId; title: string; items: Destination[] }[] {
  return SECTION_ORDER.map((section) => ({
    section,
    title: SECTION_TITLES[section],
    items: destinations.filter((destination) => destination.section === section),
  })).filter((group) => group.items.length > 0);
}
