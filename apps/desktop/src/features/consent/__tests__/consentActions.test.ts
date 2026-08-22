import { describe, expect, it, vi } from 'vitest';

import { confirmConsent, startSession } from '../consentActions';

/**
 * The one write the consent screen makes.
 *
 * `POST /api/meetings/{id}/consent-confirmation` has existed since the gate
 * did, and nothing in the desktop app ever called it. The screen showed
 * "Capture cannot start until someone confirms this on the record" and offered
 * no way to confirm — so journey 2 described a gate whose only key was `curl`.
 */
function stubFetch(body: unknown, { ok = true, status = 201 } = {}) {
  return vi.fn(
    async (_path: string, _init: RequestInit) => ({ ok, status, json: async () => body }) as Response,
  );
}

describe('confirming consent', () => {
  it('records it against the person who confirmed it', async () => {
    const fetch = stubFetch({
      meeting_id: 'meeting-9',
      confirmed_by: 'Dana Whitfield, COO',
      confirmed_at: '2026-08-20T05:56:31.811556Z',
    });

    const record = await confirmConsent('meeting-9', 'Dana Whitfield, COO', { fetch });

    const [path, init] = fetch.mock.calls[0];
    expect(path).toBe('/api/meetings/meeting-9/consent-confirmation');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body as string)).toEqual({ confirmed_by: 'Dana Whitfield, COO' });
    expect(record.confirmedBy).toBe('Dana Whitfield, COO');
  });

  it('escapes a meeting id rather than pasting it into the path', async () => {
    const fetch = stubFetch({ meeting_id: 'a/b', confirmed_by: 'X', confirmed_at: '2026-01-01T00:00:00Z' });

    await confirmConsent('a/b', 'X', { fetch });

    expect(fetch.mock.calls[0][0]).toBe('/api/meetings/a%2Fb/consent-confirmation');
  });

  /**
   * The service requires a non-empty `confirmed_by` (`Field(min_length=1)`).
   * Refusing here keeps an accidental blank from reaching a durable record
   * that exists to say who is accountable.
   */
  it('refuses to record consent against nobody', async () => {
    const fetch = stubFetch({});

    await expect(confirmConsent('meeting-9', '   ', { fetch })).rejects.toThrow(
      /who is confirming/i,
    );
    expect(fetch).not.toHaveBeenCalled();
  });

  it('passes on the service’s own refusal rather than a status code', async () => {
    const fetch = stubFetch({ detail: 'consent has not been confirmed for this meeting' }, {
      ok: false,
      status: 403,
    });

    await expect(confirmConsent('meeting-9', 'Dana Whitfield, COO', { fetch })).rejects.toThrow(
      'consent has not been confirmed for this meeting',
    );
  });

  it('distinguishes a service it cannot reach from one that refused', async () => {
    const fetch = vi.fn(async () => {
      throw new TypeError('Failed to fetch');
    });

    await expect(confirmConsent('meeting-9', 'Dana Whitfield, COO', { fetch })).rejects.toThrow(
      'The service could not be reached.',
    );
  });
});

describe('starting the session', () => {
  it('starts it for the meeting the gate just opened', async () => {
    const fetch = stubFetch(
      {
        session_id: 'session-4',
        meeting_id: 'meeting-9',
        started_at: '2026-08-20T05:56:32.721819Z',
      },
      { status: 200 },
    );

    const session = await startSession('meeting-9', { fetch });

    const [path, init] = fetch.mock.calls[0];
    expect(path).toBe('/api/meetings/meeting-9/session/start');
    expect(init.method).toBe('POST');
    expect(session.sessionId).toBe('session-4');
    expect(session.startedAt).toBe('2026-08-20T05:56:32.721819Z');
  });

  /**
   * The service refuses with 403 and a sentence naming consent. That sentence
   * is the whole point — a live run once recorded this same refusal arriving
   * as a 404 for a meeting the service could not find, which is a 4xx for the
   * wrong reason and tells the operator nothing.
   */
  it('passes on a refusal that names consent', async () => {
    const fetch = stubFetch(
      { detail: 'consent has not been confirmed for this meeting, so capture cannot begin' },
      { ok: false, status: 403 },
    );

    await expect(startSession('meeting-9', { fetch })).rejects.toThrow(/consent has not been confirmed/);
  });

  it('distinguishes a service it cannot reach', async () => {
    const fetch = vi.fn(async () => {
      throw new TypeError('Failed to fetch');
    });

    await expect(startSession('meeting-9', { fetch })).rejects.toThrow(
      'The service could not be reached.',
    );
  });
});
