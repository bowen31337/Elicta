import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { OperatorPanel } from '../route';
import { IDLE, type CaptureSnapshot, type CaptureStore } from '../../../services/captureSession';

/**
 * The panel has two accounts of one microphone, and they can disagree.
 *
 * The service's account comes from audio it has actually received. The local
 * capture store's, in the desktop shell, is a **snapshot** taken when this
 * screen mounted — the store re-reads the shell's session on mount and never
 * again. So a panel that mounted before the recording started, or whose read
 * raced it, stays wrong for the rest of the meeting.
 *
 * Nothing about that is visible. The bar reads "Listening…" from the service's
 * account while the store believes it holds nothing, so the waveform draws
 * empty and the Pause button — offered only where there is something local to
 * pause — is simply absent. An operator reported exactly that: a pill with a
 * running clock, a Stop button, and no Pause and no wave, with no state on
 * screen that explains why.
 *
 * These drive the panel with a fake store so the disagreement can be created
 * on purpose. It could not be before: the panel reached for the module
 * singleton, so the one state that mattered was the one no test could set up.
 */
function fakeStore(initial: Partial<CaptureSnapshot> = {}): CaptureStore & {
  settle: (next: Partial<CaptureSnapshot>) => void;
  refreshes: () => number;
} {
  let snapshot: CaptureSnapshot = {
    status: IDLE,
    sources: [],
    blockedReason: null,
    error: null,
    elapsedSeconds: 0,
    level: null,
    levelUnmeasurable: false,
    waveform: [],
    uploadNote: null,
    ...initial,
  };
  const listeners = new Set<() => void>();
  let refreshes = 0;
  const publish = (next: Partial<CaptureSnapshot>) => {
    snapshot = { ...snapshot, ...next };
    listeners.forEach((listener) => listener());
  };

  return {
    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    getSnapshot: () => snapshot,
    refresh: async () => {
      refreshes += 1;
    },
    check: async () => {},
    beginRecording: async () => {},
    start: async () => {},
    pause: vi.fn(async () => {}),
    resume: async () => {},
    stop: async () => {},
    settle: publish,
    refreshes: () => refreshes,
  } as unknown as CaptureStore & {
    settle: (next: Partial<CaptureSnapshot>) => void;
    refreshes: () => number;
  };
}

/** The same shape every other panel test uses to drive the stream. */
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

/** A stream that reports a meeting whose audio is (or is not) arriving. */
function laneSaying(receiving: boolean): FakeSource {
  const source = new FakeSource();
  queueMicrotask(() =>
    source.emit(
      'lane',
      JSON.stringify({
        model_reachable: true,
        reason: null,
        live_transcription: true,
        live_model: 'nova-3',
        receiving_audio: receiving,
        capturing_since: receiving ? Date.now() - 60_000 : null,
      }),
    ),
  );
  return source;
}

const MEETING = { meetingId: 'meeting-1', active: null, history: [], coverage: null, languages: [] };

