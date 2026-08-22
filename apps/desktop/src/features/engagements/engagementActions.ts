/**
 * Creating and removing a client engagement.
 *
 * These lived in `features/prep/prepActions.ts` while the Preparation screen
 * carried the create form at its foot — a page headed with one client's name
 * that two-thirds of the way down offered a blank form for a different one.
 * The lifecycle of an engagement is not part of preparing one, so it moved
 * here with the screen that owns it.
 */

/** The subset of `fetch` these calls rely on, so tests supply a stub instead of a network. */
export type EngagementFetch = (input: string, init: RequestInit) => Promise<Response>;

export interface EngagementActionOptions {
  /** Overridable for tests; defaults to the global `fetch`. */
  readonly fetch?: EngagementFetch;
}

/** A FastAPI `detail`: a string from `HTTPException`, a list from model validation. */
type ServiceDetail = { detail?: string | readonly { msg?: string }[] };

async function failureMessage(response: Response): Promise<string> {
  let body: ServiceDetail | null = null;
  try {
    body = (await response.json()) as ServiceDetail;
  } catch {
    body = null;
  }
  const detail = body?.detail;
  if (typeof detail === 'string' && detail !== '') return detail;
  if (Array.isArray(detail)) {
    const first = detail.find((entry) => typeof entry?.msg === 'string' && entry.msg !== '');
    if (first?.msg !== undefined) return first.msg;
  }
  return `The service answered ${response.status}.`;
}

async function send<T>(
  path: string,
  init: RequestInit,
  options: EngagementActionOptions,
): Promise<T | null> {
  const { fetch: fetchImpl = fetch } = options;
  let response: Response;
  try {
    response = await fetchImpl(path, {
      ...init,
      headers: { 'Content-Type': 'application/json', Accept: 'application/json', ...init.headers },
    });
  } catch {
    throw new Error('The service could not be reached.');
  }
  if (!response.ok) throw new Error(await failureMessage(response));
  try {
    return (await response.json()) as T;
  } catch {
    return null;
  }
}

export interface NewEngagement {
  readonly clientOrganisation: string;
  readonly sector: string;
  readonly commercialContext: string;
}

/**
 * "Who the client is, the sector, and the commercial shape of the engagement" —
 * the three things journey 1 opens with, and the three the service requires.
 */
export async function createEngagement(
  engagement: NewEngagement,
  options: EngagementActionOptions = {},
): Promise<string> {
  const created = await send<{ engagement_id: string }>(
    '/api/engagements',
    {
      method: 'POST',
      body: JSON.stringify({
        client_organisation: engagement.clientOrganisation,
        sector: engagement.sector,
        commercial_context: engagement.commercialContext,
      }),
    },
    options,
  );
  return created?.engagement_id ?? '';
}

/**
 * Removes an engagement from view. Soft: the record is kept and can be brought
 * back, so this is a way to tidy a list rather than a way to erase a client.
 */
export async function deleteEngagement(
  engagementId: string,
  options: EngagementActionOptions = {},
): Promise<void> {
  await send(
    `/api/engagements/${encodeURIComponent(engagementId)}`,
    { method: 'DELETE' },
    options,
  );
}
