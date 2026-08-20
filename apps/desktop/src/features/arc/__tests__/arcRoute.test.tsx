import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import ArcRoute from '../route';

/**
 * The engagement arc, connected.
 *
 * The value of an engagement-scoped product over a per-meeting one lives
 * entirely on this screen, and it rendered `meetings={[]}` — so the product's
 * whole argument for itself showed as an em dash and three zeroes.
 */
const BASE: Record<string, unknown> = {
  '/api/engagements': {
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
  },
  '/api/engagements/eng-1/meetings': {
    engagement_id: 'eng-1',
    meetings: [
      {
        meeting_id: 'meeting-1',
        engagement_id: 'eng-1',
        state: 'complete',
        capture_mode: 'live',
        scheduled_at: '2026-07-02T09:00:00Z',
        session_purpose: 'Discovery 1',
        sections_filled: 3,
        sections_total: 6,
      },
      {
        meeting_id: 'meeting-2',
        engagement_id: 'eng-1',
        state: 'planned',
        capture_mode: 'record',
        scheduled_at: null,
        session_purpose: null,
        sections_filled: null,
        sections_total: null,
      },
    ],
  },
};

function stubService(table: Record<string, unknown>) {
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

describe('the engagement arc', () => {
  it('shows the meetings the engagement actually has', async () => {
    stubService({
      ...BASE,
      '/api/engagements/eng-1/state': {
        engagement_id: 'eng-1',
        inherited_open_questions: [],
        requirements_state: null,
      },
    });
    render(<ArcRoute />);

    expect(await screen.findByText('Discovery 1')).toBeInTheDocument();
    expect(screen.getByText(/3 of 6.*sections covered/s)).toBeInTheDocument();
  });

  it('labels a meeting with no stated purpose by how it is captured', async () => {
    stubService({
      ...BASE,
      '/api/engagements/eng-1/state': {
        engagement_id: 'eng-1',
        inherited_open_questions: [],
        requirements_state: null,
      },
    });
    render(<ArcRoute />);

    expect(await screen.findByText('record capture')).toBeInTheDocument();
    expect(screen.getByText(/Not scheduled/)).toBeInTheDocument();
  });

  it('carries the standing questions the service kept, highest impact first', async () => {
    stubService({
      ...BASE,
      '/api/engagements/eng-1/state': {
        engagement_id: 'eng-1',
        inherited_open_questions: [
          { text: "What does 'fast' mean in seconds?", impact_rank: 1 },
          { text: 'Who signs off the integration?', impact_rank: 2 },
        ],
        requirements_state: {
          confirmed_requirements: [{ id: 'r-1' }, { id: 'r-2' }, { id: 'r-3' }],
        },
      },
    });
    render(<ArcRoute />);

    expect(await screen.findByText("What does 'fast' mean in seconds?")).toBeInTheDocument();
    expect(screen.getByText('Who signs off the integration?')).toBeInTheDocument();
    expect(screen.getByText('3')).toBeInTheDocument();
  });

  it('renders an engagement with nothing carried forward as exactly that', async () => {
    stubService({
      ...BASE,
      '/api/engagements/eng-1/state': {
        engagement_id: 'eng-1',
        inherited_open_questions: [],
        requirements_state: null,
      },
    });
    render(<ArcRoute />);

    expect(await screen.findByText('Carried into the next meeting')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Northwind Freight' })).toBeInTheDocument();
  });

  it('says the service is unreachable rather than showing an empty arc', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('Failed to fetch');
      }),
    );
    render(<ArcRoute />);

    expect(
      await screen.findByRole('heading', { name: 'Cannot reach the service' }),
    ).toBeInTheDocument();
  });
});
