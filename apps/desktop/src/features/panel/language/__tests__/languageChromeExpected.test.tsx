import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { LanguageChrome } from '../LanguageChrome';

/**
 * What the strip says, and what it must not say.
 *
 * A live run photographed it reading "No language detected" for a meeting
 * whose engagement expected two languages. The service knew; the strip did
 * not; and the word "detected" was doing work no audio supported.
 */
describe('the language strip', () => {
  it('shows a language the room is expected to use', () => {
    render(
      <LanguageChrome
        languages={[{ language: 'zh', tier: null, heard: false }]}
        activeTier={null}
      />,
    );

    expect(screen.getByText('ZH')).toBeInTheDocument();
  });

  it('does not call an expected language detected', () => {
    render(
      <LanguageChrome
        languages={[{ language: 'zh', tier: null, heard: false }]}
        activeTier={null}
      />,
    );

    expect(screen.queryByText(/No language detected/i)).not.toBeInTheDocument();
    expect(screen.getByText(/listening for/i)).toBeInTheDocument();
  });

  it('marks the two apart when one has been heard and one has not', () => {
    render(
      <LanguageChrome
        languages={[
          { language: 'en', tier: 'tier-1', heard: true, confidence: 0.95 },
          { language: 'zh', tier: null, heard: false },
        ]}
        activeTier="tier-1"
      />,
    );

    expect(screen.getByTitle(/heard in this meeting/i)).toHaveTextContent('EN');
    expect(screen.getByTitle(/expected.*not heard yet/i)).toHaveTextContent('ZH');
  });

  it('still says nothing is known when it knows nothing', () => {
    render(<LanguageChrome languages={[]} activeTier={null} />);

    expect(screen.getByText(/No language detected/i)).toBeInTheDocument();
  });
});