describe('the panel and the microphone it reports on', () => {
  it('asks the shell again when the service hears audio it does not know about', async () => {
    // The whole bug. The store's mount-time read said idle; the service says
    // chunks are arriving. Only one of those can be re-read, so it is.
    const store = fakeStore();
    render(
      <OperatorPanel initial={MEETING} createSource={() => laneSaying(true) as never} captureStore={store} />,
    );

    // Once on mount from `useCapture` itself, and again because the two
    // accounts disagree.
    await waitFor(() => expect(store.refreshes()).toBeGreaterThan(1));
  });

  it('offers Pause as soon as the shell settles the question', async () => {
    const store = fakeStore();
    render(
      <OperatorPanel initial={MEETING} createSource={() => laneSaying(true) as never} captureStore={store} />,
    );

    await waitFor(() => expect(store.refreshes()).toBeGreaterThan(1));
    expect(screen.queryByRole('button', { name: /pause/i })).toBeNull();

    // What the shell answers with: a session it has been holding all along.
    store.settle({
      status: { state: 'capturing', source: null, frames: 900 },
      waveform: [0.2, 0.6, 0.3],
      elapsedSeconds: 61,
    });

    expect(await screen.findByRole('button', { name: /pause/i })).toBeInTheDocument();
  });

  it('draws the wave once it has one, having drawn none while it did not', async () => {
    // Absence is not silence: an empty waveform means this window is not the
    // one holding the device, and a row of flat bars would claim a quiet room.
    const store = fakeStore();
    const { container } = render(
      <OperatorPanel initial={MEETING} createSource={() => laneSaying(true) as never} captureStore={store} />,
    );

    await waitFor(() => expect(store.refreshes()).toBeGreaterThan(1));
    expect(container.querySelector('.capture-bar__wave')).toBeNull();

    store.settle({
      status: { state: 'capturing', source: null, frames: 900 },
      waveform: [0.2, 0.6, 0.3],
    });

    await waitFor(() => expect(container.querySelector('.capture-bar__wave')).not.toBeNull());
  });

  it('does not keep asking once the two accounts agree', async () => {
    // The disagreement is the trigger, not a heartbeat. A panel polling the
    // shell every four seconds for an hour is a cost paid by every meeting to
    // fix a state most of them are never in.
    const store = fakeStore({ status: { state: 'capturing', source: null, frames: 10 } });
    render(
      <OperatorPanel initial={MEETING} createSource={() => laneSaying(true) as never} captureStore={store} />,
    );

    await waitFor(() => expect(screen.getByRole('button', { name: /pause/i })).toBeInTheDocument());
    expect(store.refreshes()).toBe(1);
  });

  it('does not ask in the other direction', async () => {
    // A store holding a device the service has heard nothing from yet is the
    // ordinary first few seconds of a recording, not a contradiction.
    const store = fakeStore({ status: { state: 'capturing', source: null, frames: 2 } });
    render(
      <OperatorPanel initial={MEETING} createSource={() => laneSaying(false) as never} captureStore={store} />,
    );

    await waitFor(() => expect(store.refreshes()).toBe(1));
  });

  it('stops claiming to listen the moment a stop comes back', async () => {
    // The other half of "Stop failed to work". `receiving_audio` is derived
    // from when a chunk last arrived and stays true for the freshness window
    // after the last one, so a stop that worked left the bar reading
    // "Listening…" with the clock running for several seconds — which is
    // exactly what a stop that did nothing looks like. This screen released
    // the device itself and knows better than the derivation does.
    const store = fakeStore({ status: { state: 'capturing', source: null, frames: 10 } });
    const fetchImpl = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        session_id: 'session-1',
        meeting_id: 'meeting-1',
        stopped_at: '2026-09-03T02:00:00Z',
      }),
    });
    vi.stubGlobal('fetch', fetchImpl);

    render(
      <OperatorPanel initial={MEETING} createSource={() => laneSaying(true) as never} captureStore={store} />,
    );
    expect(await screen.findByText('Listening…')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /^stop$/i }));

    // The stream is still saying `receiving_audio: true` throughout.
    expect(await screen.findByText('Not recording')).toBeInTheDocument();
    vi.unstubAllGlobals();
  });
});

describe('the panel never contradicts itself about the microphone', () => {
  /**
   * Two regions on one screen answered the same question differently, and an
   * operator saw both at once: the recording bar read "Listening…" over a
   * running clock while the transcript header beside it read "Not capturing".
   *
   * Neither reading was wrong. The bar preferred the local capture store; the
   * header took the service's `receiving_audio`, which is derived from when a
   * chunk last arrived and so lags both edges. They disagree constantly and
   * legitimately — the mistake was putting both on screen.
   *
   * **Asserted as a property rather than as another example.** The bug was
   * not any one of these combinations; it was that two expressions existed
   * where one belonged, so a case-by-case test would only ever have caught
   * the case somebody thought of. Every combination of the two inputs is
   * enumerated, and the only claim is that the screen agrees with itself.
   */
  const said = (holding: boolean, receiving: boolean) =>
    `store ${holding ? 'holds' : 'idle'} / service ${receiving ? 'hears' : 'silent'}`;

  for (const holding of [true, false]) {
    for (const receiving of [true, false]) {
      it(`agrees with itself when the ${said(holding, receiving)}`, async () => {
        const store = fakeStore(
          holding ? { status: { state: 'capturing', source: null, frames: 4 } } : {},
        );
        render(
          <OperatorPanel
            initial={MEETING}
            createSource={() => laneSaying(receiving) as never}
            captureStore={store}
          />,
        );
        // Let the lane frame land and any reconciliation settle.
        await waitFor(() => expect(store.refreshes()).toBeGreaterThan(0));

        const barSaysListening = screen.queryByText('Listening…') !== null;
        const headerSaysNotCapturing = screen.queryByText('Not capturing') !== null;

        expect(barSaysListening).toBe(!headerSaysNotCapturing);
      });
    }
  }

  it('agrees with itself after a stop, while the service still says it hears', async () => {
    // The lagging edge, and the one an operator reads as "Stop did nothing".
    // The stream goes on reporting `receiving_audio: true` for the whole
    // freshness window after the last chunk.
    const store = fakeStore({ status: { state: 'capturing', source: null, frames: 4 } });
    const fetchImpl = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        session_id: 'session-1',
        meeting_id: 'meeting-1',
        stopped_at: '2026-09-06T02:00:00Z',
      }),
    });
    vi.stubGlobal('fetch', fetchImpl);
    render(
      <OperatorPanel
        initial={MEETING}
        createSource={() => laneSaying(true) as never}
        captureStore={store}
      />,
    );
    expect(await screen.findByText('Listening…')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /^stop$/i }));

    await waitFor(() => expect(screen.queryByText('Listening…')).toBeNull());
    expect(screen.getByText('Not capturing')).toBeInTheDocument();
    vi.unstubAllGlobals();
  });
});

