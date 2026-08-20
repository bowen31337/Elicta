import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import ConsentRoute from '../route';

/**
 * The consent screen, connected.
 *
 * This one mattered most of the six: it shipped with `confirmedBy={null}`
 * hardcoded, so a meeting with consent properly on record still told the
 * operator capture could not start. A gate that is wrong in the safe
 * direction is still a gate nobody will believe.
 */
const ENGAGEMENTS = {
  items: [
    {
      engagement_id: 'eng-1',
      client_organisation: 'Harbourline Ferries',
      sector: 'transport',
      commercial_context: 'Crew rostering',
      purpose: null,
      scope_boundary: null,
      target_requirements_template: null,
    },
  ],
  total: 1,
};

const MEETINGS = {
  engagement_id: 'eng-1',
  meetings: [
    {
      meeting_id: 'meeting-1',
      engagement_id: 'eng-1',
      state: 'planned',
      capture_mode: 'Line-in',
      scheduled_at: null,
      session_purpose: 'Discovery 1',
      sections_filled: null,
      sections_total: null,
    },
  ],
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

const BASE = {
  '/api/engagements': ENGAGEMENTS,
  '/api/engagements/eng-1/meetings': MEETINGS,
};

beforeEach(() => window.localStorage.clear());
afterEach(() => vi.unstubAllGlobals());

describe('the consent screen', () => {
  it('shows consent as on record, with who confirmed it', async () => {
    stubService({
      ...BASE,
      '/api/meetings/meeting-1/consent-gate?engagement_id=eng-1': { status: 'confirmed' },
      '/api/meetings/meeting-1/consent-record': {
        meeting_id: 'meeting-1',
        confirmed_by: 'Priya Raman',
        confirmed_at: '2026-08-20T09:15:00Z',
      },
    });
    render(<ConsentRoute />);

    expect(await screen.findByText('Confirmed')).toBeInTheDocument();
    expect(screen.getByText(/Priya Raman/)).toBeInTheDocument();
    expect(screen.getByText('On record')).toBeInTheDocument();
  });

  it('shows consent as required when nobody has confirmed', async () => {
    stubService({
      ...BASE,
      '/api/meetings/meeting-1/consent-gate?engagement_id=eng-1': {
        status: 'awaiting_confirmation',
      },
    });
    render(<ConsentRoute />);

    expect(await screen.findByText('Not confirmed')).toBeInTheDocument();
    expect(screen.getByText('Required')).toBeInTheDocument();
  });

  it('names standing engagement consent rather than asking again', async () => {
    stubService({
      ...BASE,
      '/api/meetings/meeting-1/consent-gate?engagement_id=eng-1': { status: 'not_required' },
    });
    render(<ConsentRoute />);

    expect(await screen.findByText('standing for the engagement')).toBeInTheDocument();
  });

  it('shows the capture mode the meeting was actually created with', async () => {
    stubService({
      ...BASE,
      '/api/meetings/meeting-1/consent-gate?engagement_id=eng-1': { status: 'confirmed' },
    });
    render(<ConsentRoute />);

    expect(await screen.findAllByText(/Line-in/)).not.toHaveLength(0);
  });

  /**
   * The line this replaces said "No meeting exists yet" whenever the screen
   * had no meeting id — including when meetings existed in quantity under an
   * engagement the app had simply never been pointed at.
   */
  it('names the engagement that is empty rather than claiming no meeting exists', async () => {
    stubService({
      '/api/engagements': {
        items: [
          ENGAGEMENTS.items[0],
          { ...ENGAGEMENTS.items[0], engagement_id: 'eng-2', client_organisation: 'Cadence Rail' },
        ],
        total: 2,
      },
      '/api/engagements/eng-1/meetings': { engagement_id: 'eng-1', meetings: [] },
    });
    render(<ConsentRoute />);

    const hint = await screen.findByText(/Harbourline Ferries has no meetings yet/);
    expect(hint).toHaveTextContent('choose it from the engagement menu');
    expect(screen.queryByText(/No meeting exists yet/)).not.toBeInTheDocument();
  });

  it('says the service holds nothing when it really holds nothing', async () => {
    stubService({ '/api/engagements': { items: [], total: 0 } });
    render(<ConsentRoute />);

    expect(
      await screen.findByText(/No engagement is selected, because the service holds none yet/),
    ).toBeInTheDocument();
  });

  it('refuses to render the gate at all when it cannot be read', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('Failed to fetch');
      }),
    );
    render(<ConsentRoute />);

    expect(
      await screen.findByRole('heading', { name: 'Cannot reach the service' }),
    ).toBeInTheDocument();
    // Neither answer may be guessed: showing "on record" would be unsafe, and
    // showing "required" would be a lie about a meeting that may have consent.
    expect(screen.queryByText('On record')).not.toBeInTheDocument();
    expect(screen.queryByText('Required')).not.toBeInTheDocument();
  });
});
