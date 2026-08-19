import { createApiClient, type ApiClient } from 'api-client';

/**
 * The panel's single connection to the service tier.
 *
 * Every module in `features/` that needs the service takes an `ApiClient`
 * as an argument rather than importing one, so a component or hook stays
 * testable against a stub and there is exactly one place that decides where
 * the service actually lives.
 *
 * The base URL comes from `VITE_SERVICE_BASE_URL` at build time, falling
 * back to the local service's default port so a developer running
 * `uvicorn app.main:app` needs no configuration.
 */
export const DEFAULT_SERVICE_BASE_URL = 'http://127.0.0.1:8000';

export function serviceBaseUrl(): string {
  const configured = import.meta.env?.VITE_SERVICE_BASE_URL;
  return typeof configured === 'string' && configured.length > 0
    ? configured
    : DEFAULT_SERVICE_BASE_URL;
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
