import { useCallback, useState } from 'react';
import {
  DEFAULT_MIN_CONFIDENCE,
  LanguagePanelState,
  createLanguagePanelState,
  observeLanguage,
} from './languagePanel';
import type { LanguageObservation } from './types';

export interface UseLanguagePanelResult extends LanguagePanelState {
  observe: (observation: LanguageObservation) => void;
}

/**
 * Live panel-chrome state for detected languages and the active support
 * tier (PRD FR-2.20). Callers feed it one observation per finalised
 * utterance; rendering never needs to know about the confidence gate or the
 * BCP-47 subtag collapsing applied underneath.
 */
export function useLanguagePanel(minConfidence: number = DEFAULT_MIN_CONFIDENCE): UseLanguagePanelResult {
  const [state, setState] = useState<LanguagePanelState>(createLanguagePanelState);

  const observe = useCallback(
    (observation: LanguageObservation) => {
      setState((prev) => observeLanguage(prev, observation, minConfidence));
    },
    [minConfidence],
  );

  return { ...state, observe };
}
