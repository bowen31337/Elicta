import type { KeyboardEvent } from 'react';
import { useEscapeHatchInput } from './useEscapeHatchInput';
import type { EscapeHatchQuery } from './types';
import './chips.tokens.css';
import './EscapeHatchInput.css';

export interface EscapeHatchInputProps {
  onSubmit: (query: EscapeHatchQuery) => void;
  placeholder?: string;
  now?: () => number;
}

const DEFAULT_PLACEHOLDER = 'Type a question instead…';

/**
 * The typed escape hatch beneath the tap-only chips (PRD FR-6.9). Chips
 * cover every intent that fits a tap (FR-6.6); typing is an order of
 * magnitude more attention and is not compatible with listening to the
 * client (PRD §8.6 rationale for FR-6.6), so this input stays visually
 * present — never hidden behind a toggle — but de-emphasised: small, muted,
 * borderless until focused. It exists for the residual case, not as a
 * second primary input.
 *
 * De-emphasis is visual only. The field keeps a real accessible name and a
 * normal tab stop so it degrades to an ordinary text input for anyone not
 * relying on the visual hierarchy (e.g. screen reader or keyboard users).
 */
export function EscapeHatchInput({
  onSubmit,
  placeholder = DEFAULT_PLACEHOLDER,
  now,
}: EscapeHatchInputProps) {
  const { value, setValue, submit } = useEscapeHatchInput({ onSubmit, now });

  const handleKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Enter') {
      submit();
    }
  };

  return (
    <div className="escape-hatch">
      <input
        type="text"
        className="escape-hatch__input"
        aria-label="Ask a question"
        placeholder={placeholder}
        value={value}
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={handleKeyDown}
      />
    </div>
  );
}
