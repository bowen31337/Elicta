import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { createCaptureStore, type CaptureStore } from '../../../services/captureSession';
import CaptureRoute from '../route';

/**
 * The recording screen, which is now where a meeting actually begins.
 *
 * Consent used to carry the Start button. It booked a session on the service
 * and opened no microphone, so an operator was told a meeting had begun while
 * nothing was listening — and it offered no way to choose an input, because a
 * consent screen cannot show you one working. Both halves moved here: this is
 * the screen with a device list and a level meter on it.
 *
 * The check step is not ceremony. A browser withholds device ids *and* labels
 * until the first permission grant, so a picker drawn before that grant reads
 * "Microphone 1" and is not a choice at all; granting is what fills it in. And
 * the choice is binding — `start` refuses while a session runs on both
 * backends — so before the meeting is the only cheap time to get it right.
 */
const ENGAGEMENTS = {
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
};

const MEETINGS = {
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
};

const GATE = '/api/meetings/meeting-1/consent-gate?engagement_id=eng-1';

function stubService(table: Record<string, unknown>, startRefusal?: string) {
  const written: { path: string; method: string }[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (path: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET';
      if (method === 'POST') {
        written.push({ path, method });
        if (startRefusal !== undefined) {
          return {
            ok: false,
            status: 403,
            json: async () => ({ detail: startRefusal }),
          } as Response;
        }
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
      const body = table[path];
      if (body === undefined) return { ok: false, status: 404, json: async () => null } as Response;
      return { ok: true, status: 200, json: async () => body } as Response;
    }),
  );
  return written;
}

const BASE = {
  '/api/engagements': ENGAGEMENTS,
  '/api/engagements/eng-1/meetings': MEETINGS,
  [GATE]: { status: 'confirmed' },
};

function storeWithMicrophone(): CaptureStore {
  const track = { kind: 'audio', enabled: true, stop: vi.fn() };
  const stream = { getAudioTracks: () => [track], getTracks: () => [track] };
  return createCaptureStore({
    shellAvailable: () => false,
    audioContext: () => null,
    environment: () => ({
      isSecureContext: true,
      mediaDevices: {
        enumerateDevices: async () => [
          { kind: 'audioinput', deviceId: 'mic-1', label: 'Scarlett Solo USB' },
        ],
        getUserMedia: async () => stream,
      },
    }),
  });
}

beforeEach(() => window.localStorage.clear());
afterEach(() => vi.unstubAllGlobals());

const button = (name: RegExp) =>
  screen.getByRole('button', { name }) as HTMLButtonElement;

describe('checking the microphone before the meeting', () => {
  it('opens the input and shows it working, recording nothing', async () => {
    stubService(BASE);
    const store = storeWithMicrophone();
    render(<CaptureRoute store={store} />);

    await userEvent.click(await screen.findByRole('button', { name: /check microphone/i }));

    await waitFor(() => expect(store.getSnapshot().status.state).toBe('checking'));
    // The claim the operator needs to be able to trust before a client meeting.
    expect(screen.getByText(/nothing is being recorded/i)).toBeInTheDocument();
  });

  it('fills in the real device name, which is what the check is for', async () => {
    stubService(BASE);
    render(<CaptureRoute store={storeWithMicrophone()} />);

    await userEvent.click(await screen.findByRole('button', { name: /check microphone/i }));

    expect(await screen.findByText('Scarlett Solo USB')).toBeInTheDocument();
  });

  it('books no meeting merely for checking', async () => {
    const written = stubService(BASE);
    render(<CaptureRoute store={storeWithMicrophone()} />);

    await userEvent.click(await screen.findByRole('button', { name: /check microphone/i }));

    await waitFor(() => expect(screen.getByText(/nothing is being recorded/i)).toBeInTheDocument());
    expect(written).toHaveLength(0);
  });
});

describe('starting the recording', () => {
  it('books the meeting when the recording begins, and not before', async () => {
    const written = stubService(BASE);
    const store = storeWithMicrophone();
    render(<CaptureRoute store={store} />);

    await userEvent.click(await screen.findByRole('button', { name: /start recording/i }));

    await waitFor(() => expect(store.getSnapshot().status.state).toBe('capturing'));
    expect(written).toEqual([
      { path: '/api/meetings/meeting-1/session/start', method: 'POST' },
    ]);
  });

  it('says why in the service’s words when the gate refuses', async () => {
    stubService(BASE, 'consent has not been confirmed for this meeting, so capture cannot begin');
    const store = storeWithMicrophone();
    render(<CaptureRoute store={store} />);

    await userEvent.click(await screen.findByRole('button', { name: /start recording/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/consent has not been confirmed/);
    // Released rather than left open for a meeting that will not happen.
    expect(store.getSnapshot().status.state).toBe('idle');
  });

  it('will not record while consent is outstanding', async () => {
    // Navigating straight here must not get past the gate. The service refuses
    // too, but a screen that lets the operator try and then explains is worse
    // than one that does not offer it.
    const written = stubService({ ...BASE, [GATE]: { status: 'awaiting_confirmation' } });
    render(<CaptureRoute store={storeWithMicrophone()} />);

    await waitFor(() => expect(button(/start recording/i).disabled).toBe(true));
    expect(screen.getByText(/consent/i)).toBeInTheDocument();

    await userEvent.click(button(/start recording/i));
    expect(written).toHaveLength(0);
  });
});
