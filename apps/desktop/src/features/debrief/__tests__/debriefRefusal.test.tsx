import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import DebriefRoute from '../route';

/**
 * A refusal is an answer, and it belongs on the screen.
 *
 * `POST /debrief/run` refuses a meeting with nothing transcribed, and says
 * why. The hook discarded the response entirely — it fired the request,
 * reloaded the four reads, and got back exactly what was there before. On
 * screen that is a button that does nothing, which is what was reported.
 */
const ENGAGEMENTS = { items: [{ engagement_id: 'eng-1', client_organisation: 'Acme' }] };
const MEETINGS = {
  engagement_id: 'eng-1',
  meetings: [{ meeting_id: 'meeting-7', engagement_id: 'eng-1', session_purpose: 'Day 2' }],
};

function stub(runResponse: { status: number; body: unknown }) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (path: string, init?: RequestInit) => {
      const url = String(path);
      if (init?.method === 'POST' && url.includes('/debrief/run')) {
        return {
          ok: runResponse.status < 400,
          status: runResponse.status,
          json: async () => runResponse.body,
        } as Response;
      }
      if (url.endsWith('/api/engagements')) {
        return { ok: true, status: 200, json: async () => ENGAGEMENTS } as Response;
      }
      if (url.includes('/meetings') && !url.includes('debrief')) {
        return { ok: true, status: 200, json: async () => MEETINGS } as Response;
      }
      return { ok: false, status: 404, json: async () => null } as Response;
    }),
  );
}

beforeEach(() => window.localStorage.clear());
afterEach(() => vi.unstubAllGlobals());

describe('asking for a write-up that cannot be produced', () => {
  it('shows what the service said, as an alert', async () => {
    stub({
      status: 409,
      body: {
        detail:
          'This meeting has no completed transcript to write up. Transcribe the recording first.',
      },
    });
    render(<DebriefRoute />);

    const button = await screen.findByRole('button', { name: /write it up now/i });
    await userEvent.click(button);

    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent(/no completed transcript/i),
    );
  });

  it('says something actionable even when the refusal carries no reason', async () => {
    stub({ status: 500, body: null });
    render(<DebriefRoute />);

    await userEvent.click(await screen.findByRole('button', { name: /write it up now/i }));

    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent(/could not be started/i),
    );
  });
});
