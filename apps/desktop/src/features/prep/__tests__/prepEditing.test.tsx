import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import PrepRoute from '../route';

/**
 * Journey 1's claims, as behaviour.
 *
 * The journey says the operator tags documents, keeps the vocabulary list and
 * prunes the bank. The screen had no control for any of it — `Prune` and
 * `Compile` were buttons without handlers — so a live run against the real
 * service produced an empty screen and the journey still read as though it
 * worked. These drive the screen the way the operator does, and assert what
 * reached the service.
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

const READS: Record<string, unknown> = {
  '/api/engagements': ENGAGEMENTS,
  '/api/engagements/eng-1/documents': {
    engagement_id: 'eng-1',
    documents: [{ document_id: 'doc-1', name: 'Depot RFP.pdf', status: 'hypothesis' }],
  },
  '/api/engagements/eng-1/vocabulary': {
    engagement_id: 'eng-1',
    terms: [{ term_id: 'term-1', term: 'Depot Sequencer' }],
  },
  '/api/engagements/eng-1/meetings': {
    engagement_id: 'eng-1',
    meetings: [
      {
        meeting_id: 'meeting-1',
        engagement_id: 'eng-1',
        state: 'scheduled',
        capture_mode: 'line-in',
        scheduled_at: '2026-08-25T09:00:00Z',
        session_purpose: 'Discovery 2 — volumes',
        sections_filled: null,
        sections_total: null,
      },
    ],
  },
  '/api/engagements/eng-1/bank': {
    engagement_id: 'eng-1',
    sections: [
      {
        template_section: 'Performance',
        candidates: [
          { id: 'c-1', phrasing: 'What counts as fast, in seconds?', priority: 1, pruned: false },
          { id: 'c-2', phrasing: 'At median load or at peak?', priority: 2, pruned: false },
        ],
      },
    ],
    generated_at: '2026-08-20T00:00:00Z',
  },
};

interface Written {
  path: string;
  method: string;
  body: unknown;
}

function stubService(refusal?: { path: string; status: number; detail: unknown }) {
  const written: Written[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (path: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET';
      if (method === 'GET') {
        const body = READS[path];
        if (body === undefined) return { ok: false, status: 404, json: async () => null } as Response;
        return { ok: true, status: 200, json: async () => body } as Response;
      }
      written.push({
        path,
        method,
        body:
          init?.body === undefined
            ? undefined
            : init.body instanceof FormData
              ? Object.fromEntries(
                  [...init.body.entries()].map(([key, value]) => [
                    key,
                    value instanceof File ? value.name : value,
                  ]),
                )
              : JSON.parse(init.body as string),
      });
      if (refusal && path === refusal.path) {
        return {
          ok: false,
          status: refusal.status,
          json: async () => ({ detail: refusal.detail }),
        } as Response;
      }
      return { ok: true, status: 200, json: async () => ({}) } as Response;
    }),
  );
  return written;
}

beforeEach(() => window.localStorage.clear());
afterEach(() => vi.unstubAllGlobals());

async function ready() {
  render(<PrepRoute />);
  expect(await screen.findByRole('heading', { name: 'Northwind Freight' })).toBeInTheDocument();
}

/** Answers the first GET of each path, then leaves the refetch hanging. */
function stubWithHangingRefetch() {
  const seen = new Map<string, number>();
  const written: Written[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (path: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET';
      if (method !== 'GET') {
        written.push({ path, method, body: undefined });
        return { ok: true, status: 200, json: async () => ({}) } as Response;
      }
      const count = (seen.get(path) ?? 0) + 1;
      seen.set(path, count);
      if (count > 1) return new Promise<Response>(() => {});
      const body = READS[path];
      if (body === undefined) return { ok: false, status: 404, json: async () => null } as Response;
      return { ok: true, status: 200, json: async () => body } as Response;
    }),
  );
  return written;
}

describe('keeping the operator\'s place through a write', () => {
  /**
   * Reviewing a bank means promoting and pruning dozens of times. Each write
   * reloads the screen's reads, and while they were in flight the screen
   * rendered `ScreenState` instead of itself — so the list unmounted, came
   * back, and landed scrolled to the top. Measured against the running app: a
   * `Move up` on a sixty-question bank took the scroll container from 887 back
   * to 0, every time.
   */
  it('does not replace the screen with the loading state while a write refreshes it', async () => {
    const written = stubWithHangingRefetch();
    await ready();

    await userEvent.click(screen.getByRole('button', { name: /Prune .*What counts as fast/i }));
    await waitFor(() => expect(written).toHaveLength(1));

    expect(screen.queryByRole('heading', { name: 'Loading…' })).not.toBeInTheDocument();
    expect(screen.getByText('At median load or at peak?')).toBeInTheDocument();
  });

  it('never unmounts the screen, which is what loses the scroll position', async () => {
    // The scroll container is the pane this screen sits in, and jsdom has no
    // layout to measure. What can be asserted is the cause: the same element
    // is still on the page, so nothing was torn down and rebuilt.
    const written = stubWithHangingRefetch();
    await ready();
    const before = screen.getByRole('main');

    await userEvent.click(screen.getByRole('button', { name: /Prune .*What counts as fast/i }));
    await waitFor(() => expect(written).toHaveLength(1));

    expect(screen.getByRole('main')).toBe(before);
  });
});

