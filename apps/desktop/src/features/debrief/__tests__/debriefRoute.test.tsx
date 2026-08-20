import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import DebriefRoute from '../route';
import DebriefChatRoute from '../../debrief-chat/route';

/**
 * The debrief artifacts screen, connected — and the chat beside it.
 *
 * The one thing this screen may not get wrong is telling what the client said
 * from what the system concluded (FR-8.8), so the provenance mapping is
 * asserted in the unsafe direction: anything not explicitly stated is flagged.
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
        meeting_id: 'meeting-7',
        engagement_id: 'eng-1',
        state: 'complete',
        capture_mode: 'record',
        scheduled_at: null,
        session_purpose: 'Discovery 2',
        sections_filled: 4,
        sections_total: 6,
      },
    ],
  },
};

const ARTIFACTS: Record<string, unknown> = {
  '/api/sessions/meeting-7/open-questions': [
    {
      text: "What does 'fast' mean in seconds?",
      impact_rank: 1,
      provenance: 'stated',
      citations: [
        {
          utterance_id: 'u-1',
          start_seconds: 125,
          speaker_tag: 'Priya',
          quoted_text: 'it has to be fast',
        },
      ],
    },
  ],
  '/api/sessions/meeting-7/decision-log': [
    {
      text: 'Ship the referrals API first',
      decided_by: 'Priya',
      provenance: 'guessed-by-the-vendor',
      citations: [],
    },
  ],
  '/api/sessions/meeting-7/project-brief': {
    body: 'A depot scheduling rebuild.',
    provenance: 'stated',
    citations: [],
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

describe('the debrief artifacts screen', () => {
  it('shows the artifacts the debrief produced, with their citations', async () => {
    stubService({ ...BASE, ...ARTIFACTS });
    render(<DebriefRoute />);

    expect(await screen.findByText("What does 'fast' mean in seconds?")).toBeInTheDocument();
    expect(screen.getByText(/it has to be fast/)).toBeInTheDocument();
    expect(screen.getByText(/2:05/)).toBeInTheDocument();
    expect(screen.getByText('A depot scheduling rebuild.')).toBeInTheDocument();
  });

  it('flags anything not explicitly stated as inference', async () => {
    stubService({ ...BASE, ...ARTIFACTS });
    render(<DebriefRoute />);

    // The decision came back with a provenance value nobody recognises. FR-8.8
    // says the operator must be told it was inferred, and being wrong in the
    // other direction cannot be un-heard.
    expect(await screen.findByText('Ship the referrals API first')).toBeInTheDocument();
    expect(screen.getByText('inferred')).toBeInTheDocument();
  });

  it('names the meeting rather than a hardcoded client', async () => {
    stubService({ ...BASE, ...ARTIFACTS });
    render(<DebriefRoute />);

    expect(
      await screen.findByRole('heading', { name: 'Northwind Freight — Discovery 2' }),
    ).toBeInTheDocument();
  });

  it('renders an empty debrief for a meeting that has not been debriefed', async () => {
    stubService(BASE);
    render(<DebriefRoute />);

    expect(await screen.findByRole('heading', { name: /Northwind Freight/ })).toBeInTheDocument();
    expect(screen.queryByText('Project brief')).not.toBeInTheDocument();
  });

  it('says the service is unreachable rather than showing an empty debrief', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('Failed to fetch');
      }),
    );
    render(<DebriefRoute />);

    expect(
      await screen.findByRole('heading', { name: 'Cannot reach the service' }),
    ).toBeInTheDocument();
  });
});

describe('the debrief conversation', () => {
  it('opens against the selected meeting, not the literal meeting-1', async () => {
    const fetchMock = vi.fn(async (path: string) => {
      const body = BASE[path];
      if (body === undefined) return { ok: false, status: 404, json: async () => null } as Response;
      return { ok: true, status: 200, json: async () => body } as Response;
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<DebriefChatRoute />);

    // The chat's own h1 is fixed copy; the meeting it is about is the line
    // under it.
    expect(await screen.findByText('Northwind Freight — Discovery 2')).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some(([path]) => String(path).includes('meeting-1')),
    ).toBe(false);
  });

  it('refuses to guess a meeting when none is selected', async () => {
    const fetchMock = vi.fn(async (path: string) =>
      String(path) === '/api/engagements'
        ? ({ ok: true, status: 200, json: async () => ({ items: [], total: 0 }) } as Response)
        : ({ ok: false, status: 404, json: async () => null } as Response),
    );
    vi.stubGlobal('fetch', fetchMock);
    render(<DebriefChatRoute />);

    expect(
      await screen.findByRole('heading', { name: 'Nothing selected yet' }),
    ).toBeInTheDocument();
    // Asking questions about somebody else's meeting is worse than asking
    // about none.
    expect(screen.queryByRole('button', { name: 'Start' })).not.toBeInTheDocument();
  });
});
