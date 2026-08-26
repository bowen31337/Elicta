import { useCallback, useState } from 'react';

export interface UseAskedItChipOptions {
  /**
   * Fire-and-forget notification that the operator asked the live nudge.
   * Never awaited here -- the confirmation the operator sees is the card
   * receding in the same render pass, not this callback's outcome (FR-6.6).
   */
  onAsked?: () => void;
}

export interface UseAskedItChipResult {
  readonly asked: boolean;
  readonly tap: () => void;
}

/**
 * Backs the `Asked it` chip (PRD FR-6.6/6.7).
 *
 * It used to hold a `CoverageSlot` and flip it to `filled`, which is what
 * made the meter a record of taps rather than a measurement: the slot it was
 * handed was whichever one happened to be first unfilled, with no relation to
 * the nudge being asked. What the tap means for coverage is the service's to
 * decide, from the disposition it is told about; this hook's whole job is to
 * make the tap idempotent within one nudge, so a double-press does not record
 * twice.
 */
export function useAskedItChip(options: UseAskedItChipOptions = {}): UseAskedItChipResult {
  const { onAsked } = options;
  const [asked, setAsked] = useState(false);

  const tap = useCallback(() => {
    setAsked((already) => {
      if (already) return already;
      onAsked?.();
      return true;
    });
  }, [onAsked]);

  return { asked, tap };
}
