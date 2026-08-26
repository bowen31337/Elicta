import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import PanelRoute from '../route';

/**
 * The panel, connected.
 *
 * Every part of this screen had tests — the chips, the coverage indicator, the
 * nudge stack, the stream hook — and none of them could see that the screen
 * itself was wired to nothing. `PanelRoute` rendered `<OperatorPanel />` with
 * no props, so `meetingId` was `undefined`, `useSessionStream` took its
 * `meetingId === null` early return, and no stream was ever opened. A live run
 * recorded exactly that: coverage reading "— / —" and "No active nudge" on a
 * meeting that had a session running.
 *
 * These drive the route the way the shell mounts it, so an unbound screen
 * fails here rather than in a recording.
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

/** An `EventSource` the test drives, standing in for a real SSE connection. */
class FakeEventSource {
  static opened: string[] = [];
  static live: FakeEventSource[] = [];
  private listeners = new Map<string, ((event: MessageEvent<string>) => void)[]>();
  closed = false;

  constructor(readonly url: string) {
    FakeEventSource.opened.push(url);
    FakeEventSource.live.push(this);
  }

  addEventListener(type: string, listener: (event: MessageEvent<string>) => void) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }

  removeEventListener(type: string, listener: (event: MessageEvent<string>) => void) {
    this.listeners.set(type, (this.listeners.get(type) ?? []).filter((l) => l !== listener));
  }

  close() {
    this.closed = true;
  }

  emit(type: string, data: unknown) {
    const payload = { data: JSON.stringify(data) } as MessageEvent<string>;
    for (const listener of this.listeners.get(type) ?? []) listener(payload);
  }
}

function stubService(table: Record<string, unknown>) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (path: string) => {
      const body = table[path];
      if (body === undefined) return { ok: false, status: 404, json: async () => null } as Response;
      return { ok: true, status: 200, json: async () => body } as Response;
    }),
  );
  vi.stubGlobal('EventSource', FakeEventSource);
}

const BASE = {
  '/api/engagements': ENGAGEMENTS,
  '/api/engagements/eng-1/meetings': MEETINGS,
  // The park endpoint, so a tap can succeed. Without it the request 404s and
  // the chip correctly leaves the nudge alone — which is right, and makes a
  // test about what happens *after* a successful park impossible to write.
  '/api/threads/nudge-1/park': { open_question_id: 'open-question-1' },
};

beforeEach(() => {
  window.localStorage.clear();
  FakeEventSource.opened = [];
  FakeEventSource.live = [];
});
afterEach(() => vi.unstubAllGlobals());

const stream = () => FakeEventSource.live[0];