describe('pruning the question bank', () => {
  it('marks the candidate pruned on the service, not only on screen', async () => {
    const written = stubService();
    await ready();

    await userEvent.click(
      screen.getByRole('button', { name: /Prune .*What counts as fast/i }),
    );

    await waitFor(() => expect(written).toHaveLength(1));
    expect(written[0]).toEqual({
      path: '/api/bank/candidates/c-1',
      method: 'PATCH',
      body: { pruned: true },
    });
  });
});

describe('reordering the question bank', () => {
  it('promotes a candidate by giving it the priority above it', async () => {
    const written = stubService();
    await ready();

    await userEvent.click(
      screen.getByRole('button', { name: /Move .*At median load or at peak.* earlier/i }),
    );

    await waitFor(() => expect(written).toHaveLength(1));
    expect(written[0]).toEqual({
      path: '/api/bank/candidates/c-2',
      method: 'PATCH',
      body: { priority: 1 },
    });
  });

  it('offers no way to promote the question that is already first', async () => {
    stubService();
    await ready();

    expect(
      screen.getByRole('button', { name: /Move .*What counts as fast.* earlier/i }),
    ).toBeDisabled();
  });
});

describe('compiling the bank', () => {
  it('asks the service to compile rather than being a button that does nothing', async () => {
    const written = stubService({ path: 'none', status: 0, detail: null });
    vi.stubGlobal(
      'fetch',
      vi.fn(async (path: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET';
        if (method === 'GET') {
          const body =
            path === '/api/engagements/eng-1/bank'
              ? { engagement_id: 'eng-1', sections: [], generated_at: '2026-08-20T00:00:00Z' }
              : READS[path];
          if (body === undefined)
            return { ok: false, status: 404, json: async () => null } as Response;
          return { ok: true, status: 200, json: async () => body } as Response;
        }
        written.push({ path, method, body: undefined });
        return { ok: true, status: 202, json: async () => ({ job_id: 'job-1' }) } as Response;
      }),
    );
    render(<PrepRoute />);
    expect(await screen.findByText('Not compiled yet')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Compile' }));

    await waitFor(() => expect(written).toHaveLength(1));
    expect(written[0].path).toBe('/api/engagements/eng-1/bank/compile');
    expect(written[0].method).toBe('POST');
  });
});

describe('the client vocabulary list', () => {
  it('adds a term with the kind of word it is', async () => {
    const written = stubService();
    await ready();

    await userEvent.type(screen.getByLabelText(/word the client uses/i), 'Zephyr WMS');
    await userEvent.selectOptions(screen.getByLabelText(/kind of word/i), 'product_name');
    await userEvent.click(screen.getByRole('button', { name: 'Add term' }));

    await waitFor(() => expect(written).toHaveLength(1));
    expect(written[0]).toEqual({
      path: '/api/engagements/eng-1/vocabulary',
      method: 'POST',
      body: { term: 'Zephyr WMS', term_type: 'product_name' },
    });
  });

  it('will not send an empty term', async () => {
    const written = stubService();
    await ready();

    await userEvent.click(screen.getByRole('button', { name: 'Add term' }));

    expect(written).toHaveLength(0);
  });
});

describe('attaching a document', () => {
  it('sends the link with the tag chosen for it', async () => {
    const written = stubService();
    await ready();

    await userEvent.type(
      screen.getByLabelText(/SharePoint, OneDrive or Teams link/i),
      'https://northwind.sharepoint.com/sites/d/RFP.pdf',
    );
    await userEvent.selectOptions(screen.getByLabelText(/How to treat it/i), 'ground truth');
    await userEvent.click(screen.getByRole('button', { name: 'Attach' }));

    await waitFor(() => expect(written).toHaveLength(1));
    expect(written[0]).toEqual({
      path: '/api/engagements/eng-1/documents/link',
      method: 'POST',
      body: { url: 'https://northwind.sharepoint.com/sites/d/RFP.pdf', status: 'ground truth' },
    });
  });

  it('shows the service’s reason when it refuses the link', async () => {
    stubService({
      path: '/api/engagements/eng-1/documents/link',
      status: 422,
      detail: [{ msg: 'Value error, url must be a SharePoint or Teams link' }],
    });
    await ready();

    await userEvent.type(
      screen.getByLabelText(/SharePoint, OneDrive or Teams link/i),
      'https://elsewhere.example/x.pdf',
    );
    await userEvent.click(screen.getByRole('button', { name: 'Attach' }));

    expect(
      await screen.findByRole('alert'),
    ).toHaveTextContent(/must be a SharePoint or Teams link/);
  });

  it('re-tags a document that is already attached', async () => {
    const written = stubService();
    await ready();

    await userEvent.selectOptions(
      screen.getByLabelText(/Tag for Depot RFP.pdf/i),
      'superseded',
    );

    await waitFor(() => expect(written).toHaveLength(1));
    expect(written[0]).toEqual({
      path: '/api/documents/doc-1/status',
      method: 'PATCH',
      body: { status: 'superseded' },
    });
  });
});

describe('when no engagement is selected', () => {
  it('sends the operator to the screen that owns clients, rather than a form here', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (path: string) =>
        path === '/api/engagements'
          ? ({ ok: true, status: 200, json: async () => ({ items: [], total: 0 }) } as Response)
          : ({ ok: false, status: 404, json: async () => null } as Response),
      ),
    );
    render(<PrepRoute />);

    expect(await screen.findByText(/Engagements screen/i)).toBeInTheDocument();
    // Creating a client belongs on that screen. It used to be here, at the
    // foot of a page headed with a different client's name.
    expect(screen.queryByLabelText(/Client organisation/i)).not.toBeInTheDocument();
  });
});

