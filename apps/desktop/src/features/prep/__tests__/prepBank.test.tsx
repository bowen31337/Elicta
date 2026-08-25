import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import PrepRoute from '../route';

/**
 * Reading a compiled bank without reading nine thousand pixels.
 *
 * A real compile lands about seventy questions in eight template sections.
 * Rendered flat, that was the whole screen: measured on the running app the
 * preparation page was 10,334px of scroll and the bank was 9,162px of it —
 * eleven screens, with no section heading in view to say which section you
 * were in, and the Meetings section below all of it.
 *
 * These drive the two things that fix it. A section is a disclosure, so the
 * bank reads as the tree the PRD calls the phase 0 deliverable rather than as
 * one list; and there is a filter, because "which questions mention
 * FROSTLINE" is a question an operator has and scrolling is not an answer to
 * it.
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

/**
 * Three sections rather than one, because everything here is about what the
 * *other* sections do while you are reading one of them.
 */
const BANK = {
  engagement_id: 'eng-1',
  sections: [
    {
      template_section: 'Scope and outcomes',
      candidates: [
        {
          id: 'c-1',
          phrasing: 'Is the February go-live firm?',
          priority: 1,
          pruned: false,
          source_doc: '01-scoping-deck.pptx',
          authority_match: ['ground truth'],
        },
        { id: 'c-2', phrasing: 'Is Derby in phase one?', priority: 2, pruned: false },
      ],
    },
    {
      template_section: 'Volumes',
      candidates: [
        { id: 'c-3', phrasing: 'How many pallets a day at peak?', priority: 1, pruned: false },
        { id: 'c-4', phrasing: 'Does FROSTLINE report that daily?', priority: 2, pruned: false },
        { id: 'c-5', phrasing: 'A pruned one nobody should see', priority: 3, pruned: true },
      ],
    },
    {
      template_section: 'Performance',
      candidates: [
        { id: 'c-6', phrasing: 'What counts as fast, in seconds?', priority: 1, pruned: false },
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

function stubService() {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (path: string, init?: RequestInit) => {
      if ((init?.method ?? 'GET') !== 'GET') {
        return { ok: true, status: 200, json: async () => ({}) } as Response;
      }
      const body = ROUTES[path];
      if (body === undefined) return { ok: false, status: 404, json: async () => null } as Response;
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

const section = (name: string) => screen.getByRole('button', { name: new RegExp(`^${name}`) });

describe('a bank long enough to be a scroll problem', () => {
  it('opens the first section and leaves the rest closed', async () => {
    // Open, because a screen whose point is the question tree must not arrive
    // as a row of closed headers that could be read as an empty bank. The
    // rest closed, because that is the length problem.
    await ready();

    expect(screen.getByText('Is the February go-live firm?')).toBeInTheDocument();
    expect(screen.queryByText('How many pallets a day at peak?')).not.toBeInTheDocument();
    expect(screen.queryByText('What counts as fast, in seconds?')).not.toBeInTheDocument();
  });

  it('says how much is behind a closed section without opening it', async () => {
    await ready();

    expect(section('Volumes')).toHaveAttribute('aria-expanded', 'false');
    // Two, not three: the pruned one is not a question anybody still has to
    // review, and counting it would overstate the work left.
    expect(within(section('Volumes')).getByText('2')).toBeInTheDocument();
  });

  it('opens a section when its header is used, and closes it again', async () => {
    await ready();

    await userEvent.click(section('Volumes'));
    expect(screen.getByText('How many pallets a day at peak?')).toBeInTheDocument();
    expect(section('Volumes')).toHaveAttribute('aria-expanded', 'true');

    await userEvent.click(section('Volumes'));
    expect(screen.queryByText('How many pallets a day at peak?')).not.toBeInTheDocument();
  });

  it('closes the one that was open without closing the one just opened', async () => {
    // Sections are independent rather than an accordion of one: a reviewer
    // comparing Volumes against Performance should not have to choose.
    await ready();

    await userEvent.click(section('Volumes'));

    expect(screen.getByText('Is the February go-live firm?')).toBeInTheDocument();
    expect(screen.getByText('How many pallets a day at peak?')).toBeInTheDocument();
  });

  it('opens and closes the whole bank from one control', async () => {
    await ready();

    await userEvent.click(screen.getByRole('button', { name: 'Expand all' }));
    expect(screen.getByText('What counts as fast, in seconds?')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Collapse all' }));
    expect(screen.queryByText('Is the February go-live firm?')).not.toBeInTheDocument();
  });

  it('counts the bank in one line, so its size is known before any of it is read', async () => {
    await ready();

    expect(screen.getByText(/5 questions across 3 sections/)).toBeInTheDocument();
  });

  it('still lists the sections as headings when they are all closed', async () => {
    // A closed bank is a table of contents, and a screen reader should get the
    // same thing the eye does rather than three unlabelled buttons.
    await ready();
    await userEvent.click(screen.getByRole('button', { name: 'Expand all' }));
    await userEvent.click(screen.getByRole('button', { name: 'Collapse all' }));

    expect(
      screen.getAllByRole('heading', { level: 3 }).map((node) => node.textContent),
    ).toEqual(['Scope and outcomes2', 'Volumes2', 'Performance1']);
  });
});

describe('finding a question in a bank too long to scan', () => {
  const filter = () => screen.getByLabelText('Find a question');

  it('shows only the questions that contain what was typed', async () => {
    await ready();

    await userEvent.type(filter(), 'FROSTLINE');

    expect(screen.getByText('Does FROSTLINE report that daily?')).toBeInTheDocument();
    expect(screen.queryByText('Is the February go-live firm?')).not.toBeInTheDocument();
  });

  it('drops a section with no match rather than leaving a header to scroll past', async () => {
    await ready();

    await userEvent.type(filter(), 'FROSTLINE');

    expect(screen.queryByRole('button', { name: /^Scope and outcomes/ })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^Volumes/ })).toBeInTheDocument();
  });

  it('opens a matching section without being asked, including a closed one', async () => {
    // Volumes starts closed. A filter that matched inside it and left it shut
    // would report a hit and show nothing.
    await ready();

    await userEvent.type(filter(), 'pallets');

    expect(screen.getByText('How many pallets a day at peak?')).toBeInTheDocument();
  });

  it('says how much of the bank matched, not just what is on screen', async () => {
    await ready();

    await userEvent.type(filter(), 'FROSTLINE');

    expect(screen.getByText(/1 of 5 questions contain that/)).toBeInTheDocument();
  });

  it('counts a partly matched section both ways in its header', async () => {
    await ready();

    await userEvent.type(filter(), 'phase one');

    expect(within(section('Scope and outcomes')).getByText('1 of 2')).toBeInTheDocument();
  });

  it('ignores case, because nobody types a client system in capitals to find it', async () => {
    await ready();

    await userEvent.type(filter(), 'frostline');

    expect(screen.getByText('Does FROSTLINE report that daily?')).toBeInTheDocument();
  });

  it('says plainly when nothing matches', async () => {
    await ready();

    await userEvent.type(filter(), 'zzzz');

    expect(screen.getByText('No question contains that')).toBeInTheDocument();
    expect(screen.getByText(/0 of 5 questions contain that/)).toBeInTheDocument();
  });

  it('never surfaces a pruned candidate, however the filter is spelled', async () => {
    await ready();

    await userEvent.type(filter(), 'nobody should see');

    expect(screen.getByText('No question contains that')).toBeInTheDocument();
  });

  it('turns reordering off while filtering, and says why', async () => {
    /**
     * `Move up` gives a candidate the priority of the one above it. Above
     * *which* one is the question: under a filter the row above on screen is
     * not the row above in the bank, so promoting past it would reorder the
     * bank in a way the screen never showed. Refusing is the honest answer,
     * and the summary line is where the reason goes because that is the line
     * the filter field points at.
     */
    await ready();

    await userEvent.type(filter(), 'phase one');

    expect(screen.getByRole('button', { name: /Move .*Derby.* earlier/i })).toBeDisabled();
    expect(screen.getByText(/Reordering is off while the filter is on/)).toBeInTheDocument();
  });

  it('leaves pruning on, because it does not depend on what is next to it', async () => {
    await ready();

    await userEvent.type(filter(), 'FROSTLINE');

    expect(screen.getByRole('button', { name: /Prune .*FROSTLINE/i })).toBeEnabled();
  });

  it('gives the bank back when the box is cleared', async () => {
    await ready();

    await userEvent.type(filter(), 'FROSTLINE');
    await userEvent.clear(filter());

    expect(screen.getByText('Is the February go-live firm?')).toBeInTheDocument();
    expect(screen.getByText(/5 questions across 3 sections/)).toBeInTheDocument();
  });
});


describe('telling evidence from inference', () => {
  /**
   * The judgement the bank screen could not support.
   *
   * The Analyst drafts some questions off a document and reasons others out
   * of the engagement, and it records which is which. All of it was dropped
   * at the API boundary, so a bank grounded in a rich scoping pack and one
   * reasoned out of a one-page invite arrived looking identical — same
   * shape, same count, same confidence. "Can I trust these 164 questions"
   * had no answer on the screen that shows them, and pruning was a read of
   * every row rather than a filter.
   */
  it('names the document a question was drafted from', async () => {
    await ready();

    expect(await screen.findByText(/01-scoping-deck\.pptx/)).toBeInTheDocument();
  });

  it('says plainly when a question was reasoned rather than read', async () => {
    /* Silence is the wrong way to show this. An operator scanning a list
       cannot tell a row that has nothing to say about its source from one
       whose source failed to load, and the second is the bug this replaced. */
    await ready();

    expect(await screen.findByText(/Is Derby in phase one\?/)).toBeInTheDocument();
    const rows = screen.getAllByText(/Reasoned from the engagement/);
    expect(rows.length).toBeGreaterThan(0);
  });
});
