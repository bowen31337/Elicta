import { useEffect, useState } from 'react';

import { serviceFault } from '../services/serviceFault';
import './ServiceFaultBanner.css';

/**
 * Why nothing on any screen is working, when nothing is.
 *
 * A service the shell could not start is the one failure that makes every
 * screen look empty at once, and each screen reports only what it
 * individually found — which is nothing. An operator reads that as a product
 * with no data in it. The commonest cause is another copy of the app holding
 * port 8000: a `.dmg` installed weeks ago, still running, serving an API this
 * panel does not match.
 *
 * Said once, above everything, in the shell's own words — it is the half that
 * knows which two copies are involved and where each of them lives.
 */
export function ServiceFaultBanner({ ask = serviceFault }: { ask?: typeof serviceFault }) {
  const [reason, setReason] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void ask().then((found) => {
      if (!cancelled) setReason(found);
    });
    return () => {
      cancelled = true;
    };
  }, [ask]);

  if (reason === null) return null;
  return (
    <p className="service-fault t-footnote" role="alert">
      {reason}
    </p>
  );
}
