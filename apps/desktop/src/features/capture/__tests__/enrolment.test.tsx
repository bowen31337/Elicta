import { act, render, renderHook, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { CaptureScreen, type CaptureEnrolment } from '../route';
import { TARGET_SAMPLE_RATE } from '../pcm';
import type { PcmContextLike, ScriptProcessorLike } from '../pcmTap';
import { useEnrolment, type EnrolmentStatus } from '../useEnrolment';

/**
 * Enrolling the operator's voice (PRD FR-1.5).
 *
 * The section this covers was chrome for the life of the product: the screen
 * hardcoded "Not enrolled" and the button carried no handler, so pressing it
 * did nothing and no amount of enrolling ever changed the words above it.
 * These tests are about the two halves of fixing that — a screen that reports
 * what the service actually says, and a hook that records a capped sample and
 * sends it — and about the claims the screen is allowed to make while it does.
 */

const NOT_ENROLLED: EnrolmentStatus = {
  enrolled: false,
  sample_seconds: null,
  embedding_model: null,
  enrolled_at: null,
  max_sample_seconds: 60,
  min_sample_seconds: 3,
  usable: false,
};

const ENROLLED: EnrolmentStatus = {
  enrolled: true,
  sample_seconds: 48,
  embedding_model: 'mfcc-stats-v1',
  enrolled_at: '2026-08-23T10:30:00Z',
  max_sample_seconds: 60,
  min_sample_seconds: 3,
  usable: true,
};

function enrolment(over: Partial<CaptureEnrolment> = {}): CaptureEnrolment {
  return {
    phase: 'idle',
    seconds: 0,
    maxSeconds: 60,
    minSeconds: 3,
    usable: true,
    ...over,
  };
}

// --- the screen ----------------------------------------------------------

describe('the "Your voice" section', () => {
  it('offers to enrol, and the button is live', async () => {
    const onStart = vi.fn();
    render(
      <CaptureScreen
        state="stopped"
        sources={[]}
        elapsed="00:00"
        operatorEnrolled={false}
        enrolmentSeconds={0}
        enrolment={enrolment({ onStart })}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: 'Enrol' }));

    expect(onStart).toHaveBeenCalledOnce();
  });

  it('counts the sample out loud while it records, and offers to discard it', () => {
    render(
      <CaptureScreen
        state="stopped"
        sources={[]}
        elapsed="00:00"
        operatorEnrolled={false}
        enrolmentSeconds={0}
        enrolment={enrolment({ phase: 'recording', seconds: 12 })}
      />,
    );

    expect(screen.getByText(/12s of 60s/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Stop' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Discard' })).toBeInTheDocument();
  });

  it('says how much more is needed while the sample is still too short', () => {
    render(
      <CaptureScreen
        state="stopped"
        sources={[]}
        elapsed="00:00"
        operatorEnrolled={false}
        enrolmentSeconds={0}
        enrolment={enrolment({ phase: 'recording', seconds: 1 })}
      />,
    );

    expect(screen.getByText(/at least 3s is needed/i)).toBeInTheDocument();
  });

  it('never claims to identify the operator, only to tell voices apart', () => {
    /* The recogniser is a baseline built from the shape of a voice, not the
       learned speaker model the design calls for. An operator told it
       "identifies you" would trust a tag it has not earned. */
    render(
      <CaptureScreen
        state="stopped"
        sources={[]}
        elapsed="00:00"
        operatorEnrolled
        enrolmentSeconds={48}
        enrolment={enrolment()}
      />,
    );

    const claim = screen.getByText(/built-in baseline/i);
    expect(claim.textContent).toMatch(/two similar voices it may not/i);
  });

  it('says so when an enrolment exists and verifies nothing', () => {
    /* Enrolled and useless reads as working on every other line of the
       section, so it has to be said outright. */
    render(
      <CaptureScreen
        state="stopped"
        sources={[]}
        elapsed="00:00"
        operatorEnrolled
        enrolmentSeconds={48}
        enrolment={enrolment({ usable: false })}
      />,
    );

    expect(screen.getByText(/no longer running/i)).toBeInTheDocument();
  });

  it('does not repeat a warning the screen has already given once', () => {
    /* What stops an enrolment is almost always what stops the recording, and
       the screen has explained that at the top. Saying it again beside the
       button reads as a second, different problem. */
    const blocked = 'The browser only allows microphone access on a secure page.';
    render(
      <CaptureScreen
        state="stopped"
        sources={[]}
        elapsed="00:00"
        operatorEnrolled={false}
        enrolmentSeconds={0}
        unavailableReason={blocked}
        enrolment={enrolment({ blockedReason: blocked })}
      />,
    );

    expect(screen.getAllByText(blocked)).toHaveLength(1);
  });

  it('offers the inputs to record a voice sample from, and enrols on the chosen one', async () => {
    /* The meeting's input and the operator's are different choices: the
       meeting wants the cleanest feed of the room, enrolling wants whatever is
       nearest the operator's mouth. */
    const onStart = vi.fn();
    render(
      <CaptureScreen
        state="stopped"
        sources={[
          { id: 'built-in', label: 'Built-in microphone', kind: 'acoustic', active: false },
          { id: 'headset', label: 'USB headset', kind: 'wired', active: true },
        ]}
        elapsed="00:00"
        operatorEnrolled={false}
        enrolmentSeconds={0}
        enrolment={enrolment({ onStart })}
      />,
    );

    await userEvent.selectOptions(screen.getByLabelText('Record from'), '1');
    await userEvent.click(screen.getByRole('button', { name: 'Enrol' }));

    expect(onStart).toHaveBeenCalledWith('headset');
  });

  it('does not inherit the input the meeting is being recorded on', async () => {
    /* Inheriting it would move enrolment onto the room microphone by default —
       the worst input for the one recording where a single voice is the whole
       point. */
    const onStart = vi.fn();
    render(
      <CaptureScreen
        state="stopped"
        sources={[
          { id: 'built-in', label: 'Built-in microphone', kind: 'acoustic', active: false },
          { id: 'desk-feed', label: 'Line-in from the meeting machine', kind: 'wired', active: true },
        ]}
        elapsed="00:00"
        operatorEnrolled={false}
        enrolmentSeconds={0}
        enrolment={enrolment({ onStart })}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: 'Enrol' }));

    expect(onStart).toHaveBeenCalledWith('built-in');
  });

  it('asks for the default microphone when the browser will not name its inputs', async () => {
    /* Before the first permission grant every device id is the empty string,
       which `openBrowserCapture` reads as "the default microphone". Pinning a
       placeholder id instead fails with NotFoundError every time. */
    const onStart = vi.fn();
    render(
      <CaptureScreen
        state="stopped"
        sources={[
          { id: '', label: 'Microphone 1', kind: 'acoustic', active: false },
          { id: '', label: 'Microphone 2', kind: 'acoustic', active: false },
        ]}
        elapsed="00:00"
        operatorEnrolled={false}
        enrolmentSeconds={0}
        enrolment={enrolment({ onStart })}
      />,
    );

    await userEvent.selectOptions(screen.getByLabelText('Record from'), '1');
    await userEvent.click(screen.getByRole('button', { name: 'Enrol' }));

    expect(onStart).toHaveBeenCalledWith('');
  });

  it('offers no choice when there is only one input', () => {
    /* A select holding a single option is a control that looks like it does
       something. */
    render(
      <CaptureScreen
        state="stopped"
        sources={[{ id: 'built-in', label: 'Built-in microphone', kind: 'acoustic', active: true }]}
        elapsed="00:00"
        operatorEnrolled={false}
        enrolmentSeconds={0}
        enrolment={enrolment()}
      />,
    );

    expect(screen.queryByLabelText('Record from')).not.toBeInTheDocument();
  });

  it('will not let the input be changed mid-recording', () => {
    render(
      <CaptureScreen
        state="stopped"
        sources={[
          { id: 'built-in', label: 'Built-in microphone', kind: 'acoustic', active: false },
          { id: 'headset', label: 'USB headset', kind: 'wired', active: true },
        ]}
        elapsed="00:00"
        operatorEnrolled={false}
        enrolmentSeconds={0}
        enrolment={enrolment({ phase: 'recording', seconds: 4 })}
      />,
    );

    expect(screen.getByLabelText('Record from')).toBeDisabled();
  });

  it('leaves the button inert on a render with no enrolment control', () => {
    /* The fixed journey scenes render this section as a picture and must
       never open a microphone to do it. */
    render(
      <CaptureScreen
        state="stopped"
        sources={[]}
        elapsed="00:00"
        operatorEnrolled
        enrolmentSeconds={48}
      />,
    );

    expect(screen.getByRole('button', { name: 'Re-record' })).toBeDisabled();
  });
});

