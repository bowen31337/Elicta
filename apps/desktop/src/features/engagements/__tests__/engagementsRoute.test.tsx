import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import EngagementsRoute from '../route';

/**
 * The screen that answers "which client am I working on".
 *
 * There wasn't one. The navigation followed the arc of a single engagement —
 * before, during and after a meeting — with no step for choosing which
 * engagement that is, so creating and removing clients ended up bolted to the
 * foot of the Preparation screen: a page headed with one client's name that
 * two-thirds of the way down offered a blank form for a different one.
 */
const ENGAGEMENTS = {
  items: [
    {
      engagement_id: 'eng-1',
      client_organisation: 'Northwind Logistics',
      sector: 'Freight and warehousing',
      commercial_context: 'Fixed-price discovery',
      purpose: null,
      scope_boundary: null,
      target_requirements_template: null,
    },
    {
      engagement_id: 'eng-2',
      client_organisation: 'Calder & Rowe',
      sector: 'Professional services',
      commercial_context: 'Matter management replacement',
      purpose: null,
      scope_boundary: null,
      target_requirements_template: null,
    },
  ],
  total: 2,
};

interface Written {
  path: string;
  method: string;
  body: unknown;
}

function stubService(overrides: Record<string, unknown> = {}) {
  const written: Written[] = [];
  const table: Record<string, unknown> = { '/api/engagements': ENGAGEMENTS, ...overrides };
  vi.stubGlobal(
    'fetch',
    vi.fn(async (path: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET';
      if (method !== 'GET') {
        written.push({
          path,
          method,
          body: init?.body === undefined ? undefined : JSON.parse(init.body as string),
        });
        return { ok: true, status: 201, json: async () => ({ engagement_id: 'eng-9' }) } as Response;
      }
      const body = table[path];
      if (body === undefined) return { ok: false, status: 404, json: async () => null } as Response;
      return { ok: true, status: 200, json: async () => body } as Response;
    }),
  );
  return written;
}

beforeEach(() => {
  window.localStorage.clear();
  window.location.hash = '';
});
afterEach(() => vi.unstubAllGlobals());

describe('the engagements screen', () => {
  it('lists every client, not just the one being worked on', async () => {
    stubService();
    render(<EngagementsRoute />);

    expect(await screen.findByText('Northwind Logistics')).toBeInTheDocument();
    expect(screen.getByText('Calder & Rowe')).toBeInTheDocument();
  });

  it('shows what tells two clients apart', async () => {
    stubService();
    render(<EngagementsRoute />);

    expect(await screen.findByText(/Freight and warehousing/)).toBeInTheDocument();
    expect(screen.getByText(/Matter management replacement/)).toBeInTheDocument();
  });

  it('opening one makes it the engagement every other screen is about', async () => {
    stubService();
    render(<EngagementsRoute />);

    await userEvent.click(await screen.findByRole('button', { name: /Open Calder & Rowe/i }));

    expect(window.localStorage.getItem('elicta.selection.engagementId')).toBe('eng-2');
    expect(window.location.hash).toBe('#/prep');
  });

  it('does not label the current client with the same word as the button beside it', async () => {
    // "Open" as a status and "Open" as an action, side by side, read as two
    // buttons where one of them does nothing.
    stubService();
    render(<EngagementsRoute />);
    await screen.findByText('Northwind Logistics');

    expect(screen.getByText('Current')).toBeInTheDocument();
    expect(screen.getAllByText('Open')).toHaveLength(2); // the two Open buttons
  });

  it('creates a client from the three things it asks for', async () => {
    const written = stubService();
    render(<EngagementsRoute />);
    await screen.findByText('Northwind Logistics');

    await userEvent.type(screen.getByLabelText(/Client organisation/i), 'Halcyon Rail');
    await userEvent.type(screen.getByLabelText(/Sector/i), 'Rail');
    await userEvent.type(screen.getByLabelText(/Commercial context/i), 'Signalling upgrade');
    await userEvent.click(screen.getByRole('button', { name: 'Create engagement' }));

    await waitFor(() => expect(written).toHaveLength(1));
    expect(written[0]).toEqual({
      path: '/api/engagements',
      method: 'POST',
      body: {
        client_organisation: 'Halcyon Rail',
        sector: 'Rail',
        commercial_context: 'Signalling upgrade',
      },
    });
  });

  it('will not create one from a half-filled form', async () => {
    const written = stubService();
    render(<EngagementsRoute />);
    await screen.findByText('Northwind Logistics');

    await userEvent.type(screen.getByLabelText(/Client organisation/i), 'Halcyon Rail');
    await userEvent.click(screen.getByRole('button', { name: 'Create engagement' }));

    expect(written).toHaveLength(0);
  });

  it('removes one, and says that removal is recoverable', async () => {
    const written = stubService();
    render(<EngagementsRoute />);

    await userEvent.click(
      await screen.findByRole('button', { name: /Remove Calder & Rowe/i }),
    );

    await waitFor(() => expect(written).toHaveLength(1));
    expect(written[0].path).toBe('/api/engagements/eng-2');
    expect(written[0].method).toBe('DELETE');
    expect(screen.getByText(/nothing is erased/i)).toBeInTheDocument();
  });

  it('says plainly when there are no clients yet, and offers the way in', async () => {
    stubService({ '/api/engagements': { items: [], total: 0 } });
    render(<EngagementsRoute />);

    expect(await screen.findByText(/No engagements yet/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Client organisation/i)).toBeInTheDocument();
  });

  it('says the service is unreachable rather than showing an empty list', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('Failed to fetch');
      }),
    );
    render(<EngagementsRoute />);

    expect(
      await screen.findByRole('heading', { name: 'Cannot reach the service' }),
    ).toBeInTheDocument();
  });
});
