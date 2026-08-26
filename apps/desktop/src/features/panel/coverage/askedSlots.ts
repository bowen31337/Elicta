/**
 * Which sections the operator has marked asked, per meeting.
 *
 * Outside the component on purpose. The router mounts a different screen per
 * destination, so leaving the panel unmounts it and every piece of its own
 * state goes with it — the operator came back to 0 of 8 and no record that
 * they had been anywhere. The nudges survive that because the stream replays
 * them; these had nothing replaying them, because they are the operator's
 * own and nowhere else held them.
 *
 * Keyed by meeting because that is what they are about: a tick belongs to the
 * meeting it was made in, and coming back to a different one must not inherit
 * it.
 *
 * The same module-store-plus-`localStorage` shape `services/selection` uses,
 * and for the same two reasons: the control that changes it and the screen
 * that reads it are different components, and a choice that does not outlive
 * a reload is a choice the operator has to make twice.
 */

const KEY = 'elicta.panel.askedSlots';

type Marks = Record<string, string[]>;

const listeners = new Set<() => void>();

function read(): Marks {
  try {
    const raw = window.localStorage.getItem(KEY);
    return raw === null ? {} : (JSON.parse(raw) as Marks);
  } catch {
    // A corrupt or unavailable store is an empty one. Throwing here would
    // take the panel down over a record of what has been asked.
    return {};
  }
}

function write(marks: Marks): void {
  try {
    window.localStorage.setItem(KEY, JSON.stringify(marks));
  } catch {
    /* see `read` */
  }
  // Copied first: a listener that re-reads and re-subscribes must not mutate
  // the set being iterated.
  for (const listener of [...listeners]) listener();
}

export function subscribeAskedSlots(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** One shared empty, because a fresh `[]` is a new value every time and
 *  `useSyncExternalStore` re-renders until the stack gives out. */
const NONE: readonly string[] = [];

/** The ids marked asked in this meeting. Stable between writes, so
 *  `useSyncExternalStore` does not see a new value on every render. */
let cache: { key: string | null; value: readonly string[] } = { key: null, value: NONE };

/**
 * The key a panel with no meeting files under.
 *
 * Only a fixed scene is ever in that state — the shipped panel resolves its
 * meeting from the same selection every other screen reads. Giving those
 * scenes a real meeting id would have them open a stream, which the
 * screenshot harness has no `EventSource` for, so they keep no meeting and
 * their taps land here.
 */
const NO_MEETING = '(no meeting)';

export function askedSlotsOf(meetingId: string | null): readonly string[] {
  const stored = read()[meetingId ?? NO_MEETING] ?? NONE;
  const key = meetingId ?? NO_MEETING;
  if (cache.key === key && sameMembers(cache.value, stored)) return cache.value;
  cache = { key, value: stored };
  return cache.value;
}

function sameMembers(a: readonly string[], b: readonly string[]): boolean {
  return a.length === b.length && a.every((value, index) => value === b[index]);
}

export function markSlotAsked(meetingId: string | null, slotId: string): void {
  const key = meetingId ?? NO_MEETING;
  const marks = read();
  const held = marks[key] ?? [];
  if (held.includes(slotId)) return;
  write({ ...marks, [key]: [...held, slotId] });
}
