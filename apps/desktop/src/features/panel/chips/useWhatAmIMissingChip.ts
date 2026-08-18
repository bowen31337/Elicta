import { useCallback, useState } from 'react';
import type { CoverageSlot, CoverageSummary } from '../coverage/types';
import { pickHighestUrgencySlot } from './pickHighestUrgencySlot';

/**
 * What tapping `What am I missing?` found (PRD FR-6.6), distinguishing
 * "surfaced the highest-urgency unfilled section" from "checked, and there
 * is nothing unfilled left to surface" -- the chip has something to render
 * either way, so the hook doesn't collapse the second case into `null`.
 */
export type WhatAmIMissingResult =
  | { readonly type: 'slot'; readonly slot: CoverageSlot }
  | { readonly type: 'clear' };

export interface UseWhatAmIMissingChipOptions {
  /**
   * Fire-and-forget notification of the surfaced slot, mirroring
   * `useAskedItChip`'s `onAsked` -- never awaited, since the result this
   * hook renders is already final by the time this callback runs.
   */
  onSurfaced?: (slot: CoverageSlot) => void;
}

export interface UseWhatAmIMissingChipResult {
  readonly result: WhatAmIMissingResult | null;
  readonly tap: () => void;
}

/**
 * Backs the `What am I missing?` chip (PRD FR-6.6). A tap looks up the
 * highest-urgency unfilled section in `summary` (`pickHighestUrgencySlot`)
 * synchronously, with no network round trip -- the same immediate-local
 * shape as `useAskedItChip`, since this chip reads coverage state rather
 * than mutating it.
 */
export function useWhatAmIMissingChip(
  summary: CoverageSummary,
  options: UseWhatAmIMissingChipOptions = {},
): UseWhatAmIMissingChipResult {
  const { onSurfaced } = options;
  const [result, setResult] = useState<WhatAmIMissingResult | null>(null);

  const tap = useCallback(() => {
    const slot = pickHighestUrgencySlot(summary);
    if (slot === null) {
      setResult({ type: 'clear' });
      return;
    }
    setResult({ type: 'slot', slot });
    onSurfaced?.(slot);
  }, [summary, onSurfaced]);

  return { result, tap };
}
