import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import ConsentRoute from '../route';

/**
 * The gate, as behaviour rather than as a label.
 *
 * Journey 2's whole claim is that consent is "a gate you pass, not a warning
 * you read past". Three things stopped that being true, and each has a test
 * here:
 *
 * 1. The screen decided whether capture could begin from the *consent record*
 *    (`confirmedBy !== null`) rather than from the *gate*. Consent standing
 *    for the whole engagement writes no per-meeting record, so the one model
 *    the journey opens by advertising rendered as "Required" with capture
 *    disabled — the exact opposite of what the service said.
 * 2. There was no control to confirm consent at all, so nothing could move
 *    the screen out of that state.
 * 3. The service composes an operator-facing prompt naming the law it rests
 *    on, and the screen dropped it, leaving a gate with no warning on it.
 */
const ENGAGEMENTS = {
  items: [
    {
      engagement_id: 'eng-1',
      client_organisation: 'Northwind Logistics',
      sector: 'Freight and logistics',
      commercial_context: 'Fixed-price discovery, three meetings',
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
      capture_mode: 'Line-in from the meeting machine',
      scheduled_at: null,
      session_purpose: 'Discovery 3',
      sections_filled: null,
      sections_total: null,
    },
  ],
};

const GATE = '/api/meetings/meeting-1/consent-gate?engagement_id=eng-1';
const RECORD = '/api/meetings/meeting-1/consent-record';

const PROMPT = {
  title: 'Recording consent required',
  body:
    'This meeting will be recorded and transcribed. Continuing confirms that ' +
    'every participant has been informed and has consented to being recorded.',
  legal_basis: 'NSW Surveillance Devices Act — all-party consent',
};

interface Written {
  path: string;
  method: string;
  body: unknown;
}

/**
 * Reads come from `table`, which the test may mutate between interactions so
 * a re-read after a write sees what the service would now say.
 */
function stubService(table: Record<string, unknown>, refusal?: { status: number; detail: unknown }) {
  const written: Written[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (path: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET';
      if (method === 'GET') {
        const body = table[path];
        if (body === undefined) return { ok: false, status: 404, json: async () => null } as Response;
        return { ok: true, status: 200, json: async () => body } as Response;
      }
      written.push({
        path,
        method,
        body: init?.body === undefined ? undefined : JSON.parse(init.body as string),
      });
      if (refusal) {
        return {
          ok: false,
          status: refusal.status,
          json: async () => ({ detail: refusal.detail }),
        } as Response;
      }
      return {
        ok: true,
        status: 201,
        json: async () => ({
          meeting_id: 'meeting-1',
          confirmed_by: 'Dana Whitfield, COO',
          confirmed_at: '2026-08-20T05:56:31.811556Z',
        }),
      } as Response;
    }),
  );
  return written;
}

const BASE = {
  '/api/engagements': ENGAGEMENTS,
  '/api/engagements/eng-1/meetings': MEETINGS,
};

beforeEach(() => window.localStorage.clear());
afterEach(() => vi.unstubAllGlobals());

const startButton = () => screen.getByRole('button', { name: 'Start' }) as HTMLButtonElement;

describe('consent standing for the whole engagement', () => {
  /**
   * The service's own answer for this state is `capture_may_begin === true`
   * (`ConsentGate`, `gate.py`). The screen said the opposite, in three places
   * at once, and offered no way out of it.
   */
  it('does not demand a confirmation the engagement already covers', async () => {
    stubService({ ...BASE, [GATE]: { status: 'not_required' } });
    render(<ConsentRoute />);

    expect(await screen.findByText('standing for the engagement')).toBeInTheDocument();
    expect(screen.queryByText('Required')).not.toBeInTheDocument();
    expect(screen.queryByText(/Capture cannot start/)).not.toBeInTheDocument();
    expect(startButton().disabled).toBe(false);
  });

  it('says why it is not asking rather than leaving the row blank', async () => {
    stubService({ ...BASE, [GATE]: { status: 'not_required' } });
    render(<ConsentRoute />);

    expect(
      await screen.findByText(/does not ask for consent at each meeting/i),
    ).toBeInTheDocument();
  });

  /**
   * The row used to read "Consent was agreed once for the whole engagement"
   * beside a green "On record". Since `DEFAULT_CONSENT_MODEL` became
   * `ENGAGEMENT_LEVEL`, every unconfigured engagement lands in this state
   * having agreed nothing and recorded nothing — so that copy asserted an
   * agreement that never happened, in the unsafe direction.
   */
  it('does not claim consent is on record when nothing was recorded', async () => {
    stubService({ ...BASE, [GATE]: { status: 'not_required' } });
    render(<ConsentRoute />);

    await screen.findByText('Not required for this meeting');
    expect(screen.queryByText('On record')).not.toBeInTheDocument();
    expect(screen.queryByText(/was agreed/i)).not.toBeInTheDocument();
  });
});

