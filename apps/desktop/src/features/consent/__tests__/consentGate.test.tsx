import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { captureSession } from '../../../services/captureSession';
import ConsentRoute from '../route';

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

const continueButton = () =>
  screen.getByRole('button', { name: /continue to recording/i }) as HTMLButtonElement;

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
    expect(continueButton().disabled).toBe(false);
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
    expect(continueButton().disabled).toBe(true);
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
    await waitFor(() => expect(continueButton().disabled).toBe(false));
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
    expect(continueButton().disabled).toBe(false);
    expect(screen.queryByText(/Capture cannot start/)).not.toBeInTheDocument();
  });

  it('does not offer to confirm what is already confirmed', async () => {
    stubService({ ...BASE, [GATE]: { status: 'confirmed' } });
    render(<ConsentRoute />);

    await screen.findByText('Confirmed');
    expect(screen.queryByRole('button', { name: /confirm consent/i })).not.toBeInTheDocument();
  });
});

describe('leaving for the recording', () => {
  /**
   * Consent is a gate, and a gate's job ends when it opens.
   *
   * This screen used to carry a Capture card with a Start button on it, which
   * booked the meeting on the service and opened no microphone — so an
   * operator was told a meeting had begun while nothing was listening. Worse,
   * the card had no way to choose an input, and the row under its heading was
   * the meeting's *language* mode, so a card titled Capture said nothing about
   * capture at all. The recording, and the choice of device, belong to the one
   * screen that can show a level meter.
   */
  it('books nothing itself', async () => {
    const written = stubService({ ...BASE, [GATE]: { status: 'confirmed' } });
    render(<ConsentRoute />);

    await screen.findByText('Confirmed');
    await userEvent.click(continueButton());

    // The meeting starts when the recording starts, and that is not here.
    expect(written).toHaveLength(0);
  });

  it('takes the operator to the recording screen', async () => {
    stubService({ ...BASE, [GATE]: { status: 'confirmed' } });
    const went: string[] = [];
    render(<ConsentRoute navigate={(to) => went.push(to)} />);

    await screen.findByText('Confirmed');
    await userEvent.click(continueButton());

    expect(went).toEqual(['#/capture']);
  });

  it('opens no microphone on the way', async () => {
    // Asserted against the application's own session, because that is the one
    // a regression here would open. This screen used to carry a Start button
    // that booked a meeting and opened nothing; the correction is not a
    // quieter version of that, it is the recording screen owning both.
    stubService({ ...BASE, [GATE]: { status: 'confirmed' } });
    render(<ConsentRoute navigate={() => undefined} />);

    await screen.findByText('Confirmed');
    await userEvent.click(continueButton());

    expect(captureSession.getSnapshot().status.state).toBe('idle');
  });

  it('holds the door shut while consent is outstanding', async () => {
    stubService({
      ...BASE,
      [GATE]: { status: 'awaiting_confirmation', prompt: PROMPT },
    });
    const went: string[] = [];
    render(<ConsentRoute navigate={(to) => went.push(to)} />);

    await screen.findByText('Not confirmed');
    expect(continueButton().disabled).toBe(true);

    await userEvent.click(continueButton());
    expect(went).toEqual([]);
  });

  it('says nothing about microphones, which are not its business', async () => {
    stubService({ ...BASE, [GATE]: { status: 'confirmed' } });
    render(<ConsentRoute />);

    await screen.findByText('Confirmed');

    expect(screen.queryByRole('heading', { name: 'Capture' })).not.toBeInTheDocument();
    // The row that used to sit under that heading showed `capture_mode`, which
    // is the language mode — "monolingual" under a heading saying Capture.
    expect(screen.queryByText(/monolingual/i)).not.toBeInTheDocument();
  });
});
