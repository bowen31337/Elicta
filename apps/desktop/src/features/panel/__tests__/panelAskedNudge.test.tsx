import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi, afterEach } from 'vitest';

import { OperatorPanel } from '../route';

/**
 * A question already asked must not present itself as one still waiting.
 *
 * Two ways it can: the operator taps "Asked it" and the card recedes looking
 * exactly like the ones they have not got to; or the stream replays its
 * backlog after a reconnect and hands back a nudge they dealt with an hour
 * ago as the live card. The second is the one that bites, because several
 * nudges on the same trigger carry near-identical wording — the operator has
 * nothing else to tell them apart by.
 */
class FakeSource {
  listeners = new Map<string, (event: MessageEvent<string>) => void>();
  addEventListener(name: string, handler: (event: MessageEvent<string>) => void) {
    this.listeners.set(name, handler);
  }
  removeEventListener(name: string) {
    this.listeners.delete(name);
  }
  close() {}
  emit(name: string, data: string) {
    this.listeners.get(name)?.({ data } as MessageEvent<string>);
  }
}

function nudgeFrame(id: string, disposition: string | null) {
  return JSON.stringify({
    id,
    stub: `Stub ${id}`,
    question: `Question ${id}?`,
    trigger_reason: 'unquantified_amount',
    created_at: 1_700_000_000_000,
    disposition,
  });
}

afterEach(() => vi.unstubAllGlobals());

describe('a nudge the operator has already dealt with', () => {
  it('replays into history marked "Asked", never as the live card', async () => {
    const source = new FakeSource();
    render(
      <OperatorPanel
        initial={{ active: null, history: [], coverage: null, languages: [], meetingId: 'meeting-1' }}
        createSource={() => source as never}
      />,
    );

    // Alone, deliberately. With a second nudge behind it the first recedes
    // whatever its disposition, and the assertion passes against a panel
    // that ignores the field entirely.
    source.emit('nudge', nudgeFrame('n-1', 'taken'));

    expect(await screen.findByRole('button', { name: /Bring back Stub n-1/ })).toBeInTheDocument();
    expect(screen.getByText('Asked')).toBeInTheDocument();
    expect(screen.queryByText('Question n-1?')).not.toBeInTheDocument();
  });

  it('marks the card the moment "Asked it" is pressed, not on the next connect', async () => {
    const source = new FakeSource();
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 200 })));
    render(
      <OperatorPanel
        initial={{ active: null, history: [], coverage: null, languages: [], meetingId: 'meeting-1' }}
        createSource={() => source as never}
      />,
    );

    source.emit(
      'coverage',
      JSON.stringify({
        slots: [{ id: 'budget', label: 'Budget', filled: false }],
        time_remaining_ms: null,
      }),
    );
    source.emit('nudge', nudgeFrame('n-1', null));
    await screen.findByText('Question n-1?');
    await userEvent.click(screen.getByRole('button', { name: /Asked it/i }));

    await waitFor(() => expect(screen.getByText('Asked')).toBeInTheDocument());
  });
});
