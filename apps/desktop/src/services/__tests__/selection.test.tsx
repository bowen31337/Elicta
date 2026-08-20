import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  loadSelectedEngagementId,
  useCurrentEngagement,
  useCurrentMeeting,
  meetingTitle,
} from '../selection';
import { useResource } from '../useResource';

/**
 * The screens were shipped rendering hardcoded empty props because nothing
 * could tell them which engagement they were about. These cover the two
 * things that would make the replacement worse than the placeholder: an
 * unreachable service that reads as "no data", and a remembered choice that
 * silently moves.
 */

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
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

const MEETINGS = {
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
};

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function EngagementProbe() {
  const current = useCurrentEngagement();
  return (
    <div>
      <span data-testid="status">{current.status}</span>
      <span data-testid="id">{current.engagementId ?? 'none'}</span>
      <span data-testid="error">{current.error ?? ''}</span>
      <button type="button" onClick={() => current.select('eng-2')}>
        pick second
      </button>
    </div>
  );
}

describe('the current engagement', () => {
  it('falls back to the first the service knows about when nothing was chosen', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(ENGAGEMENTS)));
    render(<EngagementProbe />);

    await waitFor(() => expect(screen.getByTestId('id')).toHaveTextContent('eng-1'));
    expect(screen.getByTestId('status')).toHaveTextContent('ready');
  });

  it('returns to the engagement that was chosen last time', async () => {
    window.localStorage.setItem('elicta.selection.engagementId', 'eng-2');
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(ENGAGEMENTS)));
    render(<EngagementProbe />);

    await waitFor(() => expect(screen.getByTestId('id')).toHaveTextContent('eng-2'));
  });

  it('persists a choice so it survives a reload', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(ENGAGEMENTS)));
    render(<EngagementProbe />);
    await waitFor(() => expect(screen.getByTestId('id')).toHaveTextContent('eng-1'));

    await userEvent.click(screen.getByRole('button', { name: 'pick second' }));

    expect(loadSelectedEngagementId()).toBe('eng-2');
    await waitFor(() => expect(screen.getByTestId('id')).toHaveTextContent('eng-2'));
  });

  it('does not persist the fallback, so a later engagement can still surface', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(ENGAGEMENTS)));
    render(<EngagementProbe />);

    await waitFor(() => expect(screen.getByTestId('id')).toHaveTextContent('eng-1'));
    expect(loadSelectedEngagementId()).toBeNull();
  });

  it('reports an unreachable service as an error, not as no engagements', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('Failed to fetch');
      }),
    );
    render(<EngagementProbe />);

    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('error'));
    expect(screen.getByTestId('id')).toHaveTextContent('none');
    expect(screen.getByTestId('error')).not.toHaveTextContent('');
  });

  it('reports a service with no engagements as ready, not as an error', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ items: [], total: 0 })));
    render(<EngagementProbe />);

    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('ready'));
    expect(screen.getByTestId('id')).toHaveTextContent('none');
  });
});

function MeetingProbe({ engagementId }: { engagementId: string | null }) {
  const current = useCurrentMeeting(engagementId);
  return (
    <div>
      <span data-testid="status">{current.status}</span>
      <span data-testid="id">{current.meetingId ?? 'none'}</span>
      <span data-testid="count">{current.meetings.length}</span>
    </div>
  );
}

describe('the current meeting', () => {
  it('asks nothing until an engagement is known', async () => {
    const fetchMock = vi.fn(async () => jsonResponse(MEETINGS));
    vi.stubGlobal('fetch', fetchMock);
    render(<MeetingProbe engagementId={null} />);

    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('idle'));
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('defaults to the most recent meeting of the engagement', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(MEETINGS)));
    render(<MeetingProbe engagementId="eng-1" />);

    await waitFor(() => expect(screen.getByTestId('id')).toHaveTextContent('meeting-2'));
    expect(screen.getByTestId('count')).toHaveTextContent('2');
  });

  it('honours a remembered meeting that still belongs to the engagement', async () => {
    window.localStorage.setItem('elicta.selection.meetingId', 'meeting-1');
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(MEETINGS)));
    render(<MeetingProbe engagementId="eng-1" />);

    await waitFor(() => expect(screen.getByTestId('id')).toHaveTextContent('meeting-1'));
  });

  it('ignores a remembered meeting from another engagement', async () => {
    window.localStorage.setItem('elicta.selection.meetingId', 'meeting-99');
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(MEETINGS)));
    render(<MeetingProbe engagementId="eng-1" />);

    await waitFor(() => expect(screen.getByTestId('id')).toHaveTextContent('meeting-2'));
  });
});

describe('a meeting heading', () => {
  it('names the client and what the session was for', () => {
    expect(meetingTitle(ENGAGEMENTS.items[0], MEETINGS.meetings[0])).toBe(
      'Northwind Freight — Discovery 1',
    );
  });

  it('says plainly that nothing is selected rather than showing an em dash', () => {
    expect(meetingTitle(null, null)).toBe('No meeting selected');
  });
});

function ResourceProbe({ path }: { path: string | null }) {
  const resource = useResource<{ ok: boolean }>(path);
  return <span data-testid="status">{resource.status}</span>;
}

describe('reading one thing from the service', () => {
  it('treats a 404 as missing, not as an error', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(null, 404)));
    render(<ResourceProbe path="/api/anything" />);

    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('missing'));
  });

  it('treats a 500 as an error, not as missing', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(null, 500)));
    render(<ResourceProbe path="/api/anything" />);

    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('error'));
  });
});
