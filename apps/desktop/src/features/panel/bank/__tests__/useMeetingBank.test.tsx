import { afterEach, describe, expect, it, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';

import { useMeetingBank } from '../useMeetingBank';

function answerWith(body: unknown, status = 200) {
  return vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response);
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('the meeting bank the panel reads', () => {
  it('asks for nothing before a meeting has been chosen', () => {
    // The panel exists before capture does. Opening a request against `null`
    // would 404 in a loop for as long as the window is open.
    const fetcher = answerWith({});
    vi.stubGlobal('fetch', fetcher);
    renderHook(() => useMeetingBank(null));

    expect(fetcher).not.toHaveBeenCalled();
  });

  it('reads the meeting bank route, not the engagement compile', async () => {
    // The meeting's own recompile is what the live meeting asks from: it
    // carries the questions the last meeting left open, ahead of everything.
    const fetcher = answerWith({ meeting_id: 'meeting-1', candidates: [] });
    vi.stubGlobal('fetch', fetcher);
    renderHook(() => useMeetingBank('meeting-1'));

    await waitFor(() => expect(fetcher).toHaveBeenCalled());
    expect(String(fetcher.mock.calls[0][0])).toContain('/api/meetings/meeting-1/bank');
  });

  it('carries the short form through, which is the whole reason it is on the panel', async () => {
    vi.stubGlobal(
      'fetch',
      answerWith({
        meeting_id: 'meeting-1',
        candidates: [
          {
            id: 'c-1',
            template_section: 'Volumes',
            phrasing: 'How many arrivals a month?',
            priority: 1,
            inherited_from_open_question: false,
            stub: 'Monthly arrivals',
          },
        ],
      }),
    );
    const { result } = renderHook(() => useMeetingBank('meeting-1'));

    await waitFor(() => expect(result.current.questions).toHaveLength(1));
    expect(result.current.questions[0]).toMatchObject({
      id: 'c-1',
      stub: 'Monthly arrivals',
      phrasing: 'How many arrivals a month?',
      inherited: false,
    });
  });

  it('reports a bank compiled without stubs as having none, rather than as broken', async () => {
    // Every bank compiled before the stub reached the panel. The rail derives
    // keywords for these; the hook's job is to pass the absence through
    // faithfully rather than paper over it.
    vi.stubGlobal(
      'fetch',
      answerWith({
        meeting_id: 'meeting-1',
        candidates: [
          {
            id: 'c-1',
            template_section: 'Volumes',
            phrasing: 'How many arrivals a month?',
            priority: 1,
            inherited_from_open_question: false,
          },
        ],
      }),
    );
    const { result } = renderHook(() => useMeetingBank('meeting-1'));

    await waitFor(() => expect(result.current.questions).toHaveLength(1));
    expect(result.current.questions[0].stub).toBe('');
  });

  it('is empty rather than throwing when the service cannot be reached', async () => {
    // A bank that cannot be fetched must not take the panel down with it: the
    // nudges and the transcript are on a different connection and are still
    // arriving.
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')));
    const { result } = renderHook(() => useMeetingBank('meeting-1'));

    await waitFor(() => expect(result.current.loaded).toBe(true));
    expect(result.current.questions).toEqual([]);
  });
});
