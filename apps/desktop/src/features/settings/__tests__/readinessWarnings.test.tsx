import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { ReadinessWarnings } from '../ReadinessWarnings';

/**
 * A blank field is a fact; a warning is what an operator can act on.
 *
 * `deepgram_api_key: configured=false` sat on this screen the whole time a
 * meeting recorded cleanly and the live panel showed no nudge. Every fact
 * needed was here and none of them said what was not happening because of it.
 */
describe('what is not configured, and what it costs', () => {
  const LIVE = {
    capability: 'live_nudges',
    ready: false,
    missing: ['deepgram_api_key'],
    consequence: 'no nudge ever reaches the panel',
    optional: false,
  };

  it('says what stops, not just which key is blank', () => {
    render(<ReadinessWarnings readiness={[LIVE]} />);

    expect(screen.getByText(/no nudge ever reaches the panel/i)).toBeInTheDocument();
  });

  it('names the key to set', () => {
    render(<ReadinessWarnings readiness={[LIVE]} />);

    expect(screen.getByText(/deepgram_api_key/i)).toBeInTheDocument();
  });

  it('separates what is broken from what is merely unavailable', () => {
    // An optional capability missing is not a fault: sending an operator to
    // configure Entra ID for a feature they are not using is how a warning
    // becomes noise, and noise is how the one that mattered got missed.
    render(
      <ReadinessWarnings
        readiness={[
          LIVE,
          {
            capability: 'document_links',
            ready: false,
            missing: ['microsoft_graph_client_secret'],
            consequence: 'only linking from SharePoint needs this',
            optional: true,
          },
        ]}
      />,
    );

    expect(screen.getByRole('alert')).toHaveTextContent(/no nudge/i);
    expect(screen.getByText(/only linking from SharePoint/i)).toBeInTheDocument();
  });

  it('says nothing at all when everything it needs is set', () => {
    const { container } = render(
      <ReadinessWarnings
        readiness={[
          { capability: 'inference', ready: true, missing: [], consequence: '', optional: false },
        ]}
      />,
    );

    expect(container).toBeEmptyDOMElement();
  });
});


describe('after the key is set', () => {
  it('the warning is gone', () => {
    // The screen replaces its state from the save response, so this is what
    // an operator sees the moment a save succeeds — not after a reload. A
    // warning that outlives its fix is how the next real one gets ignored.
    const { container, rerender } = render(
      <ReadinessWarnings
        readiness={[
          {
            capability: 'live_nudges',
            ready: false,
            missing: ['deepgram_api_key'],
            consequence: 'no nudge ever reaches the panel',
            optional: false,
          },
        ]}
      />,
    );
    expect(screen.getByRole('alert')).toBeInTheDocument();

    rerender(
      <ReadinessWarnings
        readiness={[
          {
            capability: 'live_nudges',
            ready: true,
            missing: [],
            consequence: 'no nudge ever reaches the panel',
            optional: false,
          },
        ]}
      />,
    );

    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(container).toBeEmptyDOMElement();
  });
});
