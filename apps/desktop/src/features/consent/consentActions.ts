/**
 * The write the consent screen makes (PRD feature 246, L1/L2).
 *
 * `POST /api/meetings/{id}/consent-confirmation` existed from the day the gate
 * did, and nothing in the desktop app ever called it. The screen rendered
 * "Capture cannot start until someone confirms this on the record" above a
 * disabled button and offered no way to confirm anything — so the only key to
 * the gate journey 2 is built around was `curl`.
 *
 * Written as a plain function over an injectable `fetch`, the way
 * `prepActions` and `stopSession` are, so it is testable without a component
 * and without a network.
 */

/** The subset of `fetch` this module relies on, so tests supply a stub instead of a network. */
export type ConsentFetch = (input: string, init: RequestInit) => Promise<Response>;

export interface ConsentActionOptions {
  /** Overridable for tests; defaults to the global `fetch`. */
  readonly fetch?: ConsentFetch;
}

/** What the service recorded: who is accountable for consent, and when they said so. */
export interface ConsentRecordResult {
  readonly meetingId: string;
  readonly confirmedBy: string;
  readonly confirmedAt: string;
}

interface WireConsentRecord {
  readonly meeting_id: string;
  readonly confirmed_by: string;
  readonly confirmed_at: string;
}

/** A FastAPI `detail`: a string from `HTTPException`, a list from model validation. */
type ServiceDetail = { detail?: string | readonly { msg?: string }[] };

/**
 * What went wrong, in the service's own words where it offered them.
 *
 * A refusal here is the gate doing its job, and the sentence it refuses with
 * is the only part the operator can act on — replacing it with "the service
 * answered 403" would throw that away.
 */
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

async function post<T>(path: string, body: unknown, options: ConsentActionOptions): Promise<T> {
  const { fetch: fetchImpl = fetch } = options;
  let response: Response;
  try {
    response = await fetchImpl(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify(body ?? {}),
    });
  } catch {
    // Distinguished from a refusal on purpose: an unreachable service and a
    // gate that said no need different things from the operator.
    throw new Error('The service could not be reached.');
  }
  if (!response.ok) throw new Error(await failureMessage(response));
  return (await response.json()) as T;
}

/**
 * Puts consent on the record for one meeting, against a named person.
 *
 * The name is required and is not the participants' — it identifies whoever
 * is accountable for having disclosed the recording and confirmed that
 * everyone agreed to it. An empty one is refused here rather than sent,
 * because a durable record naming nobody answers the question it exists for
 * with a blank.
 */
export async function confirmConsent(
  meetingId: string,
  confirmedBy: string,
  options: ConsentActionOptions = {},
): Promise<ConsentRecordResult> {
  const name = confirmedBy.trim();
  if (name === '') {
    throw new Error('Consent has to be recorded against a name — say who is confirming it.');
  }

  const record = await post<WireConsentRecord>(
    `/api/meetings/${encodeURIComponent(meetingId)}/consent-confirmation`,
    { confirmed_by: name },
    options,
  );
  return {
    meetingId: record.meeting_id,
    confirmedBy: record.confirmed_by,
    confirmedAt: record.confirmed_at,
  };
}

/** A capture session the service has allocated for this meeting. */
export interface SessionStarted {
  readonly sessionId: string;
  readonly startedAt: string;
}

interface WireSessionStart {
  readonly session_id: string;
  readonly meeting_id: string;
  readonly started_at: string;
}

/**
 * Opens the capture session the consent gate exists to admit.
 *
 * The service asks its own gate before allocating anything and refuses with
 * 403 and a sentence naming consent, so this is not a second gate — it is the
 * screen finally calling the thing the button was drawn for. The `Start`
 * button had no handler at all, which meant the gate opened onto nothing:
 * confirming consent changed the screen and started no meeting.
 */
export async function startSession(
  meetingId: string,
  options: ConsentActionOptions = {},
): Promise<SessionStarted> {
  const session = await post<WireSessionStart>(
    `/api/meetings/${encodeURIComponent(meetingId)}/session/start`,
    undefined,
    options,
  );
  return { sessionId: session.session_id, startedAt: session.started_at };
}
