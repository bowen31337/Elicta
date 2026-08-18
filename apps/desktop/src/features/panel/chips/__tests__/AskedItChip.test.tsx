import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { AskedItChip } from '../AskedItChip';
import type { CoverageSlot } from '../../coverage/types';

const unfilledSlot: CoverageSlot = { id: 'budget', label: 'Budget', filled: false };

describe('AskedItChip', () => {
  it('renders the default label when the slot is not yet asked', () => {
    render(<AskedItChip slot={unfilledSlot} />);
    expect(screen.getByRole('button', { name: 'Asked it' })).toBeInTheDocument();
  });

  it('flips to a confirmed, disabled state on tap with no network round trip (PRD FR-6.6)', () => {
    const onAsked = vi.fn();
    render(<AskedItChip slot={unfilledSlot} onAsked={onAsked} />);

    fireEvent.click(screen.getByRole('button', { name: 'Asked it' }));

    const button = screen.getByRole('button', { name: 'Asked ✓' });
    expect(button).toBeDisabled();
    expect(button).toHaveClass('asked-it-chip--confirmed');
    expect(button).toHaveAttribute('aria-pressed', 'true');
    expect(onAsked).toHaveBeenCalledWith({ ...unfilledSlot, filled: true });
  });

  it('renders already-confirmed when the slot arrives already filled', () => {
    const filledSlot: CoverageSlot = { id: 'timeline', label: 'Timeline', filled: true };
    render(<AskedItChip slot={filledSlot} />);

    const button = screen.getByRole('button', { name: 'Asked ✓' });
    expect(button).toBeDisabled();
  });

  it('supports custom labels', () => {
    render(<AskedItChip slot={unfilledSlot} label="Ask this" confirmedLabel="Done" />);
    fireEvent.click(screen.getByRole('button', { name: 'Ask this' }));
    expect(screen.getByRole('button', { name: 'Done' })).toBeInTheDocument();
  });
});
