import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import PanelRoute from '../route';
import { setApiClient } from '../../../services/apiClient';
import { createApiClient } from 'api-client';

/**
 * Everything an operator needs mid-meeting, on the one screen they are on.
 *
 * Two things were missing and both cost the same thing — a navigation away
 * from a client's face. The bank was reviewable only on the Preparation
 * screen, so a question compiled, read and meant to be asked was, at the
 * moment of asking, behind a route change. And the panel could show a question
 * but never the sentence that provoked it, so its resting state meant both
 * "nothing worth asking" and "nothing heard", which are not a pair an operator
 * should be guessing between while somebody is talking.
 */
const ENGAGEMENTS = {
  items: [
    {
      engagement_id: 'eng-1',
      client_organisation: 'Northwind Logistics',
      sector: 'Freight and logistics',
      commercial_context: 'Fixed-price discovery',
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
      state: 'live',
      capture_mode: 'line-in',
      scheduled_at: null,
      session_purpose: 'Discovery 3',
      sections_filled: null,
      sections_total: null,
    },
  ],
};

const BANK = {
  meeting_id: 'meeting-1',
  candidates: [
    {
      id: 'c-1',
      template_section: 'Volumes',
      phrasing: 'How many arrivals do you handle in a month, across all three sites?',
      priority: 1,
      inherited_from_open_question: false,
      stub: 'Monthly arrivals',
    },
    {
      id: 'c-2',
      template_section: 'Exceptions',
      phrasing: 'What happens to a booking when a vessel is late?',
      priority: 2,
      inherited_from_open_question: true,
      stub: 'Late vessel, booking',
    },
  ],
  generated_at: '2026-09-02T10:00:00Z',
};

class FakeEventSource {
  static live: FakeEventSource[] = [];
  private listeners = new Map<string, ((event: MessageEvent<string>) => void)[]>();

  constructor(readonly url: string) {
    FakeEventSource.live.push(this);
  }

  addEventListener(type: string, listener: (event: MessageEvent<string>) => void) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }

  removeEventListener(type: string, listener: (event: MessageEvent<string>) => void) {
    this.listeners.set(type, (this.listeners.get(type) ?? []).filter((l) => l !== listener));
  }

  close() {}

  emit(type: string, data: unknown) {
    const payload = { data: JSON.stringify(data) } as MessageEvent<string>;
    for (const listener of this.listeners.get(type) ?? []) listener(payload);
  }
}

function stubService(table: Record<string, unknown>) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (path: string) => {
      const body = table[String(path)];
      if (body === undefined) return { ok: false, status: 404, json: async () => null } as Response;
      return { ok: true, status: 200, json: async () => body } as Response;
    }),
  );
  vi.stubGlobal('EventSource', FakeEventSource);
  setApiClient(createApiClient('http://service.test'));
}

const BASE = {
  '/api/engagements': ENGAGEMENTS,
  '/api/engagements/eng-1/meetings': MEETINGS,
  '/api/meetings/meeting-1/bank': BANK,
};

beforeEach(() => {
  window.localStorage.clear();
  FakeEventSource.live = [];
});
afterEach(() => vi.unstubAllGlobals());

const stream = () => FakeEventSource.live[0];

describe('the transcript on the panel', () => {
  it('shows a line the room said even though it earned no question', async () => {
    stubService(BASE);
    render(<PanelRoute />);
    await waitFor(() => expect(stream()).toBeDefined());

    stream().emit('utterance', {
      seq: 0,
      text: 'We run three hundred and fifty consignments a day.',
      speaker: 'client',
      at: 1_700_000_000_000,
    });

    expect(
      await screen.findByText('We run three hundred and fifty consignments a day.'),
    ).toBeInTheDocument();
  });

  it('keeps both speakers, so an answer can be read against its question', async () => {
    stubService(BASE);
    render(<PanelRoute />);
    await waitFor(() => expect(stream()).toBeDefined());

    stream().emit('utterance', { seq: 0, text: 'How many a day?', speaker: 'operator', at: 1 });
    stream().emit('utterance', { seq: 1, text: 'Three fifty.', speaker: 'client', at: 2 });

    expect(await screen.findByText('How many a day?')).toBeInTheDocument();
    expect(screen.getByText('Three fifty.')).toBeInTheDocument();
  });
});

