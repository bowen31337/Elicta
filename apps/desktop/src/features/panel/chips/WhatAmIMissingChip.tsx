import { useWhatAmIMissingChip } from './useWhatAmIMissingChip';
import type { CoverageSlot, CoverageSummary } from '../coverage/types';
import './chips.tokens.css';
import './WhatAmIMissingChip.css';

export interface WhatAmIMissingChipProps {
  summary: CoverageSummary;
  /** Fire-and-forget; see `useWhatAmIMissingChip`'s `onSurfaced`. */
  onSurfaced?: (slot: CoverageSlot) => void;
  label?: string;
  clearLabel?: string;
}

const DEFAULT_LABEL = 'What am I missing?';
const DEFAULT_CLEAR_LABEL = 'Nothing missing';

/**
 * The `What am I missing?` chip (PRD FR-6.6): a tap surfaces the
 * highest-urgency unfilled coverage section with no network round trip,
 * rendering it right beneath the chip so the operator sees it without
 * hunting through the persistent coverage indicator's full list. One of
 * the tap-only chips that make up the primary input (FR-6.6); it renders
 * standalone so a caller can place it beside `Asked it`, `Park it`, and
 * `Go deeper` without this component knowing about its siblings.
 */
export function WhatAmIMissingChip({
  summary,
  onSurfaced,
  label = DEFAULT_LABEL,
  clearLabel = DEFAULT_CLEAR_LABEL,
}: WhatAmIMissingChipProps) {
  const { result, tap } = useWhatAmIMissingChip(summary, { onSurfaced });

  return (
    <div className="what-am-i-missing-chip">
      <button
        type="button"
        className="what-am-i-missing-chip__button"
        title="Show the section with the most still to find out, of those not yet covered."
        onClick={tap}
      >
        {label}
      </button>
      {result !== null ? (
        <span className="what-am-i-missing-chip__result" role="status">
          {result.type === 'slot' ? result.slot.label : clearLabel}
        </span>
      ) : null}
    </div>
  );
}
