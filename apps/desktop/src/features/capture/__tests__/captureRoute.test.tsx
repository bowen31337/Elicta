import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { createCaptureStore } from '../../../services/captureSession';
import CaptureRoute, { CaptureScreen } from '../route';

/**
 * The service, for the half of this screen that books a meeting.
 *
 * Start recording books the meeting now — the meeting begins when the
 * recording does — so these tests need an engagement, a meeting and an open
 * consent gate to reach the device at all.
 */
const GATE = '/api/meetings/meeting-1/consent-gate?engagement_id=eng-1';
const SERVICE: Record<string, unknown> = {
  '/api/engagements': {
    items: [
      {
        engagement_id: 'eng-1',
        client_organisation: 'Northwind Logistics',
        sector: 'Freight',
        commercial_context: 'Discovery',
        purpose: null,
        scope_boundary: null,
        target_requirements_template: null,
      },
    ],
    total: 1,
  },
  '/api/engagements/eng-1/meetings': {
    engagement_id: 'eng-1',
    meetings: [
      {
        meeting_id: 'meeting-1',
        engagement_id: 'eng-1',
        state: 'planned',
        capture_mode: 'monolingual',
        scheduled_at: null,
        session_purpose: 'Discovery 1',
        sections_filled: null,
        sections_total: null,
      },
    ],
  },
  [GATE]: { status: 'confirmed' },
};

function stubService() {
  window.localStorage.clear();
  vi.stubGlobal(
    'fetch',
    vi.fn(async (path: string, init?: RequestInit) => {
      if ((init?.method ?? 'GET') === 'POST') {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            session_id: 'session-1',
            meeting_id: 'meeting-1',
            started_at: '2026-08-23T14:02:00Z',
          }),
        } as Response;
      }
      const body = SERVICE[path];
      if (body === undefined) return { ok: false, status: 404, json: async () => null } as Response;
      return { ok: true, status: 200, json: async () => body } as Response;
    }),
  );
}

/**
 * Capture, in a browser.
 *
 * Running Elicta as a web app, this screen said "Audio capture is unavailable
 * outside the desktop app, so nothing is being recorded" and disabled its only
 * control — for every reason, including the ones the operator could have fixed
 * in ten seconds. It also had no way to *begin* capture at all: `start` existed
 * on the hook and nothing called it, so even with a working microphone there
 * was no control to open it.
 */
const descriptors: { target: object; key: string }[] = [];

function define(target: object, key: string, value: unknown) {
  descriptors.push({ target, key });
  Object.defineProperty(target, key, { value, configurable: true, writable: true });
}

afterEach(() => {
  for (const { target, key } of descriptors.splice(0)) {
    delete (target as Record<string, unknown>)[key];
  }
  vi.restoreAllMocks();
});

function track() {
  return { kind: 'audio', enabled: true, stopped: false, stop() { this.stopped = true; } };
}

function browserWithMicrophone(tracks = [track()]) {
  stubService();
  const getUserMedia = vi.fn(async (_constraints: unknown) => ({
    getAudioTracks: () => tracks,
    getTracks: () => tracks,
  }));
  define(window, 'isSecureContext', true);
  define(navigator, 'mediaDevices', {
    enumerateDevices: async () => [
      { kind: 'audioinput', deviceId: 'mic-1', label: 'Built-in Microphone' },
      { kind: 'videoinput', deviceId: 'cam-1', label: 'Webcam' },
    ],
    getUserMedia,
  });
  return { getUserMedia, tracks };
}

describe('a page the browser will not let near a microphone', () => {
  it('names the insecure page instead of blaming the desktop app', async () => {
    define(window, 'isSecureContext', false);
    define(navigator, 'mediaDevices', undefined);
    render(<CaptureRoute store={createCaptureStore()} />);

    const warning = await screen.findByText(/secure page/i);
    expect(warning).toBeInTheDocument();
    expect(screen.queryByText(/unavailable outside the desktop app/i)).not.toBeInTheDocument();
  });
});

