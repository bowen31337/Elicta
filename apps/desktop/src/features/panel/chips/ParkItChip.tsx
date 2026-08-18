import { useParkItChip } from './useParkItChip';
import type { UseParkItChipOptions } from './useParkItChip';
import type { Thread } from './types';
import './ParkItChip.css';

export interface ParkItChipProps extends UseParkItChipOptions {
  thread: Thread;
  label?: string;
  pendingLabel?: string;
  parkedLabel?: string;
  retryLabel?: string;
}

const DEFAULT_LABEL = 'Park it';
const DEFAULT_PENDING_LABEL = 'Parking…';
const DEFAULT_PARKED_LABEL = 'Parked ✓';
const DEFAULT_RETRY_LABEL = 'Try again';

/**
 * The `Park it` chip (PRD FR-6.8): a tap defers the thread to the
 * `open_questions` table on the service tier for later follow-up, without
 * dismissing the thread -- unlike `Asked it`, which disables itself
 * permanently once tapped because it marks a resolution, this chip re-
 * enables after a successful park and never hides or removes the thread
 * it's attached to, since parking is a "come back to this later" filing
 * action rather than a resolution. Renders standalone so a caller can
 * place it beside `Asked it`, `Go deeper`, and `What am I missing?`
 * without this component knowing about its siblings.
 */
export function ParkItChip({
  thread,
  label = DEFAULT_LABEL,
  pendingLabel = DEFAULT_PENDING_LABEL,
  parkedLabel = DEFAULT_PARKED_LABEL,
  retryLabel = DEFAULT_RETRY_LABEL,
  ...options
}: ParkItChipProps) {
  const { status, parked, tap } = useParkItChip(thread, options);
  const pending = status === 'pending';
  const buttonLabel = pending ? pendingLabel : status === 'error' ? retryLabel : label;

  return (
    <div className="park-it-chip">
      <button
        type="button"
        className="park-it-chip__button"
        onClick={() => void tap()}
        disabled={pending}
        aria-busy={pending}
      >
        {buttonLabel}
      </button>
      {parked !== null ? (
        <span className="park-it-chip__result" role="status">
          {parkedLabel}
        </span>
      ) : null}
    </div>
  );
}
