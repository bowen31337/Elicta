import { useCallback, useState } from 'react';
import type { OperatorUtterance, Thread } from './types';
import { isOperatorAskingThreadQuestion } from './operatorAskedThread';

export interface UseOperatorAskedThreadOptions {
  /**
   * Fire-and-forget notification that the operator's own speech resolved
   * the thread, for whatever eventually syncs `operator_asked` back to the
   * service -- mirroring `useAskedItChip`'s `onAsked`. Never awaited: the
   * local mutation is the marker persisting, not this callback's outcome.
   */
  onOperatorAsked?: (thread: Thread) => void;
}

export interface UseOperatorAskedThreadResult {
  readonly thread: Thread;
  /** Whether the thread has been marked live, i.e. `operatorAskedAt` is set. */
  readonly live: boolean;
  /**
   * Feeds one finalised operator utterance to the thread. Returns whether
   * it just marked the thread live -- `false` both when the utterance
   * doesn't ask the thread's question and when the thread was already live
   * before this call.
   */
  readonly notice: (utterance: OperatorUtterance) => boolean;
}

/**
 * Treats operator speech as implicit input (PRD FR-6.10): each finalised
 * utterance tagged `operator` is checked against the thread's still-open
 * question, and the first one that asks it marks the thread live --
 * `operatorAskedAt` moves from `null` to that utterance's timestamp,
 * synchronously and with no network round trip, the same immediate-local
 * shape `useAskedItChip` uses for the tap-driven path this hook is the
 * implicit counterpart to. A thread already marked live ignores further
 * utterances: there is nothing left to resolve, and the marker, once set,
 * persists rather than moving to a later utterance.
 */
export function useOperatorAskedThread(
  initialThread: Thread,
  options: UseOperatorAskedThreadOptions = {},
): UseOperatorAskedThreadResult {
  const { onOperatorAsked } = options;
  const [thread, setThread] = useState<Thread>(initialThread);

  const notice = useCallback(
    (utterance: OperatorUtterance) => {
      let markedLive = false;
      setThread((current) => {
        if (current.operatorAskedAt !== null) {
          return current;
        }
        if (!isOperatorAskingThreadQuestion(utterance.text, current)) {
          return current;
        }
        markedLive = true;
        const next: Thread = { ...current, operatorAskedAt: utterance.finalizedAt };
        onOperatorAsked?.(next);
        return next;
      });
      return markedLive;
    },
    [onOperatorAsked],
  );

  return { thread, live: thread.operatorAskedAt !== null, notice };
}