describe('a browser that can reach a microphone', () => {
  it('lists the microphone rather than reporting no input at all', async () => {
    browserWithMicrophone();
    render(<CaptureRoute store={createCaptureStore()} />);

    expect(await screen.findByText('Built-in Microphone')).toBeInTheDocument();
    expect(screen.queryByText('Webcam')).not.toBeInTheDocument();
  });

  it('does not claim capture is unavailable', async () => {
    browserWithMicrophone();
    render(<CaptureRoute store={createCaptureStore()} />);

    await screen.findByText('Built-in Microphone');
    expect(screen.queryByText(/unavailable outside the desktop app/i)).not.toBeInTheDocument();
  });

  /** `start` existed on the hook and nothing ever called it. */
  it('offers a control that actually opens the microphone', async () => {
    const { getUserMedia } = browserWithMicrophone();
    render(<CaptureRoute store={createCaptureStore()} />);

    await userEvent.click(await screen.findByRole('button', { name: /start recording/i }));

    await waitFor(() => expect(getUserMedia).toHaveBeenCalledTimes(1));
    const constraints = getUserMedia.mock.calls[0][0] as { audio: Record<string, unknown> };
    expect(constraints.audio.echoCancellation).toBe(false);
  });

  it('says it is recording once the microphone is open', async () => {
    browserWithMicrophone();
    render(<CaptureRoute store={createCaptureStore()} />);

    await userEvent.click(await screen.findByRole('button', { name: /start recording/i }));

    expect(await screen.findByRole('heading', { name: 'Recording' })).toBeInTheDocument();
  });

  it('silences the microphone on pause without releasing it', async () => {
    const { tracks } = browserWithMicrophone();
    render(<CaptureRoute store={createCaptureStore()} />);

    await userEvent.click(await screen.findByRole('button', { name: /start recording/i }));
    await userEvent.click(await screen.findByRole('button', { name: /pause recording/i }));

    await waitFor(() => expect(tracks[0].enabled).toBe(false));
    expect(tracks[0].stopped).toBe(false);
    expect(await screen.findByRole('heading', { name: 'Paused' })).toBeInTheDocument();
  });

  it('releases the microphone on stop', async () => {
    const { tracks } = browserWithMicrophone();
    render(<CaptureRoute store={createCaptureStore()} />);

    await userEvent.click(await screen.findByRole('button', { name: /start recording/i }));
    await userEvent.click(await screen.findByRole('button', { name: /stop recording/i }));

    await waitFor(() => expect(tracks[0].stopped).toBe(true));
  });

  it('shows a refused permission in words the operator can act on', async () => {
    define(window, 'isSecureContext', true);
    define(navigator, 'mediaDevices', {
      enumerateDevices: async () => [
        { kind: 'audioinput', deviceId: 'mic-1', label: 'Built-in Microphone' },
      ],
      getUserMedia: async () => {
        throw Object.assign(new Error('denied'), { name: 'NotAllowedError' });
      },
    });
    render(<CaptureRoute store={createCaptureStore()} />);

    await userEvent.click(await screen.findByRole('button', { name: /start recording/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/refused/i);
  });
});

describe('the recording clock on screen', () => {
  it('shows the recording running rather than a frozen 00:00', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      browserWithMicrophone();
      render(<CaptureRoute store={createCaptureStore()} />);

      await userEvent.click(await screen.findByRole('button', { name: /start recording/i }));
      await waitFor(() =>
        expect(screen.getByRole('button', { name: /stop recording/i })).toBeInTheDocument(),
      );

      await vi.advanceTimersByTimeAsync(4_000);

      await waitFor(() => expect(screen.getByText('00:04')).toBeInTheDocument());
      expect(screen.queryByText('00:00')).not.toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });
});

/**
 * The level meter.
 *
 * This screen could say "Recording" for forty minutes over a muted input and
 * look identical to one that was working. The meter is the only thing that
 * distinguishes them, which makes it a safety feature of the same family as
 * the pause banner rather than a decoration.
 */
describe('the level meter', () => {
  const SOURCES = [
    { label: 'Built-in Microphone', kind: 'acoustic' as const, active: true },
  ];

  function screenWith(overrides: Record<string, unknown>) {
    return (
      <CaptureScreen
        state="capturing"
        elapsed="04:12"
        sources={SOURCES}
        operatorEnrolled={false}
        enrolmentSeconds={0}
        {...overrides}
      />
    );
  }

  it('shows how loud the input is while recording', () => {
    render(
      screenWith({
        metering: { level: { rms: 0.05, peak: 0.2 }, waveform: [0.1, 0.4, 0.9] },
      }),
    );

    const meter = screen.getByRole('meter', { name: /input level/i });

    expect(meter).toHaveAttribute('aria-valuenow');
    expect(Number(meter.getAttribute('aria-valuenow'))).toBeGreaterThan(0);
  });

  it('names the device the reading belongs to', () => {
    render(
      screenWith({
        metering: { level: { rms: 0.05, peak: 0.2 }, waveform: [0.3] },
      }),
    );

    expect(screen.getByText('Built-in Microphone', { selector: '.capture-meter-device' }))
      .toBeInTheDocument();
  });

  it('says the reading is one mixed stream, not one person', () => {
    // The screen must not imply a separation the audio does not contain:
    // getUserMedia opens a single device, and speaker attribution happens on
    // finalised transcript text, seconds later.
    render(
      screenWith({ metering: { level: { rms: 0.05, peak: 0.2 }, waveform: [0.3] } }),
    );

    expect(screen.getByText(/one mixed stream/i)).toBeInTheDocument();
  });

  it('reads a flat zero when paused, so the meter confirms the pause', () => {
    render(
      screenWith({
        state: 'paused',
        metering: { level: { rms: 0, peak: 0 }, waveform: [0, 0, 0] },
      }),
    );

    expect(screen.getByRole('meter', { name: /input level/i }))
      .toHaveAttribute('aria-valuenow', '0');
  });

  it('shows a dash rather than a number for digital silence', () => {
    render(
      screenWith({ state: 'paused', metering: { level: { rms: 0, peak: 0 }, waveform: [0] } }),
    );

    expect(screen.getByText('—', { selector: '.capture-meter-db' })).toBeInTheDocument();
  });

  it('shows no meter at all when nothing is recording', () => {
    render(screenWith({ state: 'stopped' }));

    expect(screen.queryByRole('meter')).not.toBeInTheDocument();
  });

  it('says so when the browser cannot measure a level, rather than drawing a zero', () => {
    // A meter stuck at zero reads as "the room is silent", which is a finding
    // an operator would act on. Absence of a reading is a different claim.
    render(screenWith({ metering: { level: null, waveform: [], unmeasurable: true } }));

    expect(screen.queryByRole('meter')).not.toBeInTheDocument();
    expect(screen.getByText(/cannot measure/i)).toBeInTheDocument();
  });

  it('draws nothing extra for a scene that was given no meter', () => {
    // The journey scenes render fixed props with no hook behind them. Absent
    // metering must not read as "this browser cannot measure".
    render(screenWith({}));

    expect(screen.queryByRole('meter')).not.toBeInTheDocument();
    expect(screen.queryByText(/cannot measure/i)).not.toBeInTheDocument();
  });
});
