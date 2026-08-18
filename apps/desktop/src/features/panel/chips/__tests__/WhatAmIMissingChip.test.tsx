import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { WhatAmIMissingChip } from '../WhatAmIMissingChip';
import type { CoverageSummary } from '../../coverage/types';

const summary: CoverageSummary = {
  slots: [
    { id: 'scope', label: 'Scope boundary', filled: true },
    { id: 'budget', label: 'Budget', filled: false },
    { id: 'risks', label: 'Risks', filled: false },
  ],
  timeRemainingMs: 60_000,
};

describe('WhatAmIMissingChip', () => {
  it('renders the default label and no result before tapping', () => {
    render(<WhatAmIMissingChip summary={summary} />);
    expect(screen.getByRole('button', { name: 'What am I missing?' })).toBeInTheDocument();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('displays the highest-urgency unfilled section on tap, with no network round trip', () => {
    const onSurfaced = vi.fn();
    render(<WhatAmIMissingChip summary={summary} onSurfaced={onSurfaced} />);

    fireEvent.click(screen.getByRole('button', { name: 'What am I missing?' }));

    expect(screen.getByRole('status')).toHaveTextContent('Budget');
    expect(onSurfaced).toHaveBeenCalledWith({ id: 'budget', label: 'Budget', filled: false });
  });

  it('displays the clear label when every section is already filled', () => {
    const allFilled: CoverageSummary = {
      slots: [{ id: 'scope', label: 'Scope boundary', filled: true }],
      timeRemainingMs: 30_000,
    };
    render(<WhatAmIMissingChip summary={allFilled} />);

    fireEvent.click(screen.getByRole('button', { name: 'What am I missing?' }));

    expect(screen.getByRole('status')).toHaveTextContent('Nothing missing');
  });

  it('supports custom labels', () => {
    const allFilled: CoverageSummary = {
      slots: [{ id: 'scope', label: 'Scope boundary', filled: true }],
      timeRemainingMs: null,
    };
    render(
      <WhatAmIMissingChip summary={allFilled} label="Check gaps" clearLabel="All covered" />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Check gaps' }));

    expect(screen.getByRole('status')).toHaveTextContent('All covered');
  });
});
