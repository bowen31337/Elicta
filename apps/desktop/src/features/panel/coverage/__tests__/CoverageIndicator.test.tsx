import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { CoverageIndicator } from '../CoverageIndicator';
import type { CoverageSummary } from '../types';

describe('CoverageIndicator', () => {
  it('renders sections filled versus the template total', () => {
    const summary: CoverageSummary = {
      slots: [
        { id: 'a', label: 'A', filled: true },
        { id: 'b', label: 'B', filled: false },
      ],
      timeRemainingMs: null,
    };

    render(<CoverageIndicator summary={summary} />);
    // Asserted on what is on screen rather than on an accessible name: the
    // change this guards is that the reading no longer needs one to make
    // sense.
    expect(screen.getByRole('group', { name: /1 of 2 sections covered/i })).toHaveTextContent(
      '1 of 2',
    );
  });

  it('renders time remaining when present', () => {
    const summary: CoverageSummary = { slots: [], timeRemainingMs: 90_000 };

    render(<CoverageIndicator summary={summary} />);
    expect(screen.getByText('1:30 left')).toBeInTheDocument();
  });

  it('omits time remaining when the stream has not supplied one', () => {
    const summary: CoverageSummary = { slots: [], timeRemainingMs: null };

    render(<CoverageIndicator summary={summary} />);
    expect(screen.queryByText(/left/)).not.toBeInTheDocument();
  });

  it('shows a pending placeholder before the first stream update arrives', () => {
    render(<CoverageIndicator summary={null} />);
    expect(screen.getByText('— / —')).toBeInTheDocument();
  });
});

describe('reading the indicator without being told what it is', () => {
  /**
   * Reported: "0/8 does not indicate anything".
   *
   * Two bare numbers and a row of dashes, none of which said what they
   * counted. The operator is glancing away from a client for half a second
   * — the reading has to arrive in that glance, which rules out a tooltip
   * as the primary answer: a tooltip needs hover, intent, and a second look.
   * The words are cheap and the ambiguity is not.
   */
  it('says what the count counts', () => {
    render(
      <CoverageIndicator
        summary={{
          slots: [
            { id: 'a', label: 'Volumes', filled: true },
            { id: 'b', label: 'Performance', filled: false },
          ],
          timeRemainingMs: null,
        }}
      />,
    );

    expect(screen.getByText(/covered/i)).toBeInTheDocument();
  });

  it('says what the clock is measuring', () => {
    render(
      <CoverageIndicator
        summary={{
          slots: [{ id: 'a', label: 'Volumes', filled: false }],
          timeRemainingMs: 22 * 60 * 1000,
        }}
      />,
    );

    expect(screen.getByText(/left/i)).toBeInTheDocument();
  });

  it('explains itself in full to anyone who stops to look', () => {
    /* The tooltip is the second answer, not the first: it carries what will
       not fit on one line of a 420px panel. */
    render(
      <CoverageIndicator
        summary={{
          slots: [{ id: 'a', label: 'Volumes', filled: false }],
          timeRemainingMs: null,
        }}
      />,
    );

    expect(screen.getByRole('group', { name: /covered/i })).toHaveAttribute('title');
  });

  it('still says nothing it does not know', () => {
    /* The placeholder stays a placeholder — a labelled zero would claim a
       measurement that has not happened. */
    render(<CoverageIndicator summary={null} />);

    expect(screen.getByText(/— \/ —/)).toBeInTheDocument();
  });
});
