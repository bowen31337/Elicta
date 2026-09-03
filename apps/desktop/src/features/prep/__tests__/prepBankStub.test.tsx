import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';

import { CandidateHeadline } from '../CandidateHeadline';

/**
 * What the reviewer sees is what the room will see.
 *
 * The bank was reviewed here as full phrasings and asked in the meeting as a
 * glance, and nothing on this screen showed the glance. So an operator could
 * approve a bank without ever seeing the form of it they would actually work
 * from — and the form they would work from was, for every bank compiled to
 * date, empty.
 */
describe('a bank candidate on the review screen', () => {
  it('leads with the short form the panel will show', () => {
    render(
      <CandidateHeadline
        candidate={{
          id: 'c-1',
          stub: 'Monthly arrivals',
          phrasing: 'How many arrivals do you handle in a month, across all three sites?',
          priority: 1,
          sourceDoc: null,
          authorityMatch: [],
        }}
      />,
    );

    expect(screen.getByText('Monthly arrivals')).toBeInTheDocument();
    // And the wording is still there: this screen is where it gets edited, so
    // shortening the review to keywords alone would remove the thing being
    // reviewed.
    expect(
      screen.getByText('How many arrivals do you handle in a month, across all three sites?'),
    ).toBeInTheDocument();
  });

  it('derives the short form for a bank compiled before stubs existed', () => {
    render(
      <CandidateHeadline
        candidate={{
          id: 'c-1',
          stub: '',
          phrasing: 'What is the current process for booking a slot?',
          priority: 1,
          sourceDoc: null,
          authorityMatch: [],
        }}
      />,
    );

    const headline = screen.getByTestId('candidate-headline');
    expect(headline.textContent?.split(/\s+/).length).toBeLessThanOrEqual(5);
    expect(headline.textContent?.toLowerCase()).toContain('booking');
  });

  it('does not repeat itself when the two forms would read the same', () => {
    // A question already short enough is its own headline, and printing it
    // twice makes the row look like a rendering fault.
    render(
      <CandidateHeadline
        candidate={{
          id: 'c-1',
          stub: 'Peak volumes',
          phrasing: 'Peak volumes',
          priority: 1,
          sourceDoc: null,
          authorityMatch: [],
        }}
      />,
    );

    expect(screen.getAllByText('Peak volumes')).toHaveLength(1);
  });
});
