import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi, afterEach } from 'vitest';

import { OperatorPanel } from '../route';

/**
 * The last hop.
 *
 * `state.languages` is the panel's own fixed prop — the live stream's
 * languages were a separate value the screen never read, so wiring the
 * subscription would still have left the strip empty.
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

afterEach(() => vi.unstubAllGlobals());

describe('the panel strip, over a live stream', () => {
  it('shows the languages the stream said the room expects', async () => {
    const source = new FakeSource();
    render(
      <OperatorPanel
        initial={{
          active: null,
          history: [],
          coverage: null,
          languages: [],
          meetingId: 'meeting-1',
        }}
        createSource={() => source as never}
      />,
    );

    source.emit('language', '{"language":"en","expected":true}');
    source.emit('language', '{"language":"zh","expected":true}');

    expect(await screen.findByText('EN')).toBeInTheDocument();
    expect(screen.getByText('ZH')).toBeInTheDocument();
    expect(screen.queryByText(/No language detected/i)).not.toBeInTheDocument();
  });
});