describe('taking things back out', () => {
  it('removes a document', async () => {
    const written = stubService();
    await ready();

    await userEvent.click(screen.getByRole('button', { name: /Remove .*Depot RFP\.pdf/i }));

    await waitFor(() => expect(written).toHaveLength(1));
    expect(written[0].path).toBe('/api/documents/doc-1');
    expect(written[0].method).toBe('DELETE');
  });

  it('removes a vocabulary term, which is the one a typo really costs', async () => {
    const written = stubService();
    await ready();

    await userEvent.click(screen.getByRole('button', { name: /Remove .*Depot Sequencer/i }));

    await waitFor(() => expect(written).toHaveLength(1));
    expect(written[0].path).toBe('/api/engagements/eng-1/vocabulary/term-1');
    expect(written[0].method).toBe('DELETE');
  });

  it('says the removal is recoverable rather than implying it is final', async () => {
    stubService();
    await ready();

    // Two sections say it now, which is the point: wherever you remove
    // something, it says the removal is recoverable.
    expect(screen.getAllByText(/nothing is erased/i).length).toBeGreaterThan(0);
  });
});

describe('managing meetings', () => {
  /**
   * The create-an-engagement form was rendered only when there were none at
   * all, so it vanished the moment the first one existed: an operator could
   * make their first client and never a second. And nothing anywhere created a
   * meeting, which every journey after this one needs.
   */
  it('does not offer to create or remove a client, which is another screen\'s job', async () => {
    stubService();
    await ready();

    // A guard against this creeping back: Preparation is about one client, and
    // a page headed with one name that offers a blank form for a different one
    // changes subject halfway down.
    expect(screen.queryByRole('button', { name: 'Create engagement' })).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: /Remove this engagement/i }),
    ).not.toBeInTheDocument();
  });

  it('lists the meetings this engagement already has', async () => {
    stubService();
    await ready();

    expect(await screen.findByText(/Discovery 2/)).toBeInTheDocument();
  });

  it('creates a meeting for this engagement', async () => {
    const written = stubService();
    await ready();

    await userEvent.selectOptions(screen.getByLabelText(/How the audio is captured/i), 'silent-join');
    await userEvent.click(screen.getByRole('button', { name: 'Add meeting' }));

    await waitFor(() => expect(written).toHaveLength(1));
    expect(written[0].path).toBe('/api/meetings');
    expect(written[0].method).toBe('POST');
    expect(written[0].body).toEqual({
      engagement_id: 'eng-1',
      capture_mode: 'silent-join',
    });
  });

  it('says when an engagement has no meetings rather than showing an empty box', async () => {
    stubService();
    vi.stubGlobal(
      'fetch',
      vi.fn(async (path: string, init?: RequestInit) => {
        if ((init?.method ?? 'GET') !== 'GET')
          return { ok: true, status: 201, json: async () => ({}) } as Response;
        const body =
          path === '/api/engagements/eng-1/meetings'
            ? { engagement_id: 'eng-1', meetings: [] }
            : READS[path];
        if (body === undefined)
          return { ok: false, status: 404, json: async () => null } as Response;
        return { ok: true, status: 200, json: async () => body } as Response;
      }),
    );
    render(<PrepRoute />);
    await screen.findByRole('heading', { name: 'Northwind Freight' });

    expect(await screen.findByText(/No meetings yet/i)).toBeInTheDocument();
  });
});

