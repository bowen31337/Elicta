import { describe, expect, it } from 'vitest';
import { renderHook, act } from '@testing-library/react';

import { useSessionStream } from '../useSessionStream';

/**
 * The subscription that was missing.
 *
 * `useSessionStream` listened for `coverage`, `nudge` and `lane`. A `language`
 * frame arrived and nothing was registered to hear it, so the strip stayed
 * empty however much the service sent.
 */
class FakeSource {
  listeners = new Map<string, (event: MessageEvent<string>) => void>();
  closed = false;

  addEventListener(name: string, handler: (event: MessageEvent<string>) => void) {
    this.listeners.set(name, handler);
  }

  removeEventListener(name: string) {
    this.listeners.delete(name);
  }

  close() {
    this.closed = true;
  }

  emit(name: string, data: string) {
    this.listeners.get(name)?.({ data } as MessageEvent<string>);
  }
}

describe('the panel listening for languages', () => {
  it('subscribes to the language frame at all', () => {
    const source = new FakeSource();
    renderHook(() =>
      useSessionStream('meeting-1', { createSource: () => source as never }),
    );

    expect([...source.listeners.keys()]).toContain('language');
  });

  it('collects the languages the room is expected to use', () => {
    const source = new FakeSource();
    const { result } = renderHook(() =>
      useSessionStream('meeting-1', { createSource: () => source as never }),
    );

    act(() => {
      source.emit('language', '{"language":"en","expected":true}');
      source.emit('language', '{"language":"zh","expected":true}');
    });

    expect(result.current.languages.map((l) => l.language)).toEqual(['en', 'zh']);
    expect(result.current.languages.every((l) => !l.heard)).toBe(true);
  });

  it('does not add the same language twice when the stream repeats it', () => {
    const source = new FakeSource();
    const { result } = renderHook(() =>
      useSessionStream('meeting-1', { createSource: () => source as never }),
    );

    act(() => {
      source.emit('language', '{"language":"en","expected":true}');
      source.emit('language', '{"language":"en","expected":true}');
    });

    expect(result.current.languages).toHaveLength(1);
  });
});
