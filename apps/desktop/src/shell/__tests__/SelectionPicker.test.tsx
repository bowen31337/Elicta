import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { SelectionPicker, optionLabels } from '../SelectionPicker';
import { loadSelectedEngagementId, useCurrentEngagement } from '../../services/selection';

/**
 * The control that says which engagement the app is about.
 *
 * Before it, `select()` existed on both selection hooks and no component
 * called it, so the app was permanently about whichever engagement the
 * service happened to return first. On a machine holding nine of them that is
 * the oldest, which had no meetings — so every screen reported there was
 * nothing to show while the operator's actual work sat one row away.
 *
 * The assertion that carries the story is `moves a screen that is already on
 * screen`: the picker lives in the toolbar and the screen is mounted
 * separately, so a choice only reaches it if the selection is shared state
 * rather than a copy per hook call.
 */

function jsonResponse(body: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response;
}

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
    {
      engagement_id: 'eng-2',
      client_organisation: 'Southbank Utilities',
      sector: 'utilities',
      commercial_context: 'Metering',
      purpose: null,
      scope_boundary: null,
      target_requirements_template: null,
    },
  ],
  total: 2,
};

const MEETINGS: Record<string, unknown> = {
  'eng-1': {
    engagement_id: 'eng-1',
    meetings: [
      {
        meeting_id: 'meeting-1',
        engagement_id: 'eng-1',
        state: 'planned',
        capture_mode: 'live',
        scheduled_at: null,
        session_purpose: 'Discovery 1',
        sections_filled: 2,
        sections_total: 6,
      },
      {
        meeting_id: 'meeting-2',
        engagement_id: 'eng-1',
        state: 'planned',
        capture_mode: 'live',
        scheduled_at: null,
        session_purpose: 'Discovery 2',
        sections_filled: null,
        sections_total: null,
      },
    ],
  },
  'eng-2': { engagement_id: 'eng-2', meetings: [] },
};

/** Answers the two discovery reads the picker makes, and nothing else. */
function stubService(): void {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (path: string) => {
      if (path === '/api/engagements') return jsonResponse(ENGAGEMENTS);
      const meetings = /^\/api\/engagements\/([^/]+)\/meetings$/.exec(path);
      if (meetings) return jsonResponse(MEETINGS[decodeURIComponent(meetings[1])]);
      return jsonResponse(null, 404);
    }),
  );
}

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('choosing an engagement', () => {
  it('offers every engagement the service knows about, under an accessible name', async () => {
    stubService();
    render(<SelectionPicker />);

    const control = await screen.findByLabelText('Engagement');
    expect(control.tagName).toBe('SELECT');
    expect(
      [...(control as HTMLSelectElement).options].map((option) => option.textContent),
    ).toEqual(['Northwind Freight', 'Southbank Utilities']);
  });

  it('shows the engagement in force, not merely the first option', async () => {
    window.localStorage.setItem('elicta.selection.engagementId', 'eng-2');
    stubService();
    render(<SelectionPicker />);

    await waitFor(() =>
      expect(screen.getByLabelText('Engagement')).toHaveValue('eng-2'),
    );
  });

  it('remembers the choice, so a reload lands where the operator left off', async () => {
    stubService();
    render(<SelectionPicker />);
    await screen.findByLabelText('Engagement');

    await userEvent.selectOptions(screen.getByLabelText('Engagement'), 'eng-2');

    expect(loadSelectedEngagementId()).toBe('eng-2');
  });

  it('moves a screen that is already on screen, with no manual refresh', async () => {
    stubService();
    function Screen() {
      const current = useCurrentEngagement();
      return <span data-testid="screen">{current.engagementId ?? 'none'}</span>;
    }
    render(
      <>
        <SelectionPicker />
        <Screen />
      </>,
    );
    await waitFor(() => expect(screen.getByTestId('screen')).toHaveTextContent('eng-1'));

    await userEvent.selectOptions(screen.getByLabelText('Engagement'), 'eng-2');

    await waitFor(() => expect(screen.getByTestId('screen')).toHaveTextContent('eng-2'));
  });

  /**
   * The machine that found this story held nine engagements, six of them
   * identical in every field the list returns except the id. A menu of six
   * rows reading "Northwind Logistics" is not a choice, so the id — the one
   * thing that actually differs — is shown where it has to be, and nowhere
   * else.
   */
  it('tells apart engagements that share a name, and leaves the rest alone', () => {
    expect(
      optionLabels([
        { id: 'eng-1', label: 'Northwind Logistics' },
        { id: 'eng-2', label: 'Northwind Logistics' },
        { id: 'eng-8', label: 'Northwind Freight' },
      ]),
    ).toEqual([
      'Northwind Logistics · eng-1',
      'Northwind Logistics · eng-2',
      'Northwind Freight',
    ]);
  });

  it('offers nothing at all when the service holds no engagements', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ items: [], total: 0 })));
    render(<SelectionPicker />);

    await waitFor(() => expect(screen.queryByLabelText('Engagement')).not.toBeInTheDocument());
  });

  it('offers nothing when the service cannot be reached, rather than an empty menu', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('Failed to fetch');
      }),
    );
    render(<SelectionPicker />);

    await waitFor(() => expect(screen.queryByLabelText('Engagement')).not.toBeInTheDocument());
  });
});

