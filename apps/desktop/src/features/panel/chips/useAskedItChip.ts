import { useCallback, useState } from 'react';
import type { CoverageSlot } from '../coverage/types';

export interface UseAskedItChipOptions {
  /**
   * Fire-and-forget notification that the slot was marked asked, for
   * whatever eventually syncs `satisfied_at` back to the service. Never
   * awaited here -- the local mutation below is the confirmation the
   * operator sees, not this callback's outcome (PRD FR-6.6).
   */
  onAsked?: (slot: CoverageSlot) => void;
}

export interface UseAskedItChipResult {
  readonly slot: CoverageSlot;
  readonly asked: boolean;
  readonly tap: () => void;
}

/**
 * Backs the `Asked it` chip (PRD FR-6.6/6.7). Tapping marks the coverage
 * slot filled in local state synchronously, in the same render pass,
 * rather than waiting on a round trip to the service that owns the
 * authoritative `satisfied_at` timestamp -- that persistence, tracked by
 * `core/crates/coverage`, happens independently of what this hook shows.
 * A slot that is already filled when it arrives (the stream caught up, or
 * a previous tap already landed) renders as already-asked with no further
 * tap needed, and a second tap is a no-op: there is nothing to undo, and
 * re-suggestion is already suppressed once a slot is filled.
 */
export function useAskedItChip(
  initialSlot: CoverageSlot,
  options: UseAskedItChipOptions = {},
): UseAskedItChipResult {
  const { onAsked } = options;
  const [slot, setSlot] = useState<CoverageSlot>(initialSlot);

  const tap = useCallback(() => {
    setSlot((current) => {
      if (current.filled) {
        return current;
      }
      const next: CoverageSlot = { ...current, filled: true };
      onAsked?.(next);
      return next;
    });
  }, [onAsked]);

  return { slot, asked: slot.filled, tap };
}
