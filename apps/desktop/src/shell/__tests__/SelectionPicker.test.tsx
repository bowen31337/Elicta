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
