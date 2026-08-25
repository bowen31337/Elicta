import { renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { announceServiceReady, useResource } from '../useResource';

/**
 * The cold start.
 *
 * The shell brings the window up before the service answers, deliberately: a
 * frozen Python takes seconds to unpack and import, and blocking on it means
 * no window at all for that long. The half that was missing is that the
 * screens asked once. A genuine cold start — nothing already holding port
 * 8000 — made zero API requests for the life of the window and sat on "Cannot
 * reach the service" against a service that came up two seconds later.
 *
 * The shell knows when the service starts answering and now says so. This is
 * the front end acting on it, and it is deliberately not a retry budget:
 * guessing would delay every genuine failure by the length of the guess.
 */
describe('when the shell announces the service is ready', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('a screen that was refused asks again', async () => {
    let up = false;
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        if (!up) throw new TypeError('Failed to fetch');
        return { ok: true, status: 200, json: async () => ({ items: [] }) };
      }),
    );

    const { result } = renderHook(() => useResource<{ items: unknown[] }>('/api/engagements'));
    await waitFor(() => expect(result.current.status).toBe('error'));

    up = true;
    announceServiceReady();

    await waitFor(() => expect(result.current.status).toBe('ready'));
  });

  it('an unreachable service is still reported at once, with no announcement', async () => {
    // The property the retry approach would have broken: a service that is
    // genuinely down says so immediately, rather than after a budget of
    // hopeful waiting.
    const fetchMock = vi.fn(async () => {
      throw new TypeError('Failed to fetch');
    });
    vi.stubGlobal('fetch', fetchMock);

    const { result } = renderHook(() => useResource('/api/engagements'));

    await waitFor(() => expect(result.current.status).toBe('error'));
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