describe('the bank on the panel', () => {
  it('offers the meeting\'s questions as keywords, without leaving the screen', async () => {
    stubService(BASE);
    render(<PanelRoute />);

    expect(await screen.findByRole('button', { name: /monthly arrivals/i })).toBeInTheDocument();
    // The wording is not on screen — it is 66 characters, and reading it is
    // the thing this panel exists to avoid.
    expect(screen.queryByText(/across all three sites/)).not.toBeInTheDocument();
  });

  it('promotes a tapped question into the prominent slot, where the chips act', async () => {
    // FR-6.3 constrains prominence to one question at a time. Tapping the rail
    // changes which question that is; it does not add a second.
    stubService(BASE);
    render(<PanelRoute />);

    await userEvent.click(await screen.findByRole('button', { name: /monthly arrivals/i }));

    expect(
      await screen.findByText(
        'How many arrivals do you handle in a month, across all three sites?',
      ),
    ).toBeInTheDocument();
    // The chips that act on a live question are now there to act on it.
    expect(screen.getByRole('button', { name: /asked it/i })).toBeInTheDocument();
  });

  it('takes a question off the rail once it has been asked', async () => {
    // The rail is what to ask next. One still sitting there after it was asked
    // is one the operator has to remember not to repeat.
    stubService(BASE);
    render(<PanelRoute />);

    await userEvent.click(await screen.findByRole('button', { name: /monthly arrivals/i }));
    await userEvent.click(screen.getByRole('button', { name: /asked it/i }));

    await waitFor(() =>
      expect(screen.queryByRole('button', { name: /^monthly arrivals$/i })).not.toBeInTheDocument(),
    );
    // The one not yet asked is still offered.
    expect(screen.getByRole('button', { name: /late vessel/i })).toBeInTheDocument();
  });

  it('says why it is empty rather than showing a blank rail', async () => {
    // An empty rail and a bank that never compiled look identical on screen,
    // and one of those is something the operator can still go and fix.
    //
    // The bank has to have been *asked for* before this means anything: the
    // rail renders the same words before a meeting is bound, so asserting the
    // text alone would pass against a panel that never requested a bank.
    stubService({
      ...BASE,
      '/api/meetings/meeting-1/bank': { meeting_id: 'meeting-1', candidates: [] },
    });
    render(<PanelRoute />);

    await waitFor(() =>
      expect(
        (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls.map((call) => String(call[0])),
      ).toContain('/api/meetings/meeting-1/bank'),
    );
    expect(await screen.findByText(/no questions/i)).toBeInTheDocument();
  });
});

describe('a meeting nothing will transcribe', () => {
  it('says so on the panel rather than reading as a quiet room', async () => {
    stubService(BASE);
    render(<PanelRoute />);
    await waitFor(() => expect(stream()).toBeDefined());

    stream().emit('lane', {
      model_reachable: true,
      reason: null,
      live_transcription: false,
    });

    expect(await screen.findByText(/speech credential/i)).toBeInTheDocument();
  });

  it('says nothing of the sort while the room is being transcribed', async () => {
    stubService(BASE);
    render(<PanelRoute />);
    await waitFor(() => expect(stream()).toBeDefined());

    stream().emit('lane', { model_reachable: true, reason: null, live_transcription: true });
    stream().emit('utterance', { seq: 0, text: 'Three fifty.', speaker: 'client', at: 1 });

    expect(await screen.findByText('Three fifty.')).toBeInTheDocument();
    expect(screen.queryByText(/speech credential/i)).not.toBeInTheDocument();
  });
});
