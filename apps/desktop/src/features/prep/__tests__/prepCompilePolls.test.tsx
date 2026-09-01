import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import PrepRoute from '../route';

/**
 * A compile the screen never asks about again.
 *
 * Reported from a screenshot: the meter reading 13% while the service had the
 * compile finished — all three stages done. The Preparation screen reads the
 * compile once, when it mounts, and nothing re-reads it. So the meter showed
 * whatever was true at the moment the screen opened and stayed there for the
 * whole five minutes, which reads exactly like a compile that is stuck.
 *
 * `compile.reload()` was not even in the manual reload, so pressing anything
 * else on the screen did not refresh it either.
 */
const ENGAGEMENTS = { items: [{ engagement_id: 'eng-1', client_organisation: 'Acme' }] };

function serving(compile: unknown) {
  const table: Record<string, unknown> = {
    '/api/engagements': ENGAGEMENTS,
    '/api/engagements/eng-1': { engagement_id: 'eng-1', client_organisation: 'Acme' },
    '/api/engagements/eng-1/documents': { items: [] },
    '/api/engagements/eng-1/vocabulary': { items: [] },
    '/api/engagements/eng-1/bank': { sections: [] },
    '/api/engagements/eng-1/meetings': { engagement_id: 'eng-1', meetings: [] },
    '/api/engagements/eng-1/bank/compile': compile,
  };
  return table;
}

let table: Record<string, unknown>;

beforeEach(() => {
  window.localStorage.clear();
  vi.stubGlobal(
    'fetch',
    vi.fn(async (path: string) => {
      const body = table[String(path)];
      if (body === undefined) {
        return { ok: false, status: 404, json: async () => null } as Response;
      }
      return { ok: true, status: 200, json: async () => body } as Response;
    }),
  );
});
afterEach(() => vi.unstubAllGlobals());

describe('a compile the screen is watching', () => {
  it('asks again while one is running, so the meter moves', async () => {
    table = serving({
      state: 'running',
      complete: false,
      stages_completed: [],
      stopped_at: null,
      reason: null,
      cause: null,
    });
    render(<PrepRoute />);

    // Reading the documents: nothing finished, one under way. No start time
    // in this fixture, so the stage under way counts as half.
    expect(await screen.findByText('5%')).toBeInTheDocument();

    // The service moves on. Nothing on the screen is touched.
    table = serving({
      state: 'running',
      complete: false,
      stages_completed: ['extraction', 'structuring'],
      stopped_at: null,
      reason: null,
      cause: null,
    });

    await waitFor(() => expect(screen.getByText('18%')).toBeInTheDocument(), {
      timeout: 8000,
    });
  }, 12000);

  it('stops asking once the compile has settled', async () => {
    table = serving({
      state: 'complete',
      complete: true,
      stages_completed: ['extraction', 'structuring', 'analyst-pass-direct'],
      stopped_at: null,
      reason: null,
      cause: null,
    });
    render(<PrepRoute />);

    await screen.findByText('100%');
    const asked = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls.filter(
      ([path]) => String(path).endsWith('/bank/compile'),
    ).length;

    await new Promise((resolve) => setTimeout(resolve, 2500));

    const askedLater = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls.filter(
      ([path]) => String(path).endsWith('/bank/compile'),
    ).length;
    expect(askedLater).toBe(asked);
  }, 12000);
});