describe('choosing a meeting', () => {
  it('offers the meetings of the engagement in force', async () => {
    stubService();
    render(<SelectionPicker />);

    const control = await screen.findByLabelText('Meeting');
    expect([...(control as HTMLSelectElement).options].map((option) => option.textContent)).toEqual(
      ['Discovery 1', 'Discovery 2'],
    );
  });

  it('remembers the chosen meeting', async () => {
    stubService();
    render(<SelectionPicker />);
    await screen.findByLabelText('Meeting');

    await userEvent.selectOptions(screen.getByLabelText('Meeting'), 'meeting-1');

    expect(window.localStorage.getItem('elicta.selection.meetingId')).toBe('meeting-1');
  });

  it('drops the meeting control when the chosen engagement has none', async () => {
    window.localStorage.setItem('elicta.selection.engagementId', 'eng-2');
    stubService();
    render(<SelectionPicker />);

    await screen.findByLabelText('Engagement');
    await waitFor(() => expect(screen.queryByLabelText('Meeting')).not.toBeInTheDocument());
  });
});

describe('an engagement that has been deleted', () => {
  /**
   * Reported from the running app: delete the engagement you are on, and the
   * toolbar still names it, with its meetings still in the dropdown beside it.
   *
   * `useResource` is per component instance — `useState` and an effect, no
   * shared cache — so the Engagements screen reloading its own list left the
   * toolbar holding the answer it fetched at mount. The stored choice still
   * matched a row in *that* copy, so the fallback for "the choice no longer
   * exists" never ran: as far as the toolbar could tell, it still existed.
   */
  function stubDeletable(): { removed: Set<string> } {
    const removed = new Set<string>();
    vi.stubGlobal(
      'fetch',
      vi.fn(async (path: string, init?: RequestInit) => {
        if (init?.method === 'DELETE') {
          removed.add(path.replace('/api/engagements/', ''));
          return jsonResponse({}, 204);
        }
        if (path === '/api/engagements') {
          return jsonResponse({
            items: ENGAGEMENTS.items.filter((e) => !removed.has(e.engagement_id)),
            total: ENGAGEMENTS.items.length - removed.size,
          });
        }
        const meetings = /^\/api\/engagements\/([^/]+)\/meetings$/.exec(path);
        if (meetings) return jsonResponse(MEETINGS[decodeURIComponent(meetings[1])]);
        return jsonResponse(null, 404);
      }),
    );
    return { removed };
  }

  it('stops naming it in the toolbar, and takes its meetings with it', async () => {
    window.localStorage.setItem('elicta.selection.engagementId', 'eng-1');
    stubDeletable();
    const { deleteEngagement } = await import(
      '../../features/engagements/engagementActions'
    );
    render(<SelectionPicker />);
    await waitFor(() => expect(screen.getByLabelText('Engagement')).toHaveValue('eng-1'));
    // eng-1's meetings, which must not outlive it either.
    await waitFor(() =>
      expect(
        [...(screen.getByLabelText('Meeting') as HTMLSelectElement).options].length,
      ).toBeGreaterThan(0),
    );

    await deleteEngagement('eng-1');

    await waitFor(() =>
      expect(
        [...(screen.getByLabelText('Engagement') as HTMLSelectElement).options].map(
          (option) => option.textContent,
        ),
      ).toEqual(['Southbank Utilities']),
    );
    expect(screen.getByLabelText('Engagement')).toHaveValue('eng-2');
    // And its meetings went with it. Southbank has none, so a dropdown still
    // offering "Discovery 1" would be one client's meeting under another
    // client's name.
    await waitFor(() =>
      expect(screen.queryByText('Discovery 1')).not.toBeInTheDocument(),
    );
  });

  it('stops offering a meeting that has been deleted', async () => {
    /* The same staleness one level down, and the same toolbar. The prep
       screen deletes a meeting and reloads its own list; the dropdown beside
       the engagement name is a different component and kept offering it. */
    window.localStorage.setItem('elicta.selection.engagementId', 'eng-1');
    const gone = new Set<string>();
    vi.stubGlobal(
      'fetch',
      vi.fn(async (path: string, init?: RequestInit) => {
        if (init?.method === 'DELETE') {
          gone.add(path.replace('/api/meetings/', ''));
          return jsonResponse({}, 204);
        }
        if (path === '/api/engagements') return jsonResponse(ENGAGEMENTS);
        const meetings = /^\/api\/engagements\/([^/]+)\/meetings$/.exec(path);
        if (meetings) {
          const body = MEETINGS[decodeURIComponent(meetings[1])] as {
            engagement_id: string;
            meetings: { meeting_id: string }[];
          };
          return jsonResponse({
            ...body,
            meetings: body.meetings.filter((m) => !gone.has(m.meeting_id)),
          });
        }
        return jsonResponse(null, 404);
      }),
    );
    const { deleteMeeting } = await import('../../features/prep/prepActions');
    render(<SelectionPicker />);
    await screen.findByText('Discovery 1');

    await deleteMeeting('meeting-1');

    await waitFor(() =>
      expect(screen.queryByText('Discovery 1')).not.toBeInTheDocument(),
    );
    expect(screen.getByText('Discovery 2')).toBeInTheDocument();
  });
});
