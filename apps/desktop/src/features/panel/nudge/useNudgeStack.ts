import { useCallback, useState } from 'react';
import type { Nudge } from './types';

export interface NudgeStackState {
  active: Nudge | null;
  history: Nudge[];
}

export interface UseNudgeStackResult extends NudgeStackState {
  pushNudge: (nudge: Nudge) => void;
  clear: () => void;
}

const EMPTY_STATE: NudgeStackState = { active: null, history: [] };

/**
 * Tracks exactly one prominent nudge at a time (PRD FR-6.3). Pushing a new
 * nudge demotes whichever one was active to the front of `history`, which
 * callers render dimmed and in recency order.
 *
 * `pushNudge` takes a whole, already-complete `Nudge` and applies it with a
 * single `setState` call rather than patching `active` field by field, so
 * the new nudge and the demotion of the old one land in one commit — there
 * is no intermediate state where `active` is partially formed. This is what
 * "streaming disabled in live mode" means at the state layer (PRD FR-6.4):
 * the panel has no API for delivering a nudge in pieces, only whole.
 */
export function useNudgeStack(initial: NudgeStackState = EMPTY_STATE): UseNudgeStackResult {
  const [state, setState] = useState<NudgeStackState>(initial);

  const pushNudge = useCallback((nudge: Nudge) => {
    setState((prev) => ({
      active: nudge,
      history: prev.active ? [prev.active, ...prev.history] : prev.history,
    }));
  }, []);

  const clear = useCallback(() => {
    setState(EMPTY_STATE);
  }, []);

  return { ...state, pushNudge, clear };
}
