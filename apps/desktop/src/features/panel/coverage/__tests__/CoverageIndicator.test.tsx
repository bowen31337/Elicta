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
    expect(screen.getByLabelText('Sections filled')).toHaveTextContent('1 / 2');
  });

  it('renders time remaining when present', () => {
    const summary: CoverageSummary = { slots: [], timeRemainingMs: 90_000 };

    render(<CoverageIndicator summary={summary} />);
    expect(screen.getByLabelText('Time remaining')).toHaveTextContent('1:30');
  });

  it('omits time remaining when the stream has not supplied one', () => {
    const summary: CoverageSummary = { slots: [], timeRemainingMs: null };

    render(<CoverageIndicator summary={summary} />);
    expect(screen.queryByLabelText('Time remaining')).not.toBeInTheDocument();
  });

  it('shows a pending placeholder before the first stream update arrives', () => {
    render(<CoverageIndicator summary={null} />);
    expect(screen.getByLabelText('Sections filled')).toHaveTextContent('— / —');
  });
});
