import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { GoDeeperChip } from '../GoDeeperChip';
import type { RequestFollowOnFetch } from '../requestFollowOnCandidate';
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

describe('GoDeeperChip', () => {
  it('renders the default label and no result before tapping', () => {
    render(<GoDeeperChip thread={thread} />);
    expect(screen.getByRole('button', { name: 'Go deeper' })).toBeInTheDocument();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('displays the follow-on question on the same thread once the request resolves', async () => {
    const fetchImpl = vi
      .fn<RequestFollowOnFetch>()
      .mockResolvedValue(jsonResponse(200, { question: 'What happens if the budget slips?' }));
    const onFollowOn = vi.fn();
    render(<GoDeeperChip thread={thread} fetch={fetchImpl} onFollowOn={onFollowOn} />);

    fireEvent.click(screen.getByRole('button', { name: 'Go deeper' }));

    expect(screen.getByRole('button', { name: 'Going deeper…' })).toBeDisabled();

    await waitFor(() =>
      expect(screen.getByRole('status')).toHaveTextContent('What happens if the budget slips?'),
    );
    expect(onFollowOn).toHaveBeenCalledWith({ threadId: 'budget', question: 'What happens if the budget slips?' });
    expect(fetchImpl).toHaveBeenCalledWith('/api/threads/budget/go-deeper', expect.anything());
  });

  it('renders a retry label when the request fails', async () => {
    const fetchImpl = vi.fn<RequestFollowOnFetch>().mockResolvedValue(jsonResponse(500, { detail: 'boom' }));
    render(<GoDeeperChip thread={thread} fetch={fetchImpl} />);

    fireEvent.click(screen.getByRole('button', { name: 'Go deeper' }));

    await waitFor(() => expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument());
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('supports custom labels', async () => {
    const fetchImpl = vi.fn<RequestFollowOnFetch>().mockResolvedValue(jsonResponse(200, { question: 'q2' }));
    render(<GoDeeperChip thread={thread} fetch={fetchImpl} label="Dig in" pendingLabel="Digging…" />);

    fireEvent.click(screen.getByRole('button', { name: 'Dig in' }));
    expect(screen.getByRole('button', { name: 'Digging…' })).toBeInTheDocument();

    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('q2'));
  });
});
