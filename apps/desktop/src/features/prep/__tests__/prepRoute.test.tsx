import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import PrepRoute from '../route';

/**
 * The preparation screen, connected.
 *
 * It used to render `clientOrganisation="—"` with three empty lists, which is
 * exactly what a working screen looks like for an engagement nobody has
 * touched — and exactly what it looks like when the service is not running.
 * These assert the three pictures are now different.
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

const ROUTES: Record<string, unknown> = {
  '/api/engagements': ENGAGEMENTS,
  '/api/engagements/eng-1/documents': {
    engagement_id: 'eng-1',
    documents: [
      { document_id: 'doc-1', name: 'Depot RFP.pdf', status: 'ground truth' },
      { document_id: 'doc-2', name: 'Slack thread.txt', status: 'hypothesis' },
    ],
  },
  '/api/engagements/eng-1/vocabulary': {
    engagement_id: 'eng-1',
    terms: [{ term: 'Depot Sequencer' }, { term: 'TMS' }],
  },
  '/api/engagements/eng-1/bank': {
    engagement_id: 'eng-1',
    sections: [
      {
        template_section: 'Performance',
        candidates: [
          { id: 'c-1', phrasing: 'What counts as fast, in seconds?', priority: 1, pruned: false },
          { id: 'c-2', phrasing: 'A pruned one', priority: 2, pruned: true },
        ],
      },
    ],
    generated_at: '2026-08-20T00:00:00Z',
  },
};

function stubService(overrides: Record<string, unknown> = {}) {
  const table = { ...ROUTES, ...overrides };
  vi.stubGlobal(
    'fetch',
    vi.fn(async (path: string) => {
      const body = table[path];
      if (body === undefined) return { ok: false, status: 404, json: async () => null } as Response;
      return { ok: true, status: 200, json: async () => body } as Response;
    }),
  );
}

beforeEach(() => window.localStorage.clear());
afterEach(() => vi.unstubAllGlobals());

describe('the preparation screen', () => {
  it('shows the engagement the service knows about, not an em dash', async () => {
    stubService();
    render(<PrepRoute />);

    expect(await screen.findByRole('heading', { name: 'Northwind Freight' })).toBeInTheDocument();
  });

  it('lists the documents and the vocabulary that were actually attached', async () => {
    stubService();
    render(<PrepRoute />);

    expect(await screen.findByText('Depot RFP.pdf')).toBeInTheDocument();
    expect(screen.getByText('Slack thread.txt')).toBeInTheDocument();
    // 'hypothesis' rather than 'ground truth': the screen's own hint names the
    // latter in prose, so only this one is unambiguously the document's pill.
    expect(screen.getByText('hypothesis')).toBeInTheDocument();
    expect(screen.getByText('Depot Sequencer')).toBeInTheDocument();
  });

  it('leaves a pruned candidate out of the bank', async () => {
    stubService();
    render(<PrepRoute />);

    expect(await screen.findByText('What counts as fast, in seconds?')).toBeInTheDocument();
    expect(screen.queryByText('A pruned one')).not.toBeInTheDocument();
  });

  it('says the bank is not compiled when the service returns no sections', async () => {
    stubService({
      '/api/engagements/eng-1/bank': {
        engagement_id: 'eng-1',
        sections: [],
        generated_at: '2026-08-20T00:00:00Z',
      },
    });
    render(<PrepRoute />);

    expect(await screen.findByText('Not compiled yet')).toBeInTheDocument();
  });

  it('says the service is unreachable rather than showing an empty engagement', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('Failed to fetch');
      }),
    );
    render(<PrepRoute />);

    expect(
      await screen.findByRole('heading', { name: 'Cannot reach the service' }),
    ).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: '—' })).not.toBeInTheDocument();
  });

  it('says plainly that no engagement exists rather than rendering a blank one', async () => {
    stubService({ '/api/engagements': { items: [], total: 0 } });
    render(<PrepRoute />);

    expect(
      await screen.findByRole('heading', { name: 'Nothing selected yet' }),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByText(/Create one to prepare for a meeting/)).toBeInTheDocument(),
    );
  });
});
