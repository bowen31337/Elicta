import { useCallback, useState } from 'react';
import type { EscapeHatchQuery } from './types';

export interface UseEscapeHatchInputOptions {
  onSubmit: (query: EscapeHatchQuery) => void;
  now?: () => number;
}

export interface UseEscapeHatchInputResult {
  readonly value: string;
  readonly setValue: (value: string) => void;
  readonly submit: () => void;
}

/**
 * Backs the escape-hatch text input (PRD FR-6.9). The chips (`Asked it`,
 * `Park it`, `Go deeper`, `What am I missing?`) are the primary input and
 * cover every intent that can be expressed with a tap; this hook exists for
 * the residual case a chip can't cover, which is why `submit` clears the
 * field on every non-blank submission rather than leaving typed text sitting
 * around competing for attention once it's been sent.
 */
export function useEscapeHatchInput(
  options: UseEscapeHatchInputOptions,
): UseEscapeHatchInputResult {
  const { onSubmit, now = () => Date.now() } = options;
  const [value, setValue] = useState('');

  const submit = useCallback(() => {
    const text = value.trim();
    if (!text) {
      return;
    }
    onSubmit({ text, submittedAt: now() });
    setValue('');
  }, [value, onSubmit, now]);

  return { value, setValue, submit };
}
