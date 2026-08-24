import type { DocumentStatus, VocabularyTermType } from './types';
import { apiUrl } from '../../services/apiClient';

/**
 * The writes the preparation screen makes (PRD FR-3.1, FR-3.2, FR-3.6, FR-4.8).
 *
 * Every one of these endpoints existed before any of these functions did. The
 * screen rendered `Compile` and `Prune` as buttons with no handler, and had no
 * control at all for attaching a document, adding a term or creating the
 * engagement — so journey 1 described a screen you could type into while the
 * only way to do any of it was `curl`. A live run recorded the consequence:
 * heading `—`, no documents, no vocabulary, an empty bank.
 *
 * Written as plain functions over an injectable `fetch`, the way `stopSession`
 * is, so each one is testable without a component and without a network.
 */

/** The subset of `fetch` these calls rely on, so tests supply a stub instead of a network. */
export type PrepFetch = (input: string, init: RequestInit) => Promise<Response>;

export interface PrepActionOptions {
  /** Overridable for tests; defaults to the global `fetch`. */
  readonly fetch?: PrepFetch;
}

/** A FastAPI `detail`: a string from `HTTPException`, a list from model validation. */
type ServiceDetail = { detail?: string | readonly { msg?: string }[] };

/**
 * What went wrong, in the service's own words where it offered them.
 *
 * The refusals here are ones the operator can act on — a link that is not
 * SharePoint, a term type that is not one of the three — so replacing them
 * with "the service answered 422" would throw away the only useful part.
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

async function send<T>(
  path: string,
  init: RequestInit,
  options: PrepActionOptions,
): Promise<T | null> {
  const { fetch: fetchImpl = fetch } = options;
  let response: Response;
  try {
    response = await fetchImpl(path, {
      ...init,
      headers: { 'Content-Type': 'application/json', Accept: 'application/json', ...init.headers },
    });
  } catch {
    // Distinguished from a refusal on purpose: an unreachable service and a
    // rejected value need different things from the operator.
    throw new Error('The service could not be reached.');
  }
  if (!response.ok) throw new Error(await failureMessage(response));
  try {
    return (await response.json()) as T;
  } catch {
    return null;
  }
}

const post = <T>(path: string, body: unknown, options: PrepActionOptions) =>
  send<T>(path, { method: 'POST', body: JSON.stringify(body) }, options);

const patch = <T>(path: string, body: unknown, options: PrepActionOptions) =>
  send<T>(path, { method: 'PATCH', body: JSON.stringify(body) }, options);

const id = (value: string) => encodeURIComponent(value);

export interface NewMeeting {
  readonly engagementId: string;
  readonly captureMode: string;
}

/**
 * Creates a meeting in an engagement (PRD FR-1.1).
 *
 * Nothing in the product made one: every screen after preparation is about a
 * meeting, and the only way to have one was to call the API by hand.
 */
export async function createMeeting(
  meeting: NewMeeting,
  options: PrepActionOptions = {},
): Promise<string> {
  const created = await post<{ meeting_id: string }>(
    apiUrl('/api/meetings'),
    { engagement_id: meeting.engagementId, capture_mode: meeting.captureMode },
    options,
  );
  return created?.meeting_id ?? '';
}

/**
 * Renames a meeting, which is what its session purpose is used for here (PRD FR-3.8).
 *
 * The list on the Preparation screen falls back to the bare `meeting-3` when a
 * meeting has no purpose, and three of those tell an operator nothing about
 * which is which. `PATCH /api/meetings/{id}` has stored the purpose since
 * FR-3.8 was built; no screen ever called it.
 *
 * The blank check is here rather than left to the service on purpose: the
 * service answers 422, and "The service answered 422" tells the operator less
 * than the screen already knows.
 */
export async function renameMeeting(
  meetingId: string,
  sessionPurpose: string,
  options: PrepActionOptions = {},
): Promise<string> {
  const purpose = sessionPurpose.trim();
  if (purpose === '') throw new Error('A meeting needs a purpose to be renamed to.');
  const updated = await patch<{ session_purpose: string | null }>(
    apiUrl(`/api/meetings/${id(meetingId)}`),
    { session_purpose: purpose },
    options,
  );
  return updated?.session_purpose ?? purpose;
}

/**
 * Removes a meeting from its engagement's list — soft, like the other two.
 *
 * Softer than the other two matter: a meeting is what a consent record, a
 * transcript and an audio-destruction event all point at. The service marks
 * the row and stops listing it; nothing is erased, and the record that the
 * meeting happened stays where it is.
 */
