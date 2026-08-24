import { createApiClient, type ApiClient } from 'api-client';

import { shellAvailable } from './shell';

/**
 * The panel's single connection to the service tier.
 *
 * Every module in `features/` that needs the service takes an `ApiClient`
 * as an argument rather than importing one, so a component or hook stays
 * testable against a stub and there is exactly one place that decides where
 * the service actually lives.
 *
 * The base URL comes from `VITE_SERVICE_BASE_URL` at build time, falling
 * back to whichever answer suits where the page is being served from.
 */
export const DEFAULT_SERVICE_BASE_URL = 'http://127.0.0.1:8000';

export function serviceBaseUrl(): string {
  const configured = import.meta.env?.VITE_SERVICE_BASE_URL;
  if (typeof configured === 'string' && configured.length > 0) return configured;

  // In a browser the page is served by the dev server or by `vite preview`,
  // both of which proxy `/api` to the service. Relative is then not merely
  // adequate but correct: the request stays same-origin, which is what a
  // service mounting no CORS middleware requires, and it needs no build-time
  // configuration to work on a laptop or on a LAN address.
  //
  // The packaged shell serves the page from its own protocol, where nothing
  // answers `/api`. The service runs alongside the app rather than inside it,
  // so there the request has to name it.
  return shellAvailable() ? DEFAULT_SERVICE_BASE_URL : '';
}

/**
 * Where `path` should actually be requested from.
 *
 * Every call to the service goes through here. The alternative — a relative
 * path written at each call site — is invisible until the app is packaged,
 * and then fails everywhere at once.
 */
export function apiUrl(path: string): string {
  return joinServicePath(serviceBaseUrl(), path);
}

/**
 * The base and the path, joined without inventing an origin.
 *
 * `VITE_SERVICE_BASE_URL=/` is how the web run says "this page's own origin,
 * through the proxy". Concatenated as-is it yields `//api/meetings/...`, which
 * is protocol-relative and addressed to a host called `api` — so every
 * request in the application fails at once, and silently, because a stream
 * that never opens looks exactly like a service with nothing to say.
 */
export function joinServicePath(base: string, path: string): string {
  return `${base.replace(/\/+$/, '')}${path}`;
}

let shared: ApiClient | null = null;

/** The process-wide client, created on first use. */
export function getApiClient(): ApiClient {
  if (shared === null) {
    shared = createApiClient(serviceBaseUrl());
  }
  return shared;
}

/** Replaces the shared client. Tests use this; production code does not. */
export function setApiClient(client: ApiClient | null): void {
  shared = client;
}

export type { ApiClient };
