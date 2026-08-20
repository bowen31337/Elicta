import '../features/prep/screens.css';

import { ScreenEyebrow } from './Mark';
import type { ResourceStatus } from '../services/useResource';

/**
 * What a full screen shows instead of itself while it has nothing true to say.
 *
 * These screens were connected to the service late, and the specific way they
 * were wrong before is the thing to avoid now: hardcoded empty props rendered
 * as em dashes and empty lists, which is exactly what a *working* screen with
 * no data looks like. An operator could not tell "nothing recorded yet" from
 * "the service is not running", and neither could a screenshot.
 *
 * So the states are separate surfaces, not shadings of the same one:
 *
 * - **loading** — says it is asking, and nothing else. No skeleton pretending
 *   to be content.
 * - **error** — names the failure and offers to try again. It never renders
 *   the screen's own shell underneath, because a heading with an em dash under
 *   an error banner reads as partial success.
 * - **idle** — there is no engagement to be about yet, which is a real state
 *   on a fresh install rather than a failure.
 *
 * `missing` has no entry here on purpose: a 404 is per-screen news ("this
 * meeting was never transcribed") and belongs to the screen, which knows what
 * absence means for it.
 */
export interface ScreenStateProps {
  /** The eyebrow the real screen would use, so the two do not jump. */
  readonly eyebrow: string;
  readonly status: Exclude<ResourceStatus, 'ready' | 'missing'>;
  /** Set when `status` is `error`. */
  readonly error?: string | null;
  /** What the operator would have to do for this screen to have something. */
  readonly idleHint?: string;
  readonly onRetry?: () => void;
}

const TITLE: Record<ScreenStateProps['status'], string> = {
  loading: 'Loading…',
  error: 'Cannot reach the service',
  idle: 'Nothing selected yet',
};

export function ScreenState({ eyebrow, status, error, idleHint, onRetry }: ScreenStateProps) {
  return (
    <main className="screen" aria-labelledby="screen-state-title">
      <header className="screen-head">
        <ScreenEyebrow>{eyebrow}</ScreenEyebrow>
        <h1 className="t-large-title" id="screen-state-title">
          {TITLE[status]}
        </h1>
      </header>

      {status === 'error' ? (
        <section aria-labelledby="screen-state-detail">
          <h2 className="t-section" id="screen-state-detail">
            What happened
          </h2>
          <div className="group">
            <div className="row">
              <div className="row-main">
                <span className="t-body" role="alert">
                  {error ?? 'The service could not be reached.'}
                </span>
                <span className="t-footnote">
                  Nothing is lost. This screen shows nothing rather than showing
                  you an empty one that looks like an answer.
                </span>
              </div>
              {onRetry ? (
                <button type="button" className="btn btn--filled" onClick={onRetry}>
                  Try again
                </button>
              ) : null}
            </div>
          </div>
        </section>
      ) : null}

      {status === 'idle' && idleHint ? (
        <p className="t-body hint">{idleHint}</p>
      ) : null}
    </main>
  );
}
