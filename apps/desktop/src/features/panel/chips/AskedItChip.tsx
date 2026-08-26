import { useAskedItChip } from './useAskedItChip';
import './chips.tokens.css';
import './AskedItChip.css';

export interface AskedItChipProps {
  /**
   * The template section this nudge belongs to, or `null` when it belongs to
   * none -- a template fallback fires on a phrase, not on a section. Used
   * only to say what the tap will count towards; the chip is offered either
   * way, because it is about the nudge.
   */
  section?: string | null;
  /** Fire-and-forget; see `useAskedItChip`'s `onAsked`. */
  onAsked?: () => void;
  label?: string;
  confirmedLabel?: string;
}

const DEFAULT_LABEL = 'Asked it';
const DEFAULT_CONFIRMED_LABEL = 'Asked ✓';

/**
 * The `Asked it` chip (PRD FR-6.6/6.7): a tap puts the live nudge down and
 * records that the operator asked it, with no network round trip in the way
 * -- the chip flips to a confirmed, disabled state in the same tap.
 *
 * It renders standalone so a caller can place it beside `Park it`, `Go
 * deeper`, and `What am I missing?` without this component knowing about its
 * siblings.
 */
export function AskedItChip({
  section = null,
  onAsked,
  label = DEFAULT_LABEL,
  confirmedLabel = DEFAULT_CONFIRMED_LABEL,
}: AskedItChipProps) {
  const { asked, tap } = useAskedItChip({ onAsked });

  return (
    <button
      type="button"
      className={`asked-it-chip${asked ? ' asked-it-chip--confirmed' : ''}`}
      /* Says what the tap counts towards, and says nothing when it counts
         towards nothing. Promising a section it will not move is how the
         meter came to be trusted for a claim it could not support. */
      title={
        section
          ? `Put this question down and count it against "${section}".`
          : 'Put this question down. It belongs to no section, so the meter does not move.'
      }
      onClick={tap}
      disabled={asked}
      aria-pressed={asked}
    >
      {asked ? confirmedLabel : label}
    </button>
  );
}
