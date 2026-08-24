import { afterEach, describe, expect, it } from 'vitest';

import { apiUrl, joinServicePath } from '../apiClient';

/**
 * Where a request for `/api/...` actually goes.
 *
 * In a browser the page is served by the dev server or by `vite preview`,
 * both of which proxy `/api` to the service, so a relative path is right: the
 * request stays same-origin and needs no configuration at all.
 *
 * The packaged shell serves the page from its own protocol, where nothing
 * answers `/api` — so every one of these calls resolves against an origin
 * with no service behind it and fails. That is not a degraded mode: it is the
 * panel's stream, the audio upload and the consent gate, all silent. The
 * service runs alongside the app rather than inside it, so the shell has to
 * be told where it is.
 */
function withShell(present: boolean) {
  if (present) (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__ = {};
  else delete (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__;
}

afterEach(() => withShell(false));

describe('the address a request is sent to', () => {
  it('stays relative in a browser, where the page is proxied to the service', () => {
    withShell(false);

    expect(apiUrl('/api/meetings/meeting-1/session/stream')).toBe(
      '/api/meetings/meeting-1/session/stream',
    );
  });

  it('names the service in the shell, where a relative path reaches nothing', () => {
    withShell(true);

    expect(apiUrl('/api/meetings/meeting-1/session/stream')).toBe(
      'http://127.0.0.1:8000/api/meetings/meeting-1/session/stream',
    );
  });
});


describe('joining a configured base to a path', () => {
  it('treats a lone slash as "same origin", which is what start.sh configures', () => {
    // `VITE_SERVICE_BASE_URL=/` is how the web run says "the page's own
    // origin, through the proxy". Concatenated naively it produces
    // `//api/meetings/...` — protocol-relative, addressed to a host called
    // `api` — and every request in the app fails at once. Which is what it
    // did.
    expect(joinServicePath('/', '/api/meetings/m1/session/stream')).toBe(
      '/api/meetings/m1/session/stream',
    );
  });

  it('leaves a real service address alone', () => {
    expect(joinServicePath('http://127.0.0.1:8000', '/api/x')).toBe('http://127.0.0.1:8000/api/x');
  });

  it('does not double the separator when the address ends in one', () => {
    expect(joinServicePath('http://127.0.0.1:8000/', '/api/x')).toBe('http://127.0.0.1:8000/api/x');
  });
});
