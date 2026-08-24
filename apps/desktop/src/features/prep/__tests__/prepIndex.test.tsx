import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import PrepRoute from '../route';
import { SectionIndex } from '../SectionIndex';

/**
 * Getting to the bottom of a page that is twelve screens long.
 *
 * Measured on the running app with a real compiled bank — 73 questions in
 * eight template sections — the preparation page is 3,452px with one section
 * open and 11,021px with all of them open. Meetings, which is where an
 * operator goes to do the next thing in the journey, starts at 10,235px.
 *
 * There was no way down it but the wheel. The pane is an `overflow-y: auto`
 * div inside a shell that is `overflow: hidden`, so the document has nothing
 * to scroll and End, Page Down and the arrow keys moved it by zero pixels —
 * measured, not assumed.
 *
 * These drive the answer: an index of the page's own sections that names
 * where you are and takes you anywhere in one move, at any width.
 */
const ENGAGEMENTS = {
  items: [
    {
      engagement_id: 'eng-1',
      client_organisation: 'Northwind Freight',
      sector: 'logistics',
      commercial_context: 'Depot rebuild',
      purpose: null,
      scope_boundary: null,
      target_requirements_template: null,
    },
  ],
  total: 1,
};

const BANK = {
  engagement_id: 'eng-1',
  sections: [
    {
      template_section: 'Scope and outcomes',
      candidates: [
        { id: 'c-1', phrasing: 'Is the February go-live firm?', priority: 1, pruned: false },
        { id: 'c-2', phrasing: 'Is Derby in phase one?', priority: 2, pruned: false },
      ],
    },
    {
      template_section: 'Volumes',
      candidates: [
        { id: 'c-3', phrasing: 'How many pallets a day at peak?', priority: 1, pruned: false },
        { id: 'c-4', phrasing: 'A pruned one nobody should see', priority: 2, pruned: true },
      ],
    },
    {
      template_section: 'Performance',
      candidates: [
        { id: 'c-5', phrasing: 'What counts as fast, in seconds?', priority: 1, pruned: false },
      ],
    },
  ],
  generated_at: '2026-08-20T00:00:00Z',
};

const ROUTES: Record<string, unknown> = {
  '/api/engagements': ENGAGEMENTS,
  '/api/engagements/eng-1/documents': { engagement_id: 'eng-1', documents: [] },
  '/api/engagements/eng-1/vocabulary': { engagement_id: 'eng-1', terms: [] },
  '/api/engagements/eng-1/meetings': { engagement_id: 'eng-1', meetings: [] },
  '/api/engagements/eng-1/bank': BANK,
};

function stubService(bank: unknown = BANK) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (path: string, init?: RequestInit) => {
      if ((init?.method ?? 'GET') !== 'GET') {
        return { ok: true, status: 200, json: async () => ({}) } as Response;
      }
      const body = path === '/api/engagements/eng-1/bank' ? bank : ROUTES[path];
      if (body === undefined || body === null) {
        return { ok: false, status: 404, json: async () => null } as Response;
      }
      return { ok: true, status: 200, json: async () => body } as Response;
    }),
  );
}

beforeEach(() => {
  window.localStorage.clear();
  stubService();
});
afterEach(() => vi.unstubAllGlobals());

async function ready() {
  render(<PrepRoute />);
  expect(await screen.findByRole('heading', { name: 'Northwind Freight' })).toBeInTheDocument();
}

const index = () => screen.getByRole('navigation', { name: 'On this page' });

