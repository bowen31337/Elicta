import { useGoDeeperChip } from './useGoDeeperChip';
import type { UseGoDeeperChipOptions } from './useGoDeeperChip';
import type { Thread } from './types';
import './GoDeeperChip.css';

export interface GoDeeperChipProps extends UseGoDeeperChipOptions {
  thread: Thread;
  label?: string;
  pendingLabel?: string;
  retryLabel?: string;
}

const DEFAULT_LABEL = 'Go deeper';
const DEFAULT_PENDING_LABEL = 'Going deeper…';
const DEFAULT_RETRY_LABEL = 'Try again';

/**
 * The `Go deeper` chip (PRD FR-6.8): a tap requests a follow-on candidate
 * question on the same thread from the service tier, and renders it
 * beneath the chip once it lands -- the one tap-only chip among its
 * siblings (`Asked it`, `Park it`, `What am I missing?`) that involves a
 * network round trip, since the candidate itself has to be generated
 * rather than looked up in state already held locally. Renders standalone
 * so a caller can place it beside the others without this component
 * knowing about them.
 */
export function GoDeeperChip({
  thread,
  label = DEFAULT_LABEL,
  pendingLabel = DEFAULT_PENDING_LABEL,
  retryLabel = DEFAULT_RETRY_LABEL,
  ...options
}: GoDeeperChipProps) {
  const { status, candidate, tap } = useGoDeeperChip(thread, options);
  const pending = status === 'pending';
  const buttonLabel = pending ? pendingLabel : status === 'error' ? retryLabel : label;

  return (
    <div className="go-deeper-chip">
      <button
        type="button"
        className="go-deeper-chip__button"
        onClick={() => void tap()}
        disabled={pending}
        aria-busy={pending}
      >
        {buttonLabel}
      </button>
      {candidate !== null ? (
        <span className="go-deeper-chip__result" role="status">
          {candidate.question}
        </span>
      ) : null}
    </div>
  );
}