describe('what the store knows reaches the screen', () => {
  /**
   * The gap this closes is the one this project keeps falling into: two
   * halves, each with tests, and nothing asserting they are joined.
   *
   * `captureSession` diagnoses a recording that is uploading nothing and
   * writes the sentence into `uploadNote`; `CaptureBar` renders whatever
   * `note` it is handed. Both were tested. Whether the panel passes one to
   * the other was not — and a recording that uploads nothing is exactly the
   * state where the operator has no other signal, because the transcript
   * being empty looks identical to a quiet room.
   */
  it('shows a store note about a recording that is uploading nothing, once', async () => {
    const store = fakeStore({
      status: { state: 'capturing', source: null, frames: 4 },
      uploadNote:
        'The microphone is delivering complete silence, so this meeting is not being transcribed.',
    });

    render(
      <OperatorPanel
        initial={MEETING}
        createSource={() => laneSaying(true) as never}
        captureStore={store}
      />,
    );

    // Once. Rendered by both the transcript's empty state and the recording
    // bar, the same sentence appeared twice on one screen — which is how the
    // first version of this shipped, and what `findByText` refuses.
    expect(await screen.findByText(/delivering complete silence/i)).toBeInTheDocument();
    expect(screen.getAllByText(/delivering complete silence/i)).toHaveLength(1);
  });

  it('moves the reason to the bar once the transcript has lines in it', async () => {
    // The empty state is gone by then, so the transcript cannot carry it —
    // and a recording that breaks mid-meeting is exactly when it still needs
    // saying.
    const store = fakeStore({
      status: { state: 'capturing', source: null, frames: 4 },
      uploadNote: 'The microphone is delivering complete silence.',
    });

    // Through the stream, not the prop: `transcript` on the initial state is
    // only read for a fixed scene, and a live meeting takes its lines from
    // the session stream — so a prop here would leave the transcript empty
    // and quietly assert the case above instead of this one.
    const source = laneSaying(true);
    render(
      <OperatorPanel
        initial={MEETING}
        createSource={() => source as never}
        captureStore={store}
      />,
    );
    await screen.findByText('Listening…');
    source.emit(
      'utterance',
      JSON.stringify({ seq: 0, text: 'Three fifty a day.', speaker: null, at: 1 }),
    );
    expect(await screen.findByText('Three fifty a day.')).toBeInTheDocument();

    const shown = await screen.findAllByText(/delivering complete silence/i);
    expect(shown).toHaveLength(1);
    expect(shown[0].closest('.capture-bar-dock')).not.toBeNull();
  });

  it('does not attribute a note to a recording this window does not hold', async () => {
    // A second screen has no view of somebody else's upload path, and a note
    // shown there would describe a machine the operator is not sitting at.
    const store = fakeStore({ uploadNote: 'The microphone is delivering complete silence.' });

    render(
      <OperatorPanel
        initial={MEETING}
        createSource={() => laneSaying(true) as never}
        captureStore={store}
      />,
    );
    await waitFor(() => expect(store.refreshes()).toBeGreaterThan(0));

    expect(screen.queryByText(/delivering complete silence/i)).toBeNull();
  });
});
