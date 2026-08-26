import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { AskedItChip } from '../AskedItChip';

describe('AskedItChip', () => {
  it('renders the default label before it is tapped', () => {
    render(<AskedItChip section="Budget" />);
    expect(screen.getByRole('button', { name: 'Asked it' })).toBeInTheDocument();
  });

  it('flips to a confirmed, disabled state on tap with no network round trip (PRD FR-6.6)', () => {
    const onAsked = vi.fn();
    render(<AskedItChip section="Budget" onAsked={onAsked} />);

    fireEvent.click(screen.getByRole('button', { name: 'Asked it' }));

    const button = screen.getByRole('button', { name: 'Asked ✓' });
    expect(button).toBeDisabled();
    expect(button).toHaveClass('asked-it-chip--confirmed');
    expect(button).toHaveAttribute('aria-pressed', 'true');
    expect(onAsked).toHaveBeenCalledTimes(1);
  });

  it('says which section the tap counts towards', () => {
    render(<AskedItChip section="Volumes" />);
    expect(screen.getByRole('button', { name: 'Asked it' })).toHaveAttribute(
      'title',
      'Put this question down and count it against "Volumes".',
    );
  });

  it('promises no section when the nudge belongs to none', () => {
    // A template fallback fires on a phrase. Naming a section it will not
    // move is how the meter came to be trusted for a claim it could not
    // support, so the chip says plainly that nothing moves.
    render(<AskedItChip section={null} />);
    expect(screen.getByRole('button', { name: 'Asked it' })).toHaveAttribute(
      'title',
      'Put this question down. It belongs to no section, so the meter does not move.',
    );
  });

  it('supports custom labels', () => {
    render(<AskedItChip section="Budget" label="Ask this" confirmedLabel="Done" />);
    fireEvent.click(screen.getByRole('button', { name: 'Ask this' }));
    expect(screen.getByRole('button', { name: 'Done' })).toBeInTheDocument();
  });
});
