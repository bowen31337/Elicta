/**
 * Persistence for the operator's interface language (PRD FR-2.26). The
 * setting is configured independently of the meeting language and must
 * survive a reload, scoped per user so that two operators sharing a device
 * never inherit each other's choice.
 */
const STORAGE_KEY_PREFIX = 'elicta.nudge.operatorLanguage';

function storageKey(userId: string): string {
  return `${STORAGE_KEY_PREFIX}.${userId}`;
}

/** Returns the persisted operator language for `userId`, or `null` if none has been set. */
export function loadOperatorLanguage(userId: string): string | null {
  return window.localStorage.getItem(storageKey(userId));
}

/** Persists `language` as `userId`'s operator language, scoped to that user only. */
export function saveOperatorLanguage(userId: string, language: string): void {
  window.localStorage.setItem(storageKey(userId), language);
}
