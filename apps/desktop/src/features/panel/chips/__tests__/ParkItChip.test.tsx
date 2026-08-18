import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ParkItChip } from '../ParkItChip';
import type { ParkThreadFetch } from '../parkThread';
import type { Thread } from '../types';

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  } as Response;
}

const thread: Thread = {
  id: 'budget',
  question: 'What is your budget for this project?',
  operatorAskedAt: null,
};

describe('ParkItChip', () => {
  it('renders the default label and no confirmation before tapping', () => {
    render(<ParkItChip thread={thread} />);
    expect(screen.getByRole('button', { name: 'Park it' })).toBeInTheDocument();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('persists the thread to the open_questions table and confirms without dismissing it', async () => {
    const fetchImpl = vi.fn<ParkThreadFetch>().mockResolvedValue(jsonResponse(200, { open_question_id: 'oq-1' }));
    const onParked = vi.fn();
    render(<ParkItChip thread={thread} fetch={fetchImpl} onParked={onParked} />);

    fireEvent.click(screen.getByRole('button', { name: 'Park it' }));

    expect(screen.getByRole('button', { name: 'Parking…' })).toBeDisabled();

    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Parked ✓'));
    expect(onParked).toHaveBeenCalledWith({ threadId: 'budget', openQuestionId: 'oq-1' });
    expect(fetchImpl).toHaveBeenCalledWith('/api/threads/budget/park', expect.anything());

    // The chip re-enables and keeps its default label rather than disabling
    // itself the way a resolving chip (Asked it) would -- parking never
    // dismisses the thread.
    expect(screen.getByRole('button', { name: 'Park it' })).not.toBeDisabled();
  });

  it('renders a retry label when the request fails', async () => {
    const fetchImpl = vi.fn<ParkThreadFetch>().mockResolvedValue(jsonResponse(500, { detail: 'boom' }));
    render(<ParkItChip thread={thread} fetch={fetchImpl} />);

    fireEvent.click(screen.getByRole('button', { name: 'Park it' }));

    await waitFor(() => expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument());
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('supports custom labels', async () => {
    const fetchImpl = vi.fn<ParkThreadFetch>().mockResolvedValue(jsonResponse(200, { open_question_id: 'oq-1' }));
    render(
      <ParkItChip
        thread={thread}
        fetch={fetchImpl}
        label="Defer"
        pendingLabel="Deferring…"
        parkedLabel="Deferred"
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Defer' }));
    expect(screen.getByRole('button', { name: 'Deferring…' })).toBeInTheDocument();

    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Deferred'));
  });
});