export async function deleteMeeting(
  meetingId: string,
  options: PrepActionOptions = {},
): Promise<void> {
  await send(apiUrl(`/api/meetings/${id(meetingId)}`), { method: 'DELETE' }, options);
}

export interface DocumentLink {
  readonly url: string;
  readonly status: DocumentStatus;
}

/** Attaches a SharePoint or Teams document, tagged as one of the three kinds. */
export async function linkDocument(
  engagementId: string,
  link: DocumentLink,
  options: PrepActionOptions = {},
): Promise<string> {
  const attached = await post<{ id: string }>(
    apiUrl(`/api/engagements/${id(engagementId)}/documents/link`),
    { url: link.url, status: link.status },
    options,
  );
  return attached?.id ?? '';
}

/**
 * Uploads a document's own bytes (FR-3.3).
 *
 * The second intake path, and the one that needs no connector configured: a
 * file dropped here is read on arrival by the same extractor a linked document
 * goes through. Sent as `multipart/form-data` because the service takes an
 * `UploadFile`, and deliberately without a `Content-Type` header — the browser
 * sets it, and it has to carry the boundary, which a hand-written header
 * would not.
 */
export async function uploadDocument(
  engagementId: string,
  file: File,
  status: DocumentStatus,
  options: PrepActionOptions = {},
): Promise<string> {
  const form = new FormData();
  form.append('file', file);
  form.append('status', status);

  const { fetch: fetchImpl = fetch } = options;
  let response: Response;
  try {
    response = await fetchImpl(apiUrl(`/api/engagements/${id(engagementId)}/documents`), {
      method: 'POST',
      body: form,
    });
  } catch {
    throw new Error('The service could not be reached.');
  }
  if (!response.ok) throw new Error(await failureMessage(response));
  const uploaded = (await response.json()) as { document_id?: string };
  return uploaded?.document_id ?? '';
}

/** Changes a document's tag, which is what changes how Elicta treats it. */
export async function retagDocument(
  documentId: string,
  status: DocumentStatus,
  options: PrepActionOptions = {},
): Promise<void> {
  await patch(apiUrl(`/api/documents/${id(documentId)}/status`), { status }, options);
}

export interface NewVocabularyTerm {
  readonly term: string;
  readonly termType: VocabularyTermType;
}

/** Adds one keyterm — the words a transcriber would not otherwise know. */
export async function addVocabularyTerm(
  engagementId: string,
  entry: NewVocabularyTerm,
  options: PrepActionOptions = {},
): Promise<void> {
  await post(
    apiUrl(`/api/engagements/${id(engagementId)}/vocabulary`),
    { term: entry.term, term_type: entry.termType },
    options,
  );
}

/** Starts the pre-reasoning pass that drafts the bank. Minutes, not seconds. */
export async function compileBank(
  engagementId: string,
  options: PrepActionOptions = {},
): Promise<void> {
  await post(apiUrl(`/api/engagements/${id(engagementId)}/bank/compile`), undefined, options);
}

/**
 * Prunes by marking, not by deleting. The service keeps a pruned candidate and
 * the screen filters it out (`toSection`), so a reviewer's judgement survives a
 * recompile instead of the question coming back.
 */
export async function pruneCandidate(
  candidateId: string,
  options: PrepActionOptions = {},
): Promise<void> {
  await patch(apiUrl(`/api/bank/candidates/${id(candidateId)}`), { pruned: true }, options);
}

/**
 * Removals, both of them soft.
 *
 * The row is marked on the service and stops being listed; nothing is erased.
 * That keeps a mistake recoverable and leaves the harder question — whether a
 * real erasure should also destroy recordings, consent records and artifacts —
 * to a decision rather than to a button.
 */
export async function deleteDocument(
  documentId: string,
  options: PrepActionOptions = {},
): Promise<void> {
  await send(apiUrl(`/api/documents/${id(documentId)}`), { method: 'DELETE' }, options);
}

export async function deleteVocabularyTerm(
  engagementId: string,
  termId: string,
  options: PrepActionOptions = {},
): Promise<void> {
  await send(
    apiUrl(`/api/engagements/${id(engagementId)}/vocabulary/${id(termId)}`),
    { method: 'DELETE' },
    options,
  );
}

/** Reorders within a section: priority 1 is asked first. */
export async function moveCandidate(
  candidateId: string,
  priority: number,
  options: PrepActionOptions = {},
): Promise<void> {
  if (!Number.isInteger(priority) || priority < 1) {
    throw new Error('priority must be a whole number of at least 1');
  }
  await patch(apiUrl(`/api/bank/candidates/${id(candidateId)}`), { priority }, options);
}
