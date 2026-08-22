import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { useResource } from '../useResource';

/**
 * The read behind every full screen, and the difference between the two
 * reasons it re-runs.
 *
 * A screen reloads its reads after every write, which is cheaper than tracking
 * which write invalidates which read. That was costing the operator their
 * place: the reload dropped the resource back to `loading`, the screen
 * rendered `ScreenState` instead of itself, and the list unmounted and came
 * back scrolled to the top. On a bank of sixty questions, promoting one sent
 * you back to the documents at the top of the page.
 *
 * Refetching the *same* path is therefore not the same event as pointing at a
 * *different* one, and only the second may blank the screen.
 */
afterEach(() => vi.unstubAllGlobals());

/** Answers the first GET of each path, then never answers again. */
function stubAnsweringOnce(bodies: Record<string, unknown>) {
  const seen = new Map<string, number>();
  vi.stubGlobal(
    'fetch',
    vi.fn(async (path: string) => {
      const count = (seen.get(path) ?? 0) + 1;
      seen.set(path, count);
      if (count > 1) return new Promise<Response>(() => {});
      const body = bodies[path];
      if (body === undefined) return { ok: false, status: 404, json: async () => null } as Response;
      return { ok: true, status: 200, json: async () => body } as Response;
    }),
  );
}

describe('reloading a resource', () => {
  it('keeps the answer it already has while the refetch is in flight', async () => {
    stubAnsweringOnce({ '/api/thing': { n: 1 } });
    const { result } = renderHook(() => useResource<{ n: number }>('/api/thing'));
    await waitFor(() => expect(result.current.status).toBe('ready'));

    act(() => result.current.reload());

    // The refetch never answers. A screen reading this must still have
    // something true to render — the answer from a moment ago.
    expect(result.current.status).toBe('ready');
    expect(result.current.data).toEqual({ n: 1 });
  });

  it('shows the new answer once the refetch lands', async () => {
    const bodies: Record<string, unknown> = { '/api/thing': { n: 1 } };
    vi.stubGlobal(
      'fetch',
      vi.fn(async (path: string) => ({
        ok: true,
        status: 200,
        json: async () => bodies[path],
      }) as Response),
    );
    const { result } = renderHook(() => useResource<{ n: number }>('/api/thing'));
    await waitFor(() => expect(result.current.data).toEqual({ n: 1 }));

    bodies['/api/thing'] = { n: 2 };
    act(() => result.current.reload());

    await waitFor(() => expect(result.current.data).toEqual({ n: 2 }));
    expect(result.current.status).toBe('ready');
  });

  it('blanks the screen when the path changes, rather than showing the last one', async () => {
    // The guard on the change above. Holding the previous answer here would
    // show one engagement's documents under another engagement's name, which
    // is worse than a moment of "Loading…".
    stubAnsweringOnce({ '/api/a': { n: 1 }, '/api/b': { n: 2 } });
    const { result, rerender } = renderHook(({ path }) => useResource<{ n: number }>(path), {
      initialProps: { path: '/api/a' },
    });
    await waitFor(() => expect(result.current.status).toBe('ready'));

    rerender({ path: '/api/b' });

    expect(result.current.status).toBe('loading');
  });

  it('reports a refetch that cannot reach the service', async () => {
    // Staleness may not outlive the connection: a screen holding a cheerful
    // `ready` through an outage is the failure this whole module exists to
    // prevent.
    let answer = true;
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        if (!answer) throw new TypeError('Failed to fetch');
        return { ok: true, status: 200, json: async () => ({ n: 1 }) } as Response;
      }),
    );
    const { result } = renderHook(() => useResource<{ n: number }>('/api/thing'));
    await waitFor(() => expect(result.current.status).toBe('ready'));

    answer = false;
    act(() => result.current.reload());

    await waitFor(() => expect(result.current.status).toBe('error'));
    expect(result.current.data).toBeNull();
  });
});
