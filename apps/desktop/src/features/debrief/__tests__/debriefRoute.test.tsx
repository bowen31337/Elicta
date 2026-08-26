import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
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
  const written: { path: string; method: string }[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (path: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET';
      if (method !== 'GET') {
        written.push({ path, method });
        return { ok: true, status: 202, json: async () => ({ started: true }) } as Response;
      }
      const body = table[path];
      if (body === undefined) return { ok: false, status: 404, json: async () => null } as Response;
      return { ok: true, status: 200, json: async () => body } as Response;
    }),
  );
  return written;
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

describe('a debrief that could not finish', () => {
  /**
   * Journey 5's other half. The pipeline fails closed, so a stage that cannot
   * reach a model halts the chain and the screen simply renders fewer
   * artifacts — indistinguishable from a meeting where nothing was decided.
   *
   * The service has always recorded which stage stopped and why. Until this
   * screen says so, "recorded" and "visible afterwards" were different claims.
   */
  const STOPPED = {
    session_id: 'meeting-7',
    complete: false,
    stages_completed: ['diarization', 'cleaning'],
    stopped_at: 'translation',
    reason: 'The AI provider could not be reached.',
    cause: 'failed',
  };

  it('says which stage stopped, and why, rather than looking empty', async () => {
    stubService({
      ...BASE,
      '/api/meetings/meeting-7/debrief/completion': STOPPED,
    });
    render(<DebriefRoute />);

    expect(await screen.findByRole('alert')).toHaveTextContent(/translating/i);
    expect(screen.getByRole('alert')).toHaveTextContent(/did not get through/i);
  });

  it('never puts the pipeline\'s own words on the operator\'s screen', async () => {
    /**
     * A live run rendered this, verbatim, to whoever was reading the debrief:
     * "supply `diarize` to anthropic_debrief_engines() from the configured ASR
     * vendor (architecture §3.3, ADR-011)". True, and addressed to somebody
     * else. The stage records are written for whoever is debugging the
     * pipeline; the screen composes its own sentence from the kind of failure.
     */
    stubService({
      ...BASE,
      '/api/meetings/meeting-7/debrief/completion': {
        ...STOPPED,
        stopped_at: 'diarization',
        cause: 'not_configured',
        reason:
          'diarization needs a speech vendor to tell the voices apart, and none is configured.',
      },
    });
    render(<DebriefRoute />);

    const notice = await screen.findByRole('alert');
    expect(notice).toHaveTextContent(/telling the voices apart/i);
    expect(notice).toHaveTextContent(/not set up/i);
    expect(notice.textContent).not.toMatch(/anthropic_debrief_engines|ADR-|§/);
  });

  it('says a stage failed without claiming to know why, when it does not', async () => {
    stubService({
      ...BASE,
      '/api/meetings/meeting-7/debrief/completion': {
        ...STOPPED,
        cause: 'unknown',
        reason: null,
      },
    });
    render(<DebriefRoute />);

    const notice = await screen.findByRole('alert');
    expect(notice).toHaveTextContent(/translating/i);
    expect(notice).not.toHaveTextContent(/not set up/i);
  });

  it('says nothing when the write-up finished', async () => {
    stubService({
      ...BASE,
      ...ARTIFACTS,
      '/api/meetings/meeting-7/debrief/completion': {
        session_id: 'meeting-7',
        complete: true,
        stages_completed: ['diarization'],
        stopped_at: null,
        reason: null,
      },
    });
    render(<DebriefRoute />);

    await screen.findByText('A depot scheduling rebuild.');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('says nothing when no debrief has been run at all', async () => {
    // The route 404s, which means "not asked for yet" — not a failure, and a
    // notice here would appear on every meeting whose write-up is still to come.
    stubService({ ...BASE });
    render(<DebriefRoute />);

    await screen.findByText('Open questions');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('says why it is empty when no write-up has been run', async () => {
    /**
     * The four routes behind this screen 404 for a meeting nobody has
     * debriefed, which is correct — and left the screen as two empty headings
     * and nothing else. An operator cannot tell that from a meeting where
     * nothing was decided, and the Recording screen one click away already
     * says which of the two it is looking at.
     */
    stubService({ ...BASE });
    render(<DebriefRoute />);

    expect(await screen.findByText(/no write-up has been produced/i)).toBeInTheDocument();
  });

  it('does not blame the operator for a write-up nothing asks them to start', async () => {
    // It runs on its own once the recording is transcribed. Telling somebody
    // to press a button that does not exist is worse than saying nothing.
    stubService({ ...BASE });
    render(<DebriefRoute />);

    expect(await screen.findByText(/once the recording has been transcribed/i)).toBeInTheDocument();
  });

  it('tells a write-up that finished empty from one never run', async () => {
    stubService({
      ...BASE,
      '/api/meetings/meeting-7/debrief/completion': {
        session_id: 'meeting-7',
        complete: true,
        stages_completed: ['diarization'],
        stopped_at: null,
        reason: null,
        cause: null,
      },
    });
    render(<DebriefRoute />);

    expect(await screen.findByText(/finished without producing/i)).toBeInTheDocument();
    expect(screen.queryByText(/no write-up has been produced/i)).not.toBeInTheDocument();
  });

  it('offers to produce the write-up rather than only explaining its absence', async () => {
    /* The reported state: a meeting with a transcript, no write-up, and a
       screen saying one "runs on its own once the recording has been
       transcribed" — which had already happened. The sentence was true of
       the mechanism and false of this meeting, and there was nothing to
       press.

       The pipeline runs itself once, when the second record-path engine
       finishes. A run lost to a restart, or one whose engines were
       misconfigured at the time, leaves a meeting owed a write-up with no
       way to ask for it. */
    stubService(BASE);
    render(<DebriefRoute />);
    await screen.findByText(/no write-up has been produced/i);

    expect(
      screen.getByRole('button', { name: /write it up/i }),
    ).toBeInTheDocument();
  });

  it('asks the service for it when that is pressed', async () => {
    const written = stubService(BASE);
    render(<DebriefRoute />);
    await screen.findByText(/no write-up has been produced/i);

    await userEvent.click(screen.getByRole('button', { name: /write it up/i }));

    await waitFor(() =>
      expect(written.some((w) => w.path.endsWith('/debrief/run'))).toBe(true),
    );
  });

  it('says it once: a stopped run explains itself without a second notice', async () => {
    // `incompleteNotice` already ends "Nothing below is missing on purpose."
    stubService({
      ...BASE,
      '/api/meetings/meeting-7/debrief/completion': STOPPED,
    });
    render(<DebriefRoute />);

    await screen.findByRole('alert');
    expect(screen.queryByText(/no write-up has been produced/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/finished without producing/i)).not.toBeInTheDocument();
  });

  it('stays quiet about emptiness while the artifacts are still loading', async () => {
    // A notice that flashes before the answer arrives trains people to ignore
    // it. Nothing here resolves, so nothing may claim the screen is empty.
    vi.stubGlobal(
      'fetch',
      vi.fn(async (path: string) => {
        const body = BASE[path];
        if (body !== undefined) return { ok: true, status: 200, json: async () => body } as Response;
        return new Promise<Response>(() => {});
      }),
    );
    render(<DebriefRoute />);

    await screen.findByText('Open questions');
    expect(screen.queryByText(/no write-up has been produced/i)).not.toBeInTheDocument();
  });

  it('names a stage it has no plain name for, rather than saying nothing', async () => {
    // A stage added to the pipeline later has no entry in the wording table.
    // Falling silent would hide the notice exactly when it is least expected.
    stubService({
      ...BASE,
      '/api/meetings/meeting-7/debrief/completion': {
        ...STOPPED,
        stopped_at: 'some-new-stage',
      },
    });
    render(<DebriefRoute />);

    expect(await screen.findByRole('alert')).toHaveTextContent(/some new stage/i);
  });

  it('names the stage even when the reason is missing', async () => {
    // A stage refused before it was attempted records no error. The stage name
    // alone is still enough to act on, and dropping the notice would hide it.
    stubService({
      ...BASE,
      '/api/meetings/meeting-7/debrief/completion': {
        ...STOPPED,
        reason: null,
        cause: 'unknown',
      },
    });
    render(<DebriefRoute />);

    expect(await screen.findByRole('alert')).toHaveTextContent(/translating/i);
  });
});
