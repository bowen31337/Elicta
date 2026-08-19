import { useAskedItChip } from './useAskedItChip';
import type { CoverageSlot } from '../coverage/types';
import './chips.tokens.css';
import './AskedItChip.css';

export interface AskedItChipProps {
  slot: CoverageSlot;
  /** Fire-and-forget; see `useAskedItChip`'s `onAsked`. */
  onAsked?: (slot: CoverageSlot) => void;
  label?: string;
  confirmedLabel?: string;
}

const DEFAULT_LABEL = 'Asked it';
const DEFAULT_CONFIRMED_LABEL = 'Asked ✓';

/**
 * The `Asked it` chip (PRD FR-6.6/6.7): a tap marks the coverage slot
 * satisfied with no network round trip, and the chip itself flips to a
 * confirmed, disabled state in that same tap -- the operator sees
 * confirmation immediately rather than waiting on whatever eventually
 * persists `satisfied_at` to the service. This is one of the tap-only
 * chips that make up the primary input (FR-6.6); it renders standalone so
 * a caller can place it beside `Park it`, `Go deeper`, and `What am I
 * missing?` without this component knowing about its siblings.
 */
export function AskedItChip({
  slot,
  onAsked,
  label = DEFAULT_LABEL,
  confirmedLabel = DEFAULT_CONFIRMED_LABEL,
}: AskedItChipProps) {
  const { asked, tap } = useAskedItChip(slot, { onAsked });

  return (
    <button
      type="button"
      className={`asked-it-chip${asked ? ' asked-it-chip--confirmed' : ''}`}
      onClick={tap}
      disabled={asked}
      aria-pressed={asked}
    >
      {asked ? confirmedLabel : label}
    </button>
  );
}