describe('the live panel', () => {
  it('opens the session stream for the meeting the operator has selected', async () => {
    stubService(BASE);
    render(<PanelRoute />);

    await waitFor(() =>
      expect(FakeEventSource.opened).toContain('/api/meetings/meeting-1/session/stream'),
    );
  });

  it('shows coverage from the live session rather than the placeholder', async () => {
    stubService(BASE);
    render(<PanelRoute />);
    await waitFor(() => expect(stream()).toBeDefined());

    stream().emit('coverage', {
      slots: [
        { id: 's-1', label: 'Performance', filled: true },
        { id: 's-2', label: 'Integrations', filled: false },
        { id: 's-3', label: 'Volumes', filled: false },
      ],
      time_remaining_ms: 900000,
    });

    // The placeholder chrome renders "— / —", which is a non-empty string: a
    // length check would pass while proving nothing arrived.
    expect(await screen.findByText(/1\s*\/\s*3/)).toBeInTheDocument();
  });

  it('surfaces a nudge from the live session', async () => {
    stubService(BASE);
    render(<PanelRoute />);
    await waitFor(() => expect(stream()).toBeDefined());

    stream().emit('nudge', {
      id: 'nudge-1',
      stub: 'Fast in seconds?',
      question: 'When you say the dashboard has to be fast, what does that mean in seconds?',
      trigger_reason: 'unquantified adjective — "fast"',
      created_at: 1,
    });

    expect(await screen.findByText(/what does that mean in seconds/i)).toBeInTheDocument();
    expect(screen.queryByText(/no active nudge/i)).not.toBeInTheDocument();
  });

  /**
   * Journey 3's four one-tap responses are gated on there being coverage and
   * an active nudge. Unwired, none of them ever rendered — the journey
   * described four buttons the running app did not draw.
   */
  it('offers the one-tap responses once the session is feeding it', async () => {
    stubService(BASE);
    render(<PanelRoute />);
    await waitFor(() => expect(stream()).toBeDefined());

    stream().emit('coverage', {
      slots: [{ id: 's-1', label: 'Performance', filled: false }],
      time_remaining_ms: 600000,
    });
    stream().emit('nudge', {
      id: 'nudge-1',
      stub: 'Fast in seconds?',
      question: 'What does fast mean in seconds?',
      trigger_reason: 'unquantified adjective',
      created_at: 1,
    });

    expect(await screen.findByRole('button', { name: /asked it/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /park it/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /missing/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /deeper/i })).toBeInTheDocument();
  });

  it('brings a receded nudge back, and the chips then act on it', async () => {
    /* The whole point of reaching one: not to read it — the history already
       shows its headline — but to be able to park or deepen it. */
    stubService(BASE);
    render(<PanelRoute />);
    await waitFor(() => expect(stream()).toBeDefined());

    for (const n of [1, 2]) {
      stream().emit('nudge', {
        id: `nudge-${n}`,
        stub: `Stub ${n}`,
        question: `Question ${n}?`,
        trigger_reason: `reason ${n}`,
        created_at: n,
      });
    }
    expect(await screen.findByText('Question 2?')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /Bring back Stub 1/i }));

    // The first is prominent now — its question is the one shown in full.
    expect(await screen.findByText('Question 1?')).toBeInTheDocument();
    expect(screen.queryByText('Question 2?')).not.toBeInTheDocument();
    // And the one it displaced is reachable in turn: nothing is lost.
    expect(
      screen.getByRole('button', { name: /Bring back Stub 2/i }),
    ).toBeInTheDocument();
  });

  it('keeps exactly one nudge prominent while doing it', async () => {
    /* FR-6.3's constraint is prominence, and swapping must not breach it. */
    stubService(BASE);
    render(<PanelRoute />);
    await waitFor(() => expect(stream()).toBeDefined());

    for (const n of [1, 2, 3]) {
      stream().emit('nudge', {
        id: `nudge-${n}`,
        stub: `Stub ${n}`,
        question: `Question ${n}?`,
        trigger_reason: `reason ${n}`,
        created_at: n,
      });
    }
    await screen.findByText('Question 3?');

    await userEvent.click(screen.getByRole('button', { name: /Bring back Stub 1/i }));

    expect(screen.getAllByText(/^Question \d\?$/)).toHaveLength(1);
    expect(screen.getAllByRole('button', { name: /Bring back/i })).toHaveLength(2);
  });

  function emitNudge(n: number) {
    stream().emit('nudge', {
      id: `nudge-${n}`,
      stub: `Stub ${n}`,
      question: `Question ${n}?`,
      trigger_reason: `reason ${n}`,
      created_at: n,
    });
  }

  it('puts a parked nudge down, rather than leaving it where it was', async () => {
    /* Reported: "after i park the nudge, it is still there". Parking is how
       an operator says they are done with a question for now — and the panel
       went on showing it, with the next nudge up to a minute away. So the
       card sat there already dealt with, and there was nothing to press to
       move past it.

       Retiring it to history was not safe until history became reachable:
       before that, putting a nudge down lost it for good. It is a press away
       now, which is what makes this the right behaviour rather than a
       trade. */
    stubService(BASE);
    render(<PanelRoute />);
    await waitFor(() => expect(stream()).toBeDefined());
    emitNudge(1);
    await screen.findByText('Question 1?');

    await userEvent.click(screen.getByRole('button', { name: /park it/i }));

    // Only once the park has actually landed. A refused one leaves the nudge
    // exactly where it was, because the operator's intent was not filed —
    // retiring it there would lose it quietly, which is the failure this
    // whole change is about.
    await waitFor(() => expect(screen.getByText('No active nudge')).toBeInTheDocument());
    // Put down, not thrown away.
    expect(screen.getByRole('button', { name: /Bring back Stub 1/i })).toBeInTheDocument();
  });

  it('puts a nudge down once it has been asked, too', async () => {
    stubService(BASE);
    render(<PanelRoute />);
    await waitFor(() => expect(stream()).toBeDefined());
    stream().emit('coverage', {
      slots: [{ id: 's-1', label: 'Performance', filled: false }],
      time_remaining_ms: null,
    });
    emitNudge(1);
    await screen.findByText('Question 1?');

    await userEvent.click(screen.getByRole('button', { name: /asked it/i }));

    await waitFor(() => expect(screen.getByText('No active nudge')).toBeInTheDocument());
    expect(screen.getByRole('button', { name: /Bring back Stub 1/i })).toBeInTheDocument();
  });

  it('shows a typed question as the nudge, so the chips can act on it', async () => {
    /* FR-6.9's escape hatch submitted to a handler that did nothing, and the
       field cleared on Enter — which is the gesture that means "sent". It
       signalled success for work that never happened. */
    stubService(BASE);
    render(<PanelRoute />);
    await waitFor(() => expect(stream()).toBeDefined());

    await userEvent.type(
      screen.getByLabelText('Ask a question'),
      'What happens on a bad day?{Enter}',
    );

    expect(await screen.findByText('What happens on a bad day?')).toBeInTheDocument();
    // And it is a nudge like any other, so it can be parked.
    expect(screen.getByRole('button', { name: /park it/i })).toBeInTheDocument();
  });

  it('says a typed question is on screen because it was typed', async () => {
    /* The reason line's job is to say why this is here, and "you typed it"
       is as legitimate an answer as "somebody said several". */
    stubService(BASE);
    render(<PanelRoute />);
    await waitFor(() => expect(stream()).toBeDefined());

    await userEvent.type(screen.getByLabelText('Ask a question'), 'Anything?{Enter}');

    expect(await screen.findByText(/typed by you/i)).toBeInTheDocument();
  });

  it('does not displace a typed question without keeping it', async () => {
    stubService(BASE);
    render(<PanelRoute />);
    await waitFor(() => expect(stream()).toBeDefined());
    await userEvent.type(screen.getByLabelText('Ask a question'), 'Mine?{Enter}');
    await screen.findByText('Mine?');

    emitNudge(9);

    expect(await screen.findByText('Question 9?')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Bring back Your question/i })).toBeInTheDocument();
  });

  it('does not stack up a second copy when the stream reconnects', async () => {
    /* The stream replays its whole backlog on every connect — that is how a
       panel opened mid-meeting catches up — and `EventSource` reconnects on
       its own schedule, every few minutes. Nothing deduped by id, so each
       reconnection appended the meeting's entire history to itself again.
       An operator who had seen three nudges would find six, then nine, all
       of them real and none of them new. */
    stubService(BASE);
    render(<PanelRoute />);
    await waitFor(() => expect(stream()).toBeDefined());

    emitNudge(1);
    emitNudge(2);
    await screen.findByText('Question 2?');

    // The same two arriving again, as a reconnect delivers them.
    emitNudge(1);
    emitNudge(2);

    // Settled first, then counted. Counting inside `waitFor` let the
    // assertion pass on the first check — before React had rendered the
    // duplicates — which is a test that reports the bug as fixed.
    await waitFor(() => expect(screen.getByText('Question 2?')).toBeInTheDocument());

    expect(screen.queryAllByRole('button', { name: /Bring back/i })).toHaveLength(1);
  });

  it('is short two of the four responses when no coverage frame arrives', async () => {
    /* The failure this pair documents, and the reason the test above passed
       while the panel was broken in a real meeting: it *emits* the coverage
       frame, and nothing proved the service sends one. It did not — the only
       frame kind ever queued was `nudge` — so `Asked it` and `What am I
       missing?` never rendered, and the operator had two chips where FR-6.6
       says four.

       Asserted rather than left implicit so the frame cannot be removed as
       cosmetic: it is what half the primary input is gated on. */
    stubService(BASE);
    render(<PanelRoute />);
    await waitFor(() => expect(stream()).toBeDefined());

    stream().emit('nudge', {
      id: 'nudge-1',
      stub: 'Fast in seconds?',
      question: 'What does fast mean in seconds?',
      trigger_reason: 'unquantified adjective',
      created_at: 1,
    });

    // The two that need only a nudge are there.
    expect(await screen.findByRole('button', { name: /park it/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /deeper/i })).toBeInTheDocument();
    // The two that need coverage are not.
    expect(screen.queryByRole('button', { name: /asked it/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /missing/i })).not.toBeInTheDocument();
  });

  /**
   * "An empty panel is the right resting state" — so with nothing selected the
   * panel still renders, and simply opens no stream. It must not become an
   * error screen, and it must not reconnect in a loop against a 404.
   */
  it('renders the resting panel and opens nothing when no meeting is selected', async () => {
    stubService({ '/api/engagements': { items: [], total: 0 } });
    render(<PanelRoute />);

    expect(await screen.findByLabelText('Elicitation panel')).toBeInTheDocument();
    expect(FakeEventSource.opened).toHaveLength(0);
  });
});
