import { useCallback, useEffect, useState } from 'react';
import { loadOperatorLanguage, saveOperatorLanguage } from './operatorLanguageStore';

/** Matches the English fallback used by `getNudgeChromeCopy` for an unset operator language. */
export const DEFAULT_OPERATOR_LANGUAGE = 'en';

export interface UseOperatorLanguageResult {
  readonly operatorLanguage: string;
  readonly setOperatorLanguage: (language: string) => void;
}

/**
 * The operator's interface language, configurable independently of whichever
 * language the meeting is in (PRD FR-2.26). Reads the persisted choice for
 * `userId` on mount and whenever `userId` changes — so switching the active
 * user swaps in that user's own setting rather than carrying over the
 * previous user's — and falls back to `defaultLanguage` when nothing has
 * been persisted yet. `setOperatorLanguage` updates the live value and
 * persists it in the same call, so the choice survives a reload.
 */
export function useOperatorLanguage(
  userId: string,
  defaultLanguage: string = DEFAULT_OPERATOR_LANGUAGE,
): UseOperatorLanguageResult {
  const [operatorLanguage, setOperatorLanguageState] = useState<string>(
    () => loadOperatorLanguage(userId) ?? defaultLanguage,
  );

  useEffect(() => {
    setOperatorLanguageState(loadOperatorLanguage(userId) ?? defaultLanguage);
  }, [userId, defaultLanguage]);

  const setOperatorLanguage = useCallback(
    (language: string) => {
      setOperatorLanguageState(language);
      saveOperatorLanguage(userId, language);
    },
    [userId],
  );

  return { operatorLanguage, setOperatorLanguage };
}