describe('dropping documents onto the screen', () => {
  function fileOf(name: string) {
    return new File([new Uint8Array([1, 2, 3])], name, { type: 'application/pdf' });
  }

  async function readyWithWrites() {
    const written = stubService();
    await ready();
    return written;
  }

  it('uploads a dropped file with the tag chosen beside the zone', async () => {
    const written = await readyWithWrites();

    await userEvent.selectOptions(screen.getByLabelText(/How to treat it/i), 'superseded');
    fireEvent.drop(screen.getByTestId('document-dropzone'), {
      dataTransfer: { files: [fileOf('Throughput study.pdf')], types: ['Files'] },
    });

    await waitFor(() => expect(written).toHaveLength(1));
    expect(written[0].path).toBe('/api/engagements/eng-1/documents');
    expect(written[0].method).toBe('POST');
    expect(written[0].body).toEqual({ file: 'Throughput study.pdf', status: 'superseded' });
  });

  it('still uploads with the window-wide stray-drop guard installed', async () => {
    /* The guard exists because an unhandled drop navigates the webview to the
       file, which in the packaged app has no way back. It must not claim the
       one drop that *is* handled — and the ordering that keeps it honest is
       subtle enough to be worth asserting rather than reasoning about. React
       delegates to the root container, which is below `document`, so the
       zone's `preventDefault` lands first and the guard sees the event
       already claimed. */
    const { refuseStrayDrops } = await import('../../../services/strayDrop');
    const stop = refuseStrayDrops();
    try {
      const written = await readyWithWrites();

      fireEvent.drop(screen.getByTestId('document-dropzone'), {
        dataTransfer: { files: [fileOf('Guarded.pdf')], types: ['Files'] },
      });

      await waitFor(() => expect(written).toHaveLength(1));
      expect((written[0].body as { file: string }).file).toBe('Guarded.pdf');
    } finally {
      stop();
    }
  });

  it('uploads every file in one drop, not just the first', async () => {
    const written = await readyWithWrites();

    fireEvent.drop(screen.getByTestId('document-dropzone'), {
      dataTransfer: { files: [fileOf('One.pdf'), fileOf('Two.pdf')], types: ['Files'] },
    });

    await waitFor(() => expect(written).toHaveLength(2));
    expect(written.map((w) => (w.body as { file: string }).file)).toEqual(['One.pdf', 'Two.pdf']);
  });

  it('offers a file picker as well, so the drop zone is not the only way in', async () => {
    // A drop target that cannot be reached from the keyboard is not reachable
    // at all for some operators; the audit gates this.
    await readyWithWrites();

    expect(screen.getByLabelText(/choose files/i)).toBeInTheDocument();
  });

  it('uploads what the file picker was given', async () => {
    const written = await readyWithWrites();

    await userEvent.upload(screen.getByLabelText(/choose files/i), fileOf('Picked.pdf'));

    await waitFor(() => expect(written).toHaveLength(1));
    expect(written[0].path).toBe('/api/engagements/eng-1/documents');
  });

  it('says why when the service refuses the upload', async () => {
    stubService({
      path: '/api/engagements/eng-1/documents',
      status: 422,
      detail: 'file must have a filename, or name must be provided',
    });
    await ready();

    fireEvent.drop(screen.getByTestId('document-dropzone'), {
      dataTransfer: { files: [fileOf('Broken.pdf')], types: ['Files'] },
    });

    expect(await screen.findByRole('alert')).toHaveTextContent(/must have a filename/);
  });

  it('ignores a drop that carries no files', async () => {
    const written = await readyWithWrites();

    fireEvent.drop(screen.getByTestId('document-dropzone'), {
      dataTransfer: { files: [], types: ['text/plain'] },
    });

    expect(written).toHaveLength(0);
  });
});

/**
 * The meetings list, which was one-way.
 *
 * `Add meeting` has been on this screen since the screen learned to make one,
 * and nothing took a meeting back out or told two of them apart. Three rows
 * reading `meeting-1`, `meeting-2`, `meeting-3` is what an operator saw after
 * pressing the button while working out what it did, and there was no way back
 * from any of it.
 */
