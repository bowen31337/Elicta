import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { EscapeHatchInput } from '../EscapeHatchInput';

describe('EscapeHatchInput', () => {
  it('is present in the document, not hidden behind a toggle (PRD FR-6.9)', () => {
    render(<EscapeHatchInput onSubmit={vi.fn()} />);
    expect(screen.getByRole('textbox', { name: 'Ask a question' })).toBeVisible();
  });

  it('renders with de-emphasised styling distinct from a primary control', () => {
    render(<EscapeHatchInput onSubmit={vi.fn()} />);
    const input = screen.getByRole('textbox', { name: 'Ask a question' });
    expect(input).toHaveClass('escape-hatch__input');
  });

  it('submits the typed text on Enter and clears the field', () => {
    const onSubmit = vi.fn();
    render(<EscapeHatchInput onSubmit={onSubmit} now={() => 42} />);
    const input = screen.getByRole('textbox', { name: 'Ask a question' });

    fireEvent.change(input, { target: { value: 'what am I missing?' } });
    fireEvent.keyDown(input, { key: 'Enter' });

    expect(onSubmit).toHaveBeenCalledWith({ text: 'what am I missing?', submittedAt: 42 });
    expect(input).toHaveValue('');
  });

  it('does not submit on other keys', () => {
    const onSubmit = vi.fn();
    render(<EscapeHatchInput onSubmit={onSubmit} />);
    const input = screen.getByRole('textbox', { name: 'Ask a question' });

    fireEvent.change(input, { target: { value: 'partial' } });
    fireEvent.keyDown(input, { key: 'a' });

    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('uses a placeholder that reads as secondary rather than a primary prompt', () => {
    render(<EscapeHatchInput onSubmit={vi.fn()} />);
    expect(screen.getByPlaceholderText('Type a question instead…')).toBeInTheDocument();
  });

  it('supports a custom placeholder', () => {
    render(<EscapeHatchInput onSubmit={vi.fn()} placeholder="Or ask anything…" />);
    expect(screen.getByPlaceholderText('Or ask anything…')).toBeInTheDocument();
  });
});
