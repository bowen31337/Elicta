import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import CaptureRoute from '../route';

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
    render(<CaptureRoute />);

    const warning = await screen.findByText(/secure page/i);
    expect(warning).toBeInTheDocument();
    expect(screen.queryByText(/unavailable outside the desktop app/i)).not.toBeInTheDocument();
  });
});

describe('a browser that can reach a microphone', () => {
  it('lists the microphone rather than reporting no input at all', async () => {
    browserWithMicrophone();
    render(<CaptureRoute />);

    expect(await screen.findByText('Built-in Microphone')).toBeInTheDocument();
    expect(screen.queryByText('Webcam')).not.toBeInTheDocument();
  });

  it('does not claim capture is unavailable', async () => {
    browserWithMicrophone();
    render(<CaptureRoute />);

    await screen.findByText('Built-in Microphone');
    expect(screen.queryByText(/unavailable outside the desktop app/i)).not.toBeInTheDocument();
  });

  /** `start` existed on the hook and nothing ever called it. */
  it('offers a control that actually opens the microphone', async () => {
    const { getUserMedia } = browserWithMicrophone();
    render(<CaptureRoute />);

    await userEvent.click(await screen.findByRole('button', { name: /start recording/i }));

    await waitFor(() => expect(getUserMedia).toHaveBeenCalledTimes(1));
    const constraints = getUserMedia.mock.calls[0][0] as { audio: Record<string, unknown> };
    expect(constraints.audio.echoCancellation).toBe(false);
  });

  it('says it is recording once the microphone is open', async () => {
    browserWithMicrophone();
    render(<CaptureRoute />);

    await userEvent.click(await screen.findByRole('button', { name: /start recording/i }));

    expect(await screen.findByRole('heading', { name: 'Recording' })).toBeInTheDocument();
  });

  it('silences the microphone on pause without releasing it', async () => {
    const { tracks } = browserWithMicrophone();
    render(<CaptureRoute />);

    await userEvent.click(await screen.findByRole('button', { name: /start recording/i }));
    await userEvent.click(await screen.findByRole('button', { name: /pause recording/i }));

    await waitFor(() => expect(tracks[0].enabled).toBe(false));
    expect(tracks[0].stopped).toBe(false);
    expect(await screen.findByRole('heading', { name: 'Paused' })).toBeInTheDocument();
  });

  it('releases the microphone on stop', async () => {
    const { tracks } = browserWithMicrophone();
    render(<CaptureRoute />);

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
    render(<CaptureRoute />);

    await userEvent.click(await screen.findByRole('button', { name: /start recording/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/refused/i);
  });
});

describe('the recording clock on screen', () => {
  it('shows the recording running rather than a frozen 00:00', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      browserWithMicrophone();
      render(<CaptureRoute />);

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