describe('editing the meetings on the list', () => {
  it('removes a meeting through the service', async () => {
    const written = stubService();
    await ready();

    await userEvent.click(
      screen.getByRole('button', { name: 'Remove Discovery 2 — volumes' }),
    );

    await waitFor(() => expect(written).toHaveLength(1));
    expect(written[0].path).toBe('/api/meetings/meeting-1');
    expect(written[0].method).toBe('DELETE');
  });

  it('says what the service said when it will not remove one', async () => {
    stubService({
      path: '/api/meetings/meeting-1',
      status: 404,
      detail: 'meeting not found',
    });
    await ready();

    await userEvent.click(
      screen.getByRole('button', { name: 'Remove Discovery 2 — volumes' }),
    );

    expect(await screen.findByText('meeting not found')).toBeInTheDocument();
  });

  it('renames a meeting to the purpose the operator typed', async () => {
    const written = stubService();
    await ready();

    await userEvent.click(
      screen.getByRole('button', { name: 'Rename Discovery 2 — volumes' }),
    );
    const field = screen.getByRole('textbox', { name: 'What this meeting is for' });
    await userEvent.clear(field);
    await userEvent.type(field, 'Discovery 3 — peak volumes');
    await userEvent.click(screen.getByRole('button', { name: 'Save meeting purpose' }));

    await waitFor(() => expect(written).toHaveLength(1));
    expect(written[0].path).toBe('/api/meetings/meeting-1');
    expect(written[0].method).toBe('PATCH');
    expect(written[0].body).toEqual({ session_purpose: 'Discovery 3 — peak volumes' });
  });

  it('opens the rename field with the purpose already in it', async () => {
    // Renaming is usually amending, and retyping a sentence to change a word
    // is how an operator ends up with two meetings called almost the same.
    stubService();
    await ready();

    await userEvent.click(
      screen.getByRole('button', { name: 'Rename Discovery 2 — volumes' }),
    );

    expect(screen.getByRole('textbox', { name: 'What this meeting is for' })).toHaveValue(
      'Discovery 2 — volumes',
    );
  });

  it('leaves the meeting alone when the rename is cancelled', async () => {
    const written = stubService();
    await ready();

    await userEvent.click(
      screen.getByRole('button', { name: 'Rename Discovery 2 — volumes' }),
    );
    await userEvent.click(screen.getByRole('button', { name: 'Cancel rename' }));

    expect(written).toHaveLength(0);
    expect(screen.getByText('Discovery 2 — volumes')).toBeInTheDocument();
  });

  it('does not send a blank purpose to a service that refuses it', async () => {
    const written = stubService();
    await ready();

    await userEvent.click(
      screen.getByRole('button', { name: 'Rename Discovery 2 — volumes' }),
    );
    await userEvent.clear(screen.getByRole('textbox', { name: 'What this meeting is for' }));
    await userEvent.click(screen.getByRole('button', { name: 'Save meeting purpose' }));

    expect(written).toHaveLength(0);
    expect(await screen.findByText(/needs a purpose/i)).toBeInTheDocument();
  });

  it('names an unnamed meeting by its id, so the controls can still be told apart', async () => {
    // A meeting created and not yet described has no purpose. Two rows whose
    // buttons both read `Remove` are two buttons a screen reader cannot
    // separate, and this screen's whole point is that the operator made
    // several while working out what the button did.
    const written = stubService();
    READS['/api/engagements/eng-1/meetings'] = {
      engagement_id: 'eng-1',
      meetings: [
        (READS['/api/engagements/eng-1/meetings'] as { meetings: unknown[] }).meetings[0],
        {
          meeting_id: 'meeting-2',
          engagement_id: 'eng-1',
          state: 'scheduled',
          capture_mode: 'line-in',
          scheduled_at: null,
          session_purpose: null,
          sections_filled: null,
          sections_total: null,
        },
      ],
    };
    try {
      await ready();

      expect(screen.getByRole('button', { name: 'Remove meeting-2' })).toBeInTheDocument();

      await userEvent.click(screen.getByRole('button', { name: 'Remove meeting-2' }));
      await waitFor(() => expect(written).toHaveLength(1));
      expect(written[0].path).toBe('/api/meetings/meeting-2');
    } finally {
      READS['/api/engagements/eng-1/meetings'] = {
        engagement_id: 'eng-1',
        meetings: [
          (READS['/api/engagements/eng-1/meetings'] as { meetings: unknown[] }).meetings[0],
        ],
      };
    }
  });
});