// --- the hook ------------------------------------------------------------

/** An `AudioContext` that hands back the samples the test decides to emit. */
function fakeAudio() {
  let processor: ScriptProcessorLike | null = null;
  const node = () => ({ connect: () => {}, disconnect: () => {} });

  const context: PcmContextLike = {
    // Already at the target rate, so the resampler is a pass-through and the
    // sample counts in these tests are the ones the hook actually holds.
    sampleRate: TARGET_SAMPLE_RATE,
    destination: {},
    createMediaStreamSource: () => node(),
    createScriptProcessor: () => {
      processor = Object.assign(node(), {
        onaudioprocess: null as ScriptProcessorLike['onaudioprocess'],
      });
      return processor;
    },
    createGain: () => Object.assign(node(), { gain: { value: 1 } }),
    close: async () => {},
  };

  return {
    context,
    /** Emits `samples` frames of audible tone from the microphone. */
    emit(samples: number) {
      const frame = new Float32Array(samples).fill(0.4);
      processor?.onaudioprocess?.({ inputBuffer: { getChannelData: () => frame } });
    },
  };
}

function fakeMedia(stopped: { count: number }) {
  const track = {
    kind: 'audio',
    enabled: true,
    stop: () => (stopped.count += 1),
    getSettings: () => ({ deviceId: 'mic-1' }),
  };
  return {
    enumerateDevices: async () => [],
    getUserMedia: async () => ({ getAudioTracks: () => [track], getTracks: () => [track] }),
  };
}