describe('an index of the page, for a page too long to scroll', () => {
  it('names every section of the page, in the order they appear', async () => {
    await ready();

    const links = within(index())
      .getAllByRole('link')
      .map((link) => link.textContent?.replace(/\s+/g, ' ').trim());

    // The whole index in document order, both levels, because the order *is*
    // the claim: an index that lists the page in a different order than the
    // page is a map of somewhere else. Meetings matters most — it is the
    // furthest thing from the top and the next thing an operator does.
    expect(links).toEqual([
      'Reference documents',
      'Engagement vocabulary',
      'Question bank',
      'Scope and outcomes 2',
      'Volumes 1',
      'Performance 1',
      'Meetings',
    ]);
  });

  it('takes the operator to a section named in it', async () => {
    await ready();

    const meetings = within(index()).getByRole('link', { name: 'Meetings' });
    // The section it points at is the one the page renders, not a guess: an
    // index whose target does not exist scrolls nowhere and reports nothing.
    const target = meetings.getAttribute('href')?.replace('#', '') ?? '';
    expect(target).not.toBe('');
    expect(document.getElementById(target)).toBe(
      screen.getByRole('heading', { name: 'Meetings' }).closest('section'),
    );
  });

  it('lists the bank’s own sections under it, because that is where the length is', async () => {
    await ready();

    const bank = within(index()).getByRole('list', { name: 'Question bank sections' });
    const rows = within(bank)
      .getAllByRole('link')
      .map((link) => link.textContent?.replace(/\s+/g, ' ').trim());

    // Each carries its count, so the operator can tell where the ten minutes
    // will go before opening anything — the same thing the closed disclosure
    // headers say, said once in a place that stays on screen.
    expect(rows).toEqual(['Scope and outcomes 2', 'Volumes 1', 'Performance 1']);
  });

  it('opens a closed bank section when the index sends you to it', async () => {
    await ready();

    // Only the first section is open by default. Being sent to a closed one
    // and finding a shut header is a jump that did nothing.
    expect(screen.queryByText('What counts as fast, in seconds?')).not.toBeInTheDocument();

    const bank = within(index()).getByRole('list', { name: 'Question bank sections' });
    await userEvent.click(within(bank).getByRole('link', { name: /^Performance/ }));

    expect(screen.getByText('What counts as fast, in seconds?')).toBeInTheDocument();
  });

  it('says which section the page is showing', async () => {
    await ready();

    // `aria-current` is the claim, not a class: it is the only form of "you
    // are here" a screen reader can act on, and the eye gets the same state
    // from the same attribute.
    const current = within(index())
      .getAllByRole('link')
      .filter((link) => link.getAttribute('aria-current') === 'true');
    expect(current).toHaveLength(1);
    expect(current[0]).toHaveTextContent('Reference documents');
  });

  it('leaves the bank out of the index when there is no bank to index', async () => {
    stubService(null);
    await ready();

    // A bank that has not compiled is one row on the screen, not a tree. An
    // index listing eight sections that are not there would be a promise the
    // page cannot keep.
    expect(
      within(index()).queryByRole('list', { name: 'Question bank sections' }),
    ).not.toBeInTheDocument();
    expect(within(index()).getByRole('link', { name: 'Question bank' })).toBeInTheDocument();
  });
});

/**
 * The trail, not just the destination.
 *
 * At narrow widths the bank's own rows are not drawn — eight more capsules in
 * a row that already scrolls is a scroll to cross a scroll — so the mark for
 * "you are here" would land on an element CSS had removed, and neither the eye
 * nor a screen reader would find a current row anywhere. Marking the whole
 * trail fixes both at once, and it is the truer claim in any case: a reader
 * inside Operations is inside the Question bank.
 */
describe('marking where the reader is', () => {
  const ENTRIES = [
    { id: 'a', label: 'Reference documents' },
    {
      id: 'bank',
      label: 'Question bank',
      childrenLabel: 'Question bank sections',
      children: [
        { id: 'ops', label: 'Operations', count: 9 },
        { id: 'vol', label: 'Volumes', count: 7 },
      ],
    },
    { id: 'z', label: 'Meetings' },
  ];

  const marked = () =>
    screen
      .getAllByRole('link')
      .filter((link) => link.getAttribute('aria-current') === 'true')
      .map((link) => link.textContent?.replace(/\s+/g, ' ').trim());

  it('marks the section containing the one being read, as well as that one', () => {
    render(<SectionIndex entries={ENTRIES} currentId="ops" onJump={() => {}} />);

    expect(marked()).toEqual(['Question bank', 'Operations 9']);
  });

  it('marks only the row itself when it contains nothing', () => {
    render(<SectionIndex entries={ENTRIES} currentId="z" onJump={() => {}} />);

    expect(marked()).toEqual(['Meetings']);
  });

  it('marks nothing before anything has been measured', () => {
    render(<SectionIndex entries={ENTRIES} currentId={null} onJump={() => {}} />);

    expect(marked()).toEqual([]);
  });
});
