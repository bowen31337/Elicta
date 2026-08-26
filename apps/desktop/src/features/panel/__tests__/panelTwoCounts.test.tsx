import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi, afterEach } from 'vitest';

import { OperatorPanel } from '../route';

/**
 * Two numbers, and they are not the same number.
 *
 * Reported as "the number in meter does not match the number of nudges in
 * the history". It never did: the meter counts template sections and the
 * history counts questions. What made that unreadable is that the meter sits
 * directly above the nudge stack and, on the meeting it was first seen on,
 * the bank happened to have eight sections at the moment there were eight
 * nudges. "0 of 8" read as a nudge counter, and stayed read that way when
 * the nudges went to fifteen and the sections stayed at eight.
 *
 * So each number has to say what it is where it is shown, and the count the
 * operator was actually looking for -- how many questions they are sitting
 * on -- has to exist at all. Thirteen of fifteen had no disposition on the
 * reported meeting and nothing on the panel said so.
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
    template_section: null,
  });
}

function panel(source: FakeSource) {
  return render(
    <OperatorPanel
      initial={{ active: null, history: [], coverage: null, languages: [], meetingId: 'meeting-1' }}
      createSource={() => source as never}
    />,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe('the two counts on the panel', () => {
  it('says the meter is counting sections, on the meter itself', async () => {
    const source = new FakeSource();
    panel(source);

    source.emit(
      'coverage',
      JSON.stringify({
        slots: [
          { id: 'a', label: 'Scope', filled: false },
          { id: 'b', label: 'Volumes', filled: false },
        ],
        time_remaining_ms: null,
      }),
    );

    // Not only in the accessible name: the operator reading this mid-meeting
    // is looking at it, not listening to it.
    expect(await screen.findByText(/sections/i)).toBeInTheDocument();
  });

  it('says how many questions are still waiting, where the questions are', async () => {
    const source = new FakeSource();
    panel(source);

    // Four raised: one live, three earlier, of which one is already dealt
    // with. The number the operator wants is the two they have not answered.
    source.emit('nudge', nudgeFrame('n-1', 'taken'));
    source.emit('nudge', nudgeFrame('n-2', null));
    source.emit('nudge', nudgeFrame('n-3', null));
    source.emit('nudge', nudgeFrame('n-4', null));

    expect(await screen.findByText(/2 still waiting/i)).toBeInTheDocument();
  });

  it('says nothing about a backlog when there is none', async () => {
    const source = new FakeSource();
    panel(source);

    source.emit('nudge', nudgeFrame('n-1', 'taken'));
    source.emit('nudge', nudgeFrame('n-2', null));

    expect(await screen.findByRole('button', { name: /Bring back Stub n-1/ })).toBeInTheDocument();
    expect(screen.queryByText(/still waiting/i)).not.toBeInTheDocument();
  });
});