function harness(over: { status?: EnrolmentStatus; post?: () => Response } = {}) {
  const audio = fakeAudio();
  const stopped = { count: 0 };
  const posted: string[] = [];

  const fetchImpl = (async (_path: string, init?: RequestInit) => {
    if (init?.method === 'POST') {
      posted.push(String(init.body));
      return (
        over.post?.() ??
        new Response(JSON.stringify({ ...ENROLLED, sample_seconds: 5 }), { status: 201 })
      );
    }
    return new Response(JSON.stringify(over.status ?? NOT_ENROLLED), { status: 200 });
  }) as unknown as typeof fetch;

  return {
    audio,
    stopped,
    posted,
    deps: {
      environment: () => ({ isSecureContext: true, mediaDevices: fakeMedia(stopped) }),
      pcmContext: () => () => audio.context,
      fetch: fetchImpl,
    },
  };
}

describe('recording a voice sample', () => {
  it('reads the enrolment the service already holds', async () => {
    const { deps } = harness({ status: ENROLLED });

    const { result } = renderHook(() => useEnrolment(deps));

    await waitFor(() => expect(result.current.status?.enrolled).toBe(true));
    expect(result.current.status?.sample_seconds).toBe(48);
  });

  it('sends what was recorded and takes the new status from the answer', async () => {
    const { deps, audio, posted } = harness();
    const { result } = renderHook(() => useEnrolment(deps));
    await waitFor(() => expect(result.current.status).not.toBeNull());

    act(() => result.current.start());
    await waitFor(() => expect(result.current.phase).toBe('recording'));
    act(() => audio.emit(TARGET_SAMPLE_RATE * 5));
    act(() => result.current.stop());

    await waitFor(() => expect(posted).toHaveLength(1));
    expect(JSON.parse(posted[0]).pcm).toBeTypeOf('string');
    await waitFor(() => expect(result.current.status?.enrolled).toBe(true));
  });

  it('releases the microphone once the sample is sent', async () => {
    /* A device left open keeps the browser's recording indicator lit with
       nothing behind it, on a screen whose whole job is being unambiguous
       about whether anything is recording. */
    const { deps, audio, stopped } = harness();
    const { result } = renderHook(() => useEnrolment(deps));

    act(() => result.current.start());
    await waitFor(() => expect(result.current.phase).toBe('recording'));
    act(() => audio.emit(TARGET_SAMPLE_RATE * 4));
    act(() => result.current.stop());

    await waitFor(() => expect(stopped.count).toBe(1));
  });

  it('keeps no more than the cap however much audio arrives', async () => {
    /* FR-1.5 caps the sample at sixty seconds. The cap is enforced on the
       samples themselves rather than on a timer, because a throttled tab
       fires timers late and would send more than a minute. */
    const { deps, audio, posted } = harness();
    const { result } = renderHook(() => useEnrolment(deps));
    await waitFor(() => expect(result.current.status).not.toBeNull());

    act(() => result.current.start());
    await waitFor(() => expect(result.current.phase).toBe('recording'));
    act(() => audio.emit(TARGET_SAMPLE_RATE * 90));
    act(() => result.current.stop());

    await waitFor(() => expect(posted).toHaveLength(1));
    // base64 of 60s of 16-bit samples at 16kHz, and not a byte more.
    const bytes = (JSON.parse(posted[0]).pcm.length * 3) / 4;
    expect(bytes).toBe(TARGET_SAMPLE_RATE * 60 * 2);
  });

  it('discards a recording without sending it', async () => {
    const { deps, audio, posted, stopped } = harness();
    const { result } = renderHook(() => useEnrolment(deps));

    act(() => result.current.start());
    await waitFor(() => expect(result.current.phase).toBe('recording'));
    act(() => audio.emit(TARGET_SAMPLE_RATE * 5));
    act(() => result.current.cancel());

    expect(posted).toEqual([]);
    expect(stopped.count).toBe(1);
    expect(result.current.phase).toBe('idle');
  });

  it('shows the service’s own reason when a sample is refused', async () => {
    /* The service writes that message for the operator — "that recording held
       no speech" — and replacing it with a status code loses the only part
       they can act on. */
    const { deps, audio } = harness({
      post: () =>
        new Response(JSON.stringify({ detail: 'That recording held no speech.' }), {
          status: 422,
        }),
    });
    const { result } = renderHook(() => useEnrolment(deps));
    await waitFor(() => expect(result.current.status).not.toBeNull());

    act(() => result.current.start());
    await waitFor(() => expect(result.current.phase).toBe('recording'));
    act(() => audio.emit(TARGET_SAMPLE_RATE * 4));
    act(() => result.current.stop());

    await waitFor(() => expect(result.current.error).toBe('That recording held no speech.'));
  });

  it('refuses to start on a page that cannot reach a microphone', async () => {
    const { deps } = harness();
    const { result } = renderHook(() =>
      useEnrolment({ ...deps, environment: () => ({ isSecureContext: false, mediaDevices: undefined }) }),
    );

    act(() => result.current.start());

    expect(result.current.phase).toBe('idle');
    expect(result.current.blockedReason).toMatch(/secure page/i);
  });
});
