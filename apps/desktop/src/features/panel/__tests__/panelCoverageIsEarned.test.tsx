import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi, afterEach, beforeEach } from 'vitest';

import { OperatorPanel } from '../route';

/**
 * The meter counts what the service knows, and nothing else.
 *
 * It used to count the operator's own taps, kept in `localStorage`, each one
 * attributed to whichever section happened to be first unticked. Eight
 * questions about "a lot" and "some" ticked off Volumes, Performance and
 * Integrations in list order, and the panel reported eight of eight covered
 * on evidence of nothing.
 *
 * The tick was also one-way, and the chip that made it was gated on there
 * being an unticked section left. So on the eighth tap the chip removed
 * itself permanently, and no disposition could ever be recorded again --
 * which is why nothing was ever marked "Asked".
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

const SECTIONS = ['Scope and outcomes', 'Volumes', 'Performance'];

function coverageFrame(filled: readonly string[] = []) {
  return JSON.stringify({
    slots: SECTIONS.map((id) => ({ id, label: id, filled: filled.includes(id) })),
    time_remaining_ms: null,
  });
}

function nudgeFrame(id: string, section: string | null) {
  return JSON.stringify({
    id,
    stub: `Stub ${id}`,
    question: `Question ${id}?`,
    trigger_reason: 'unquantified_amount',
    created_at: 1_700_000_000_000,
    disposition: null,
    template_section: section,
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

beforeEach(() => {
  window.localStorage.clear();
  vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 200 })));
});
afterEach(() => vi.unstubAllGlobals());

describe('the coverage meter', () => {
  it('reports what the stream says, even when the operator has tapped', async () => {
    const source = new FakeSource();
    panel(source);

    source.emit('coverage', coverageFrame([]));
    source.emit('nudge', nudgeFrame('n-1', 'Volumes'));
    await screen.findByText('Question n-1?');
    await userEvent.click(screen.getByRole('button', { name: /Asked it/i }));

    // The tap records a disposition; the service decides what that means for
    // the meter and says so on the next coverage frame. Until it does, the
    // panel must not move the meter on its own — that invention is the bug.
    await waitFor(() => expect(screen.getByText(/0 of 3/)).toBeInTheDocument());
  });

  it('moves when the service says it moved', async () => {
    const source = new FakeSource();
    panel(source);

    source.emit('coverage', coverageFrame([]));
    expect(await screen.findByText(/0 of 3/)).toBeInTheDocument();

    source.emit('coverage', coverageFrame(['Volumes']));
    await waitFor(() => expect(screen.getByText(/1 of 3/)).toBeInTheDocument());
  });

  it('says what it is counting, and does not claim the client answered', async () => {
    const source = new FakeSource();
    panel(source);
    source.emit('coverage', coverageFrame([]));

    const meter = await screen.findByRole('group', { name: /asked about/i });
    expect(meter).toBeInTheDocument();
    expect(screen.queryByText(/^covered$/)).not.toBeInTheDocument();
  });

  it('keeps offering "Asked it" when every section is already filled', async () => {
    const source = new FakeSource();
    panel(source);

    // The self-lock: with nothing left unfilled the chip used to vanish, so
    // no further nudge could ever be marked asked.
    source.emit('coverage', coverageFrame(SECTIONS));
    source.emit('nudge', nudgeFrame('n-1', 'Volumes'));

    expect(await screen.findByText('Question n-1?')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Asked it/i })).toBeInTheDocument();
  });

  it('offers it for a nudge belonging to no section at all', async () => {
    const source = new FakeSource();
    panel(source);

    source.emit('coverage', coverageFrame([]));
    source.emit('nudge', nudgeFrame('n-1', null));

    expect(await screen.findByText('Question n-1?')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Asked it/i })).toBeInTheDocument();
  });

  it('remembers nothing in the browser', async () => {
    const source = new FakeSource();
    panel(source);

    source.emit('coverage', coverageFrame([]));
    source.emit('nudge', nudgeFrame('n-1', 'Volumes'));
    await screen.findByText('Question n-1?');
    await userEvent.click(screen.getByRole('button', { name: /Asked it/i }));

    // The record belongs in the database, where a restart and a second
    // screen both see it. A copy here is a second answer nobody reconciles.
    expect(Object.keys(window.localStorage).filter((k) => /asked/i.test(k))).toEqual([]);
  });
});
