import { useCallback, useState } from 'react';

/**
 * The conversational half of debrief mode (FR-7.3).
 *
 * The service has carried this since early on — open a conversation against a
 * meeting, send a question in your own words, get an answer grounded in what
 * was actually said — and nothing ever called it. This is that caller.
 *
 * Debrief mode is the opposite trade-off from the live panel: nothing here is
 * time-critical, so the request is allowed to take as long as it takes and the
 * screen says it is thinking rather than pretending to be instant.
 */
export type DebriefRole = 'user' | 'assistant';

export interface DebriefTurn {
  readonly role: DebriefRole;
  readonly text: string;
}

/** The wire shape: content is a list of blocks, only some of which are text. */
interface WireMessage {
  role: DebriefRole;
  content: Array<{ type?: string; text?: string }>;
  recorded_at: string;
}

interface WireSession {
  session_id: string;
  history: WireMessage[];
}

/** Flattens a message's content blocks into the one string a reader sees. */
export function readableText(content: WireMessage['content']): string {
  return content
    .filter((block) => typeof block.text === 'string')
    .map((block) => block.text)
    .join('')
    .trim();
}

function toTurns(session: WireSession): DebriefTurn[] {
  return session.history
    .map((message) => ({ role: message.role, text: readableText(message.content) }))
    .filter((turn) => turn.text.length > 0);
}

export interface UseDebriefChat {
  readonly turns: readonly DebriefTurn[];
  readonly busy: boolean;
  /** Set when the last action failed; the screen shows it and stays usable. */
  readonly error: string | null;
  readonly started: boolean;
  readonly start: () => Promise<void>;
  readonly ask: (question: string) => Promise<void>;
}

/**
 * What the service said went wrong, in preference to what its status number
 * was.
 *
 * The service goes to some trouble here: an unconfigured engine answers 503
 * naming the setting that would fix it, and a rate-limited provider answers
 * 429 saying to wait rather than to go looking for a broken deployment.
 * "The debrief service answered 429." throws all of that away and leaves the
 * operator with the one thing they cannot act on.
 */
async function failureMessage(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === 'string' && body.detail !== '') return body.detail;
  } catch {
    // Not JSON, or no body at all. The status is then genuinely all we know.
  }
  return `The debrief service answered ${response.status}.`;
}

async function post(path: string, body?: unknown): Promise<WireSession> {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(await failureMessage(response));
  }
  return (await response.json()) as WireSession;
}

export function useDebriefChat(meetingId: string): UseDebriefChat {
  const [turns, setTurns] = useState<readonly DebriefTurn[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [started, setStarted] = useState(false);

  const run = useCallback(async (work: () => Promise<WireSession>, optimistic?: DebriefTurn) => {
    setBusy(true);
    setError(null);
    // The operator's own question appears immediately. Waiting for the round
    // trip to echo it back makes the interface feel broken on a slow answer,
    // and this half of the product is explicitly allowed to be slow.
    if (optimistic) setTurns((current) => [...current, optimistic]);
    try {
      setTurns(toTurns(await work()));
      setStarted(true);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'The debrief service is unreachable.');
    } finally {
      setBusy(false);
    }
  }, []);

  const encoded = encodeURIComponent(meetingId);

  return {
    turns,
    busy,
    error,
    started,
    start: useCallback(
      () => run(() => post(`/api/meetings/${encoded}/debrief/start`)),
      [encoded, run],
    ),
    ask: useCallback(
      (question: string) =>
        run(
          () => post(`/api/meetings/${encoded}/debrief/message`, { message: question }),
          { role: 'user', text: question },
        ),
      [encoded, run],
    ),
  };
}
