import { describe, expect, it, vi } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { useSessionStream } from '../useSessionStream';
import type { SessionStreamSource, SessionStreamSourceFactory } from '../useSessionStream';

/**
 * Stands in for `EventSource` so tests can dispatch named SSE events
 * synchronously instead of standing up a real connection (or a jsdom
 * polyfill for one).
 */
class FakeSource implements SessionStreamSource {
  closed = false;
  private readonly listeners = new Map<string, Set<(event: MessageEvent<string>) => void>>();

  addEventListener(type: string, listener: (event: MessageEvent<string>) => void): void {
    if (!this.listeners.has(type)) {
      this.listeners.set(type, new Set());
    }
    this.listeners.get(type)!.add(listener);
  }

  removeEventListener(type: string, listener: (event: MessageEvent<string>) => void): void {
    this.listeners.get(type)?.delete(listener);
  }

  close(): void {
    this.closed = true;
  }

  dispatch(type: string, data: string): void {
    for (const listener of this.listeners.get(type) ?? []) {
      listener({ data } as MessageEvent<string>);
    }
  }
}

function fakeFactory(): { createSource: SessionStreamSourceFactory; sources: FakeSource[]; urls: string[] } {
  const sources: FakeSource[] = [];
  const urls: string[] = [];
  const createSource = (url: string) => {
    urls.push(url);
    const source = new FakeSource();
    sources.push(source);
    return source;
  };
  return { createSource, sources, urls };
}

describe('useSessionStream', () => {
  it('connects to the meeting session stream endpoint', () => {
    const { createSource, urls } = fakeFactory();
    renderHook(() => useSessionStream('meeting-1', { createSource }));

    expect(urls).toEqual(['/api/meetings/meeting-1/session/stream']);
  });

  it('has no coverage summary until the stream delivers one', () => {
    const { createSource } = fakeFactory();
    const { result } = renderHook(() => useSessionStream('meeting-1', { createSource }));

    expect(result.current.coverage).toBeNull();
  });

  it('updates coverage state from a coverage event', () => {
    const { createSource, sources } = fakeFactory();
    const { result } = renderHook(() => useSessionStream('meeting-1', { createSource }));

    act(() => {
      sources[0].dispatch(
        'coverage',
        JSON.stringify({ slots: [{ id: 'a', label: 'A', filled: true }], time_remaining_ms: 60_000 }),
      );
    });

    expect(result.current.coverage).toEqual({
      slots: [{ id: 'a', label: 'A', filled: true }],
      timeRemainingMs: 60_000,
    });
  });

  it('forwards nudge events to onNudge without touching coverage state', () => {
    const { createSource, sources } = fakeFactory();
    const onNudge = vi.fn();
    const { result } = renderHook(() => useSessionStream('meeting-1', { createSource, onNudge }));

    act(() => {
      sources[0].dispatch(
        'nudge',
        JSON.stringify({
          id: 'nudge-1',
          stub: 'Quantify "fast"',
          question: 'What does fast mean?',
          trigger_reason: 'vague adjective',
          created_at: 1,
        }),
      );
    });

    expect(onNudge).toHaveBeenCalledWith({
      id: 'nudge-1',
      stub: 'Quantify "fast"',
      question: 'What does fast mean?',
      triggerReason: 'vague adjective',
      createdAt: 1,
      disposition: null,
    });
    expect(result.current.coverage).toBeNull();
  });

  it('closes the source on unmount', () => {
    const { createSource, sources } = fakeFactory();
    const { unmount } = renderHook(() => useSessionStream('meeting-1', { createSource }));

    unmount();

    expect(sources[0].closed).toBe(true);
  });

  it('reconnects to the new meeting when the meeting id changes', () => {
    const { createSource, sources, urls } = fakeFactory();
    const { rerender } = renderHook(({ meetingId }) => useSessionStream(meetingId, { createSource }), {
      initialProps: { meetingId: 'meeting-1' },
    });

    rerender({ meetingId: 'meeting-2' });

    expect(sources[0].closed).toBe(true);
    expect(urls).toEqual([
      '/api/meetings/meeting-1/session/stream',
      '/api/meetings/meeting-2/session/stream',
    ]);
  });
});

describe('before a meeting starts', () => {
  it('opens no connection when there is no meeting to follow', () => {
    const createSource = vi.fn();

    renderHook(() => useSessionStream(null, { createSource }));

    // A stream to nothing would reconnect in a loop against a 404, which is
    // exactly the state the panel sits in before capture begins.
    expect(createSource).not.toHaveBeenCalled();
  });
});
