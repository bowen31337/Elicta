import { describe, expect, it } from 'vitest';
import { act, renderHook } from '@testing-library/react';

import { supersedes, useSessionStream } from '../useSessionStream';
import type { SessionStreamSource, SessionStreamSourceFactory } from '../useSessionStream';
import { parseSessionStreamEvent } from '../sessionStreamEvents';

class FakeSource implements SessionStreamSource {
  closed = false;
  private readonly listeners = new Map<string, Set<(event: MessageEvent<string>) => void>>();

  addEventListener(type: string, listener: (event: MessageEvent<string>) => void): void {
    if (!this.listeners.has(type)) this.listeners.set(type, new Set());
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

function fakeFactory(): { createSource: SessionStreamSourceFactory; sources: FakeSource[] } {
  const sources: FakeSource[] = [];
  return {
    createSource: () => {
      const source = new FakeSource();
      sources.push(source);
      return source;
    },
    sources,
  };
}

function line(seq: number, text: string, speaker: string | null = null, at = 1_700_000_000_000) {
  return JSON.stringify({ seq, text, speaker, at: at + seq * 1000 });
}

describe('parsing an utterance frame', () => {
  it('reads the wire shape the service sends', () => {
    const parsed = parseSessionStreamEvent('utterance', line(3, 'Three fifty a day.', 'client'));

    expect(parsed).toEqual({
      type: 'utterance',
      utterance: {
        seq: 3,
        text: 'Three fifty a day.',
        speaker: 'client',
        at: 1_700_000_003_000,
        final: true,
      },
    });
  });

  it('treats a line with no `final` as finished', () => {
    // A service that predates interim lines only ever sent settled ones.
    // Defaulting the other way would render a whole meeting as though every
    // word in it might still change.
    const parsed = parseSessionStreamEvent('utterance', line(0, 'Yes.', null));

    expect(parsed).toEqual(
      expect.objectContaining({ utterance: expect.objectContaining({ final: true }) }),
    );
  });

  it('carries a line that is still being spoken as unfinished', () => {
    const parsed = parseSessionStreamEvent(
      'utterance',
      JSON.stringify({ seq: 0, text: 'Three fifty a', speaker: null, at: 1, final: false }),
    );

    expect(parsed).toEqual(
      expect.objectContaining({ utterance: expect.objectContaining({ final: false }) }),
    );
  });

  it('keeps an unattributed line as unattributed rather than inventing a speaker', () => {
    // Nobody enrolled is the ordinary deployment, and a line put in the wrong
    // person's mouth is worse than one in nobody's.
    const parsed = parseSessionStreamEvent('utterance', line(0, 'It depends.', null));
    expect(parsed).toMatchObject({ utterance: { speaker: null } });
  });
});

describe('the transcript the panel holds', () => {
  it('is empty until the stream says anything', () => {
    const { createSource } = fakeFactory();
    const { result } = renderHook(() => useSessionStream('meeting-1', { createSource }));

    expect(result.current.transcript).toEqual([]);
  });

  it('accumulates every line in the order it was said', () => {
    const { createSource, sources } = fakeFactory();
    const { result } = renderHook(() => useSessionStream('meeting-1', { createSource }));

    act(() => {
      sources[0].dispatch('utterance', line(0, 'How many a day?', 'operator'));
      sources[0].dispatch('utterance', line(1, 'Three fifty.', 'client'));
    });

    expect(result.current.transcript.map((entry) => entry.text)).toEqual([
      'How many a day?',
      'Three fifty.',
    ]);
  });

  it('does not double a line when the stream replays its backlog', () => {
    // `EventSource` reconnects on its own schedule every few minutes and the
    // service replays the whole meeting on every connect — that is how a panel
    // opened mid-meeting catches up. Appending blindly turned three lines into
    // six, then nine, which is exactly what happened to the nudges.
    const { createSource, sources } = fakeFactory();
    const { result } = renderHook(() => useSessionStream('meeting-1', { createSource }));

    act(() => {
      sources[0].dispatch('utterance', line(0, 'How many a day?', 'operator'));
      sources[0].dispatch('utterance', line(1, 'Three fifty.', 'client'));
    });
    act(() => {
      sources[0].dispatch('utterance', line(0, 'How many a day?', 'operator'));
      sources[0].dispatch('utterance', line(1, 'Three fifty.', 'client'));
      sources[0].dispatch('utterance', line(2, 'More at Christmas.', 'client'));
    });

    expect(result.current.transcript.map((entry) => entry.text)).toEqual([
      'How many a day?',
      'Three fifty.',
      'More at Christmas.',
    ]);
  });

  it('keeps two identical sentences apart, because people repeat themselves', () => {
    // Deduping on the text would silently swallow the second "Yes." — the
    // reason the service assigns an index rather than the panel counting.
    const { createSource, sources } = fakeFactory();
    const { result } = renderHook(() => useSessionStream('meeting-1', { createSource }));

    act(() => {
      sources[0].dispatch('utterance', line(0, 'Yes.', 'client'));
      sources[0].dispatch('utterance', line(1, 'Could you repeat that?', 'operator'));
      sources[0].dispatch('utterance', line(2, 'Yes.', 'client'));
    });

    expect(result.current.transcript).toHaveLength(3);
  });

  it('holds lines in transcript order even if a frame arrives out of turn', () => {
    const { createSource, sources } = fakeFactory();
    const { result } = renderHook(() => useSessionStream('meeting-1', { createSource }));

    act(() => {
      sources[0].dispatch('utterance', line(2, 'Third.', 'client'));
      sources[0].dispatch('utterance', line(0, 'First.', 'operator'));
      sources[0].dispatch('utterance', line(1, 'Second.', 'client'));
    });

    expect(result.current.transcript.map((entry) => entry.text)).toEqual([
      'First.',
      'Second.',
      'Third.',
    ]);
  });
});

describe('whether the room will be transcribed at all', () => {
  it('is read off the lane frame', () => {
    const parsed = parseSessionStreamEvent(
      'lane',
      JSON.stringify({ model_reachable: true, reason: null, live_transcription: false }),
    );

    expect(parsed).toMatchObject({ lane: { liveTranscription: false } });
  });

  it('is assumed working when the service does not say', () => {
    // An older service sends no such field. Reading absence as "not
    // configured" would put a permanent notice on a panel that is
    // transcribing perfectly well, and a notice that cries wolf stops being
    // read — the same reasoning `modelReachable` starts true for.
    const parsed = parseSessionStreamEvent(
      'lane',
      JSON.stringify({ model_reachable: true, reason: null }),
    );

    expect(parsed).toMatchObject({ lane: { liveTranscription: true } });
  });

  it('reaches the panel through the hook', () => {
    const { createSource, sources } = fakeFactory();
    const { result } = renderHook(() => useSessionStream('meeting-1', { createSource }));

    expect(result.current.liveTranscription).toBe(true);
    act(() => {
      sources[0].dispatch(
        'lane',
        JSON.stringify({ model_reachable: true, reason: null, live_transcription: false }),
      );
    });

    expect(result.current.liveTranscription).toBe(false);
  });
});

describe('a line that arrives more than once', () => {
  /**
   * The rule was "keep the first, ignore the rest", and it was right for as
   * long as a line could only arrive once — the stream replays the whole
   * meeting on every connect, so ignoring a repeat is what makes a reconnect
   * idempotent.
   *
   * A streaming recogniser broke that without changing its shape. A line now
   * arrives many times: the words so far, growing, then the finished sentence
   * in the same place. Keeping the first meant keeping the first *fragment* —
   * the panel showed "Hey, what's" for the rest of the meeting while the
   * service held "Hey. What's up?". Nothing was broken except the screen.
   */
  const line = (text: string, final: boolean) =>
    ({ seq: 0, text, speaker: null, at: 1, final }) as const;

  it('takes a line where there was none', () => {
    expect(supersedes(undefined, line('Hey', false))).toBe(true);
  });

  it('takes the longer words of a line still being spoken', () => {
    expect(supersedes(line('Hey', false), line("Hey, what's", false))).toBe(true);
  });

  it('takes the finished sentence over the fragment it grew from', () => {
    // The failure exactly: without this the screen keeps the fragment.
    expect(supersedes(line("Hey, what's", false), line("Hey. What's up?", true))).toBe(true);
  });

  it('keeps a finished line when the same one is replayed', () => {
    // Every reconnect replays the whole meeting. Re-filing each line would
    // re-render the transcript on a schedule nobody chose.
    expect(supersedes(line('Hey. What\'s up?', true), line('Hey. What\'s up?', true))).toBe(false);
  });

  it('never un-finishes a line that has settled', () => {
    // A backlog arriving out of order must not turn a finished sentence back
    // into a fragment on screen.
    expect(supersedes(line("Hey. What's up?", true), line("Hey, what's", false))).toBe(false);
  });

  it('ignores an identical interim rather than re-rendering for nothing', () => {
    expect(supersedes(line('Hey', false), line('Hey', false))).toBe(false);
  });
});