describe('consent still to be confirmed', () => {
  it('holds capture shut', async () => {
    stubService({ ...BASE, [GATE]: { status: 'awaiting_confirmation', prompt: PROMPT } });
    render(<ConsentRoute />);

    expect(await screen.findByText('Not confirmed')).toBeInTheDocument();
    expect(screen.getByText('Required')).toBeInTheDocument();
    expect(startButton().disabled).toBe(true);
  });

  it('states what is being confirmed, and the law it rests on', async () => {
    stubService({ ...BASE, [GATE]: { status: 'awaiting_confirmation', prompt: PROMPT } });
    render(<ConsentRoute />);

    expect(await screen.findByText(/every participant has been informed/i)).toBeInTheDocument();
    expect(screen.getByText(/Surveillance Devices Act/)).toBeInTheDocument();
  });

  it('records consent against the person confirming it', async () => {
    const written = stubService({
      ...BASE,
      [GATE]: { status: 'awaiting_confirmation', prompt: PROMPT },
    });
    render(<ConsentRoute />);

    await userEvent.type(
      await screen.findByLabelText(/who is confirming/i),
      'Dana Whitfield, COO',
    );
    await userEvent.click(screen.getByRole('button', { name: /confirm consent/i }));

    await waitFor(() => expect(written).toHaveLength(1));
    expect(written[0]).toEqual({
      path: '/api/meetings/meeting-1/consent-confirmation',
      method: 'POST',
      body: { confirmed_by: 'Dana Whitfield, COO' },
    });
  });

  it('will not put consent on the record against nobody', async () => {
    const written = stubService({
      ...BASE,
      [GATE]: { status: 'awaiting_confirmation', prompt: PROMPT },
    });
    render(<ConsentRoute />);

    await screen.findByText('Not confirmed');
    await userEvent.click(screen.getByRole('button', { name: /confirm consent/i }));

    expect(written).toHaveLength(0);
  });

  it('shows the gate opening once consent is on the record', async () => {
    const table: Record<string, unknown> = {
      ...BASE,
      [GATE]: { status: 'awaiting_confirmation', prompt: PROMPT },
    };
    stubService(table);
    render(<ConsentRoute />);

    await userEvent.type(
      await screen.findByLabelText(/who is confirming/i),
      'Dana Whitfield, COO',
    );
    // What the service would say on the next read, once the write has landed.
    table[GATE] = { status: 'confirmed' };
    table[RECORD] = {
      meeting_id: 'meeting-1',
      confirmed_by: 'Dana Whitfield, COO',
      confirmed_at: '2026-08-20T05:56:31.811556Z',
    };
    await userEvent.click(screen.getByRole('button', { name: /confirm consent/i }));

    expect(await screen.findByText('Confirmed')).toBeInTheDocument();
    expect(screen.getByText(/Dana Whitfield, COO/)).toBeInTheDocument();
    expect(screen.getByText('On record')).toBeInTheDocument();
    await waitFor(() => expect(startButton().disabled).toBe(false));
  });

  it('says what the service said when it refuses a confirmation', async () => {
    stubService(
      { ...BASE, [GATE]: { status: 'awaiting_confirmation', prompt: PROMPT } },
      { status: 422, detail: 'confirmed_by must name a person' },
    );
    render(<ConsentRoute />);

    await userEvent.type(await screen.findByLabelText(/who is confirming/i), 'x');
    await userEvent.click(screen.getByRole('button', { name: /confirm consent/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent('confirmed_by must name a person');
  });
});

describe('consent already confirmed', () => {
  /**
   * The gate and the record are two different reads, and only the gate decides
   * whether capture may begin. A confirmed gate whose record cannot be read
   * back is exactly the write/read split the live run found; the screen must
   * still open, and must not invent a name for it.
   */
  it('opens the gate even when the record cannot be read back', async () => {
    stubService({ ...BASE, [GATE]: { status: 'confirmed' } });
    render(<ConsentRoute />);

    expect(await screen.findByText('Confirmed')).toBeInTheDocument();
    expect(startButton().disabled).toBe(false);
    expect(screen.queryByText(/Capture cannot start/)).not.toBeInTheDocument();
  });

  it('does not offer to confirm what is already confirmed', async () => {
    stubService({ ...BASE, [GATE]: { status: 'confirmed' } });
    render(<ConsentRoute />);

    await screen.findByText('Confirmed');
    expect(screen.queryByRole('button', { name: /confirm consent/i })).not.toBeInTheDocument();
  });
});

describe('starting the meeting', () => {
  /**
   * The button the whole gate exists to enable had no handler. Confirming
   * consent moved the screen from "Required" to "On record" and started
   * nothing — the gate opened onto a control that did not work.
   */
  it('opens the session the gate admitted', async () => {
    const written = stubService({ ...BASE, [GATE]: { status: 'confirmed' } });
    render(<ConsentRoute />);

    await screen.findByText('Confirmed');
    await userEvent.click(startButton());

    await waitFor(() => expect(written).toHaveLength(1));
    expect(written[0]).toMatchObject({
      path: '/api/meetings/meeting-1/session/start',
      method: 'POST',
    });
  });

  it('reports the meeting as live rather than looking like nothing happened', async () => {
    stubService({ ...BASE, [GATE]: { status: 'confirmed' } });
    render(<ConsentRoute />);

    await screen.findByText('Confirmed');
    await userEvent.click(startButton());

    expect(await screen.findByText(/Session live/i)).toBeInTheDocument();
  });

  it('will not start the same meeting twice', async () => {
    const written = stubService({ ...BASE, [GATE]: { status: 'confirmed' } });
    render(<ConsentRoute />);

    await screen.findByText('Confirmed');
    await userEvent.click(startButton());
    await screen.findByText(/Session live/i);
    await userEvent.click(startButton());

    expect(written).toHaveLength(1);
  });

  it('says why in the service’s words when the start is refused', async () => {
    stubService({ ...BASE, [GATE]: { status: 'confirmed' } }, {
      status: 403,
      detail: 'consent has not been confirmed for this meeting, so capture cannot begin',
    });
    render(<ConsentRoute />);

    await screen.findByText('Confirmed');
    await userEvent.click(startButton());

    expect(await screen.findByRole('alert')).toHaveTextContent(/consent has not been confirmed/);
  });

  it('starts nothing while consent is still outstanding', async () => {
    const written = stubService({
      ...BASE,
      [GATE]: { status: 'awaiting_confirmation', prompt: PROMPT },
    });
    render(<ConsentRoute />);

    await screen.findByText('Not confirmed');
    await userEvent.click(startButton());

    expect(written).toHaveLength(0);
  });
});
