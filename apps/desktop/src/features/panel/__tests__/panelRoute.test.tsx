import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import PanelRoute from '../route';
import { setApiClient } from '../../../services/apiClient';
import { createApiClient } from 'api-client';

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

/** Every request the panel made, so a test can assert one was made at all. */
let fetchMock: ReturnType<typeof vi.fn>;

function stubService(table: Record<string, unknown>) {
  fetchMock = vi.fn(async (path: string) => {
    const body = table[path];
    if (body === undefined) return { ok: false, status: 404, json: async () => null } as Response;
    return { ok: true, status: 200, json: async () => body } as Response;
  });
  vi.stubGlobal('fetch', fetchMock);
  vi.stubGlobal('EventSource', FakeEventSource);

  /* Built here, after the stub, and given an absolute base.

     `openapi-fetch` binds `globalThis.fetch` when the client is created, and
     the client is a module-level singleton — so one built before this line,
     or left over from another test, keeps calling a fetch nobody is
     watching.

     The base matters just as much. In the app it is either the page's own
     origin (a browser resolves a relative url against it) or the service's
     address (the packaged shell). Under jsdom neither applies: `Request`
     refuses a relative url outright, `recordNudgeDisposition` catches that
     and returns `false`, and every chip reporting through the client
     no-opped silently — so no test in this file could have caught a POST
     that never happened. */
  setApiClient(createApiClient('http://service.test'));
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
    expect(await screen.findByText(/1 of 3/)).toBeInTheDocument();
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
    await waitFor(() => expect(screen.getByText(/Listening/)).toBeInTheDocument());
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

    await waitFor(() => expect(screen.getByText(/Listening/)).toBeInTheDocument());
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

  it('leaves only the chip that says what to do next once a nudge is dealt with', async () => {
    /* Reported: "after park it there are still chips shown".

       Three of the four are about the nudge — `Asked it` says you asked it,
       `Park it` says not now, `Go deeper` asks for another on the same
       thread — and all three should go when it does. `Asked it` did not,
       because it was bound to a coverage slot rather than to the nudge, so
       it rendered permanently whether anything had been suggested or not.
       FR-6.7 settles which it is: it "suppresses re-suggestion", and there
       is nothing to re-suggest without a question that was suggested.

       `What am I missing?` stays, and this is the moment it is most for:
       the operator has just finished with something and is deciding what to
       raise next. */
    stubService(BASE);
    render(<PanelRoute />);
    await waitFor(() => expect(stream()).toBeDefined());
    stream().emit('coverage', {
      slots: [{ id: 's-1', label: 'Performance', filled: false }],
      time_remaining_ms: null,
    });
    emitNudge(1);
    await screen.findByText('Question 1?');
    expect(screen.getByRole('button', { name: /asked it/i })).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /park it/i }));

    await waitFor(() => expect(screen.getByText(/Listening/)).toBeInTheDocument());
    expect(screen.queryByRole('button', { name: /asked it/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /park it/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /deeper/i })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /missing/i })).toBeInTheDocument();
  });

  it('records the tap on the service and leaves the meter to it', async () => {
    /* The meter used to move on the tap, from a `localStorage` record the
       panel merged over the stream's coverage. Two things were wrong with
       that and the second is worse: the count was a record of taps wearing
       the clothes of a measurement, and the slot it credited was whichever
       one happened to be first unfilled — nothing to do with the nudge. A
       live meeting reported eight of eight covered after eight questions
       about "a lot" and "some". */
    stubService(BASE);
    render(<PanelRoute />);
    await waitFor(() => expect(stream()).toBeDefined());
    stream().emit('coverage', {
      slots: [
        { id: 's-1', label: 'Volumes', filled: false },
        { id: 's-2', label: 'Performance', filled: false },
      ],
      time_remaining_ms: null,
    });
    emitNudge(1);
    await screen.findByText(/0 of 2/);

    await userEvent.click(screen.getByRole('button', { name: /asked it/i }));

    await waitFor(() =>
      expect(
        // The client builds a `Request`, so the url is read off whichever
        // argument carries it rather than assumed to be the first.
        fetchMock.mock.calls.some(([target]) =>
          String((target as Request)?.url ?? target).includes('/disposition'),
        ),
      ).toBe(true),
    );
    // And the meter has not budged on the panel's own authority.
    expect(screen.getByText(/0 of 2/)).toBeInTheDocument();
  });

  it('shows the meter the service sends, including after a reconnect', async () => {
    /* One answer, in one place. The panel holding a second copy is what made
       a reconnect either wipe the operator's work or preserve a number the
       service disagreed with, depending on which half won. */
    stubService(BASE);
    render(<PanelRoute />);
    await waitFor(() => expect(stream()).toBeDefined());
    const slots = (filled: readonly string[]) => ({
      slots: [
        { id: 's-1', label: 'Volumes', filled: filled.includes('s-1') },
        { id: 's-2', label: 'Performance', filled: filled.includes('s-2') },
      ],
      time_remaining_ms: null,
    });
    stream().emit('coverage', slots([]));
    await screen.findByText(/0 of 2/);

    // The service says one is now asked about — which is what a recorded
    // disposition looks like arriving back.
    stream().emit('coverage', slots(['s-1']));
    expect(await screen.findByText(/1 of 2/)).toBeInTheDocument();

    // A reconnect re-sends the same truth, so nothing flickers back.
    stream().emit('coverage', slots(['s-1']));
    await waitFor(() => expect(screen.getByText(/1 of 2/)).toBeInTheDocument());
  });

  it('keeps what the operator marked when they visit another screen', async () => {
    /* Reported: "when page switches, the nudge progress bar status is
       reset". The router mounts a different component per destination, so
       leaving the panel unmounted every piece of its own state — including
       which sections had been marked.

       It survives now for a duller and better reason than the module store
       that used to hold it: the mark is in the database, so the new
       connection is simply told the same thing the old one was. */
    stubService(BASE);
    const first = render(<PanelRoute />);
    await waitFor(() => expect(stream()).toBeDefined());
    const frame = {
      slots: [
        { id: 's-1', label: 'Volumes', filled: true },
        { id: 's-2', label: 'Performance', filled: false },
      ],
      time_remaining_ms: null,
    };
    stream().emit('coverage', frame);
    await screen.findByText(/1 of 2/);

    // Away to another screen, and back.
    first.unmount();
    const opened = FakeEventSource.live.length;
    render(<PanelRoute />);
    // The *new* connection. `stream()` is `live[0]`, which after a remount is
    // the one that was just closed — emitting there proves nothing.
    await waitFor(() => expect(FakeEventSource.live.length).toBeGreaterThan(opened));
    FakeEventSource.live[FakeEventSource.live.length - 1].emit('coverage', frame);

    expect(await screen.findByText(/1 of 2/)).toBeInTheDocument();
  });

  it('brings one back when nothing is active, which is when it is wanted', async () => {
    /* Reported: "tap it to bring it back does not work".

       The guard read `if (current.active === null || ...) return current`.
       The null clause was defensive noise and it broke the main case:
       nothing being active is exactly the state parking leaves, and exactly
       when an operator reaches for a question they put down. Every test
       written for this had an active nudge, so none of them went near it. */
    stubService(BASE);
    render(<PanelRoute />);
    await waitFor(() => expect(stream()).toBeDefined());
    emitNudge(1);
    await screen.findByText('Question 1?');
    await userEvent.click(screen.getByRole('button', { name: /park it/i }));
    await waitFor(() => expect(screen.getByText(/Listening/)).toBeInTheDocument());

    await userEvent.click(screen.getByRole('button', { name: /Bring back Stub 1/i }));

    expect(await screen.findByText('Question 1?')).toBeInTheDocument();
    // And it is out of history, because it is here.
    expect(screen.queryByRole('button', { name: /Bring back Stub 1/i })).toBeNull();
  });

  it('is short one of the four responses when no coverage frame arrives', async () => {
    /* The failure this pair documents, and the reason the test above passed
       while the panel was broken in a real meeting: it *emits* the coverage
       frame, and nothing proved the service sends one. It did not — the only
       frame kind ever queued was `nudge` — so `What am I missing?` never
       rendered, and the operator was short of the four FR-6.6 asks for.

       `Asked it` used to be gated on coverage too, and that gating is what
       made it vanish for good once every section had been marked: with no
       chip there was no way to record a disposition, so nothing was ever
       marked "Asked" again. It is about the nudge, and it is offered
       whenever there is one.

       Asserted rather than left implicit so the frame cannot be removed as
       cosmetic: the summary is what `What am I missing?` reads. */
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

    // The three that need only a nudge are there.
    expect(await screen.findByRole('button', { name: /park it/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /deeper/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /asked it/i })).toBeInTheDocument();
    // The one that needs a coverage summary to read is not.
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
