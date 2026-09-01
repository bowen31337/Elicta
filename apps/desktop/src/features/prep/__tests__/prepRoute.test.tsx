import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import PrepRoute from '../route';

/**
 * The preparation screen, connected.
 *
 * It used to render `clientOrganisation="—"` with three empty lists, which is
 * exactly what a working screen looks like for an engagement nobody has
 * touched — and exactly what it looks like when the service is not running.
 * These assert the three pictures are now different.
 */
const ENGAGEMENTS = {
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
};

const ROUTES: Record<string, unknown> = {
  '/api/engagements': ENGAGEMENTS,
  '/api/engagements/eng-1/documents': {
    engagement_id: 'eng-1',
    documents: [
      { document_id: 'doc-1', name: 'Depot RFP.pdf', status: 'ground truth' },
      { document_id: 'doc-2', name: 'Slack thread.txt', status: 'hypothesis' },
    ],
  },
  '/api/engagements/eng-1/vocabulary': {
    engagement_id: 'eng-1',
    terms: [{ term: 'Depot Sequencer' }, { term: 'TMS' }],
  },
  '/api/engagements/eng-1/bank': {
    engagement_id: 'eng-1',
    sections: [
      {
        template_section: 'Performance',
        candidates: [
          { id: 'c-1', phrasing: 'What counts as fast, in seconds?', priority: 1, pruned: false },
          { id: 'c-2', phrasing: 'A pruned one', priority: 2, pruned: true },
        ],
      },
    ],
    generated_at: '2026-08-20T00:00:00Z',
  },
};

function stubService(overrides: Record<string, unknown> = {}) {
  const table = { ...ROUTES, ...overrides };
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

describe('the preparation screen', () => {
  it('shows the engagement the service knows about, not an em dash', async () => {
    stubService();
    render(<PrepRoute />);

    expect(await screen.findByRole('heading', { name: 'Northwind Freight' })).toBeInTheDocument();
  });

  it('lists the documents and the vocabulary that were actually attached', async () => {
    stubService();
    render(<PrepRoute />);

    expect(await screen.findByText('Depot RFP.pdf')).toBeInTheDocument();
    expect(screen.getByText('Slack thread.txt')).toBeInTheDocument();
    // The tag is a control now rather than a pill, because journey 1 says the
    // operator chooses it — so what is asserted is the control's value, which
    // is the same claim about the same data and additionally proves the
    // service's tag is what the control opens on.
    expect(screen.getByLabelText('Tag for Depot RFP.pdf')).toHaveValue('ground truth');
    expect(screen.getByLabelText('Tag for Slack thread.txt')).toHaveValue('hypothesis');
    expect(screen.getByText('Depot Sequencer')).toBeInTheDocument();
  });

  it('does not claim a document is indexed, which nothing here knows', async () => {
    stubService();
    render(<PrepRoute />);

    await screen.findByText('Depot RFP.pdf');
    // The row used to carry "Indexed for retrieval" as a fixed subtitle under
    // every document. The document list returns an id, a name and a tag — no
    // indexing state — and a linked document's text is not read at all until
    // the connector for it exists. So the line asserted a pipeline stage that
    // does not run, under documents whose text nothing had opened.
    expect(screen.queryByText('Indexed for retrieval')).not.toBeInTheDocument();
  });

  it('leaves a pruned candidate out of the bank', async () => {
    stubService();
    render(<PrepRoute />);

    expect(await screen.findByText('What counts as fast, in seconds?')).toBeInTheDocument();
    expect(screen.queryByText('A pruned one')).not.toBeInTheDocument();
  });

  it('says the bank is not compiled when the service returns no sections', async () => {
    stubService({
      '/api/engagements/eng-1/bank': {
        engagement_id: 'eng-1',
        sections: [],
        generated_at: '2026-08-20T00:00:00Z',
      },
    });
    render(<PrepRoute />);

    expect(await screen.findByText('Not compiled yet')).toBeInTheDocument();
  });

  it('says the service is unreachable rather than showing an empty engagement', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('Failed to fetch');
      }),
    );
    render(<PrepRoute />);

    expect(
      await screen.findByRole('heading', { name: 'Cannot reach the service' }),
    ).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: '—' })).not.toBeInTheDocument();
  });

  it('says plainly that no engagement exists rather than rendering a blank one', async () => {
    stubService({ '/api/engagements': { items: [], total: 0 } });
    render(<PrepRoute />);

    expect(
      await screen.findByRole('heading', { name: 'Nothing selected yet' }),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByText(/Engagements screen/)).toBeInTheDocument(),
    );
  });
});

describe('a compile that ran and stopped', () => {
  /**
   * The screen said "Not compiled yet" after four compiles had run and failed.
   * `POST /bank/compile` answers 202 whatever happens next and the bank answers
   * an empty list whatever the reason, so between them they were capable of
   * saying nothing at all about four consecutive failures.
   *
   * The reason was recorded every time. It went to the service log, which is
   * not where the operator is.
   */
  const EMPTY_BANK = { '/api/engagements/eng-1/bank': { engagement_id: 'eng-1', sections: [] } };

  function outcome(over: Record<string, unknown>) {
    return {
      '/api/engagements/eng-1/bank/compile': {
        engagement_id: 'eng-1',
        compile_id: 'compile-4',
        complete: false,
        stages_completed: [],
        stopped_at: 'extraction',
        reason: 'a stage [not_entitled]: the model provider refused this request',
        ...over,
      },
    };
  }

  it('still says "not compiled yet" when nothing has been tried', async () => {
    // The compile route 404s: no attempt has been made. That is not a failure
    // and must not be dressed as one.
    stubService(EMPTY_BANK);
    render(<PrepRoute />);

    expect(await screen.findByText('Not compiled yet')).toBeInTheDocument();
  });

  it('says a credential that may not use the model will not fix itself', async () => {
    stubService({ ...EMPTY_BANK, ...outcome({ cause: 'not_entitled' }) });
    render(<PrepRoute />);

    const notice = await screen.findByRole('alert');
    expect(notice).toHaveTextContent(/reading the documents/i);
    expect(notice).toHaveTextContent(/not permitted/i);
    expect(notice).toHaveTextContent(/waiting will not help/i);
    expect(screen.queryByText('Not compiled yet')).not.toBeInTheDocument();
  });

  it('tells a real throttle apart from that, because one does clear', async () => {
    stubService({ ...EMPTY_BANK, ...outcome({ cause: 'rate_limited' }) });
    render(<PrepRoute />);

    const notice = await screen.findByRole('alert');
    expect(notice).toHaveTextContent(/throttling/i);
    expect(notice).not.toHaveTextContent(/waiting will not help/i);
  });

  it('points at Settings when no provider is configured at all', async () => {
    stubService({ ...EMPTY_BANK, ...outcome({ cause: 'not_configured' }) });
    render(<PrepRoute />);

    expect(await screen.findByRole('alert')).toHaveTextContent(/no ai provider/i);
  });

  it('names the direct drafting route in words, not by its internal name', async () => {
    // "stopped while analyst pass direct" is what the hyphen-stripping
    // fallback produces, and it reads like a stack frame. Every stage the
    // compile can actually stop at gets said in words.
    stubService({
      ...EMPTY_BANK,
      ...outcome({ stopped_at: 'analyst-pass-direct', cause: 'failed' }),
    });
    render(<PrepRoute />);

    const notice = await screen.findByRole('alert');
    expect(notice).toHaveTextContent(/drafting the questions/i);
    expect(notice.textContent).not.toMatch(/analyst pass direct/i);
  });

  it('names the drafting step when the batch itself was refused', async () => {
    stubService({
      ...EMPTY_BANK,
      ...outcome({ stopped_at: 'batch-submission', cause: 'not_entitled' }),
    });
    render(<PrepRoute />);

    expect(await screen.findByRole('alert')).toHaveTextContent(/drafting job/i);
  });

  it('never puts the pipeline\'s own words on the screen', async () => {
    stubService({
      ...EMPTY_BANK,
      ...outcome({
        cause: 'not_entitled',
        reason: 'a stage [not_entitled]: OAuth token does not meet scope requirement '
          + 'any_of(user:batch, user:developer, workspace:developer, workspace:inference)',
      }),
    });
    render(<PrepRoute />);

    const notice = await screen.findByRole('alert');
    expect(notice.textContent).not.toMatch(/any_of|user:batch|workspace:/);
  });

  it('says nothing when the compile finished', async () => {
    stubService({
      ...EMPTY_BANK,
      ...outcome({ complete: true, stopped_at: null, reason: null, cause: null }),
    });
    render(<PrepRoute />);

    await screen.findByText('Not compiled yet');
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });
});

describe('a compile that is still running', () => {
  /**
   * The third state. A compile now runs outside its request, so between
   * pressing the button and the chain finishing there is a real interval in
   * which nothing has stopped it and nothing has finished either — and the
   * screen has to say so rather than pick one of the other two.
   */
  const RUNNING = {
    '/api/engagements/eng-1/bank': { engagement_id: 'eng-1', sections: [] },
    '/api/engagements/eng-1/bank/compile': {
      engagement_id: 'eng-1',
      compile_id: 'compile-5',
      state: 'running',
      complete: false,
      stages_completed: [],
      stopped_at: null,
      reason: null,
      cause: null,
    },
  };

  it('says it is working rather than that nothing has been tried', async () => {
    stubService(RUNNING);
    render(<PrepRoute />);

    expect(await screen.findByText(/compiling now/i)).toBeInTheDocument();
    expect(screen.queryByText('Not compiled yet')).not.toBeInTheDocument();
  });

  it('does not offer to start another one on top of it', async () => {
    // Pressing Compile again is exactly what someone does when a screen looks
    // idle, and two chains writing one bank is a race with no winner worth
    // having.
    stubService(RUNNING);
    render(<PrepRoute />);

    await screen.findByText(/compiling now/i);
    expect(screen.getByRole('button', { name: /compil/i })).toBeDisabled();
  });
});
