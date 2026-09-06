import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { useRecordingStart } from '../useRecordingStart';
import { createCaptureStore, type CaptureStore } from '../../../services/captureSession';

/**
 * Beginning a meeting, and saying so when it will not begin.
 *
 * This hook had no tests of its own. It was reachable from one screen with a
 * device picker in front of it, so its failure paths were the ones nobody
 * walked: every caller held a source, a meeting was always selected, and the
 * only way to see `error` was to break something on purpose.
 *
 * That stopped being true when the live panel's recording bar started calling
 * it. The bar has no picker and no engagement context of its own, so it
 * reaches the exact branches the capture screen never did — and the first
 * thing an operator saw from it was Tauri's ``invalid args `sourceId` for
 * command `start_capture` ``, carried faithfully to the screen by the one
 * path here that no test covered.
 *
 * What is asserted is the reporting rather than the recording: whether a
 * refusal reaches the operator in words, and whether a control that cannot
 * work is offered anyway.
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

function stubService(table: Record<string, unknown>) {
  const asked: string[] = [];
  const spy = vi.fn(async (path: string, init?: RequestInit) => {
      asked.push(path);
      if ((init?.method ?? 'GET') === 'POST') {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            session_id: 'session-1',
            meeting_id: 'meeting-1',
            started_at: '2026-09-06T10:00:00Z',
          }),
        } as Response;
      }
      const body = table[path];
      if (body === undefined) return { ok: false, status: 404, json: async () => null } as Response;
      return { ok: true, status: 200, json: async () => body } as Response;
  });
  vi.stubGlobal('fetch', spy);
  return asked;
}

/**
 * Wait until a meeting has actually been resolved.
 *
 * `consentBlocked` is null both before the engagement list arrives and after
 * it says consent is fine, so waiting on it proves nothing. The gate is only
 * fetched once there is a meeting id to fetch it for, so its request is the
 * signal that the hook has one.
 */
async function meetingResolved(asked: string[]) {
  await waitFor(() => expect(asked).toContain(GATE));
}

const CONFIRMED = {
  '/api/engagements': ENGAGEMENTS,
  '/api/engagements/eng-1/meetings': MEETINGS,
  [GATE]: { status: 'confirmed' },
};

/**
 * A store whose device refuses to open.
 *
 * Thrown as a `DOMException`-shaped object, because that is what a browser
 * raises and what `openFailureMessage` translates. A plain `Error` falls
 * through to the generic sentence — correctly, and it would make this test
 * assert the fallback while claiming to assert the translation.
 */
async function refusingStore(name: string): Promise<CaptureStore> {
  const store = createCaptureStore({
    shellAvailable: () => false,
    audioContext: () => null,
    environment: () => ({
      isSecureContext: true,
      mediaDevices: {
        enumerateDevices: async () => [
          { kind: 'audioinput', deviceId: 'mic-1', label: 'Desk microphone' },
        ],
        getUserMedia: async () => {
          throw Object.assign(new Error('refused'), { name });
        },
      },
    }),
  });
  // Listed first, as `useCapture`'s mount effect does on every screen that
  // holds this store. Without it the store refuses before it reaches the
  // device at all — "No microphone is available to record from" — which is a
  // true sentence about a different failure, and would have made these tests
  // assert the wrong branch.
  await store.refresh();
  return store;
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

describe('when the microphone will not open', () => {
  it('reports the device its own words rather than a generic failure', async () => {
    // The device's sentence is the actionable half — "permission denied" and
    // "device in use by another application" send an operator to different
    // places, and "That did not work." sends them nowhere.
    const asked = stubService(CONFIRMED);
    const store = await refusingStore('NotAllowedError');
    const { result } = renderHook(() => useRecordingStart(store));
    await meetingResolved(asked);

    await act(async () => {
      result.current.start();
    });

    await waitFor(() => expect(result.current.error).toMatch(/access was refused/i));
  });

  it('reports a refused check too, which is the other way to meet a device', async () => {
    // This path had no coverage at all: the capture screen's picker calls it
    // on every selection, so it ran constantly and was never asserted.
    stubService(CONFIRMED);
    const store = await refusingStore('NotReadableError');
    const { result } = renderHook(() => useRecordingStart(store));

    await act(async () => {
      result.current.check('mic-1');
    });

    await waitFor(() => expect(result.current.error).toMatch(/in use by another application/i));
  });

  it('stops being busy after a failure, so the control can be pressed again', async () => {
    // A `busy` left set by a failed start disables Start for the rest of the
    // meeting, which is a worse outcome than the failure it is reporting.
    const asked = stubService(CONFIRMED);
    const store = await refusingStore('NotAllowedError');
    const { result } = renderHook(() => useRecordingStart(store));
    await meetingResolved(asked);

    await act(async () => {
      result.current.start();
    });

    await waitFor(() => expect(result.current.busy).toBe(false));
  });
});

describe('when there is no meeting to record', () => {
  it('says so instead of booking nothing', async () => {
    // Reachable from the panel's bar, which offers Start without an
    // engagement picker in front of it. Silence here is a pressed button that
    // does nothing at all — the failure this whole screen keeps producing.
    stubService({ '/api/engagements': { items: [], total: 0 } });
    const store = await refusingStore('NotAllowedError');
    const { result } = renderHook(() => useRecordingStart(store));

    await act(async () => {
      result.current.start();
    });

    await waitFor(() =>
      expect(result.current.error).toBe('No meeting is selected, so there is nothing to record.'),
    );
  });
});

describe('when consent has not been confirmed', () => {
  it('names the reason before anything is pressed', async () => {
    // Answered *before* the press: the service refuses too, but a screen that
    // offers a control, takes the click and then explains is worse than one
    // that does not offer it.
    stubService({ ...CONFIRMED, [GATE]: { status: 'awaiting_confirmation' } });
    const store = await refusingStore('NotAllowedError');
    const { result } = renderHook(() => useRecordingStart(store));

    await waitFor(() => expect(result.current.consentBlocked).toMatch(/consent has not been/i));
  });

  it('holds the gate shut while the answer is unknown', async () => {
    // Absent means unknown, and unknown may not open the gate: a screen that
    // recorded because it could not read the gate would be recording a
    // meeting that may have no consent at all.
    stubService({ '/api/engagements': ENGAGEMENTS, '/api/engagements/eng-1/meetings': MEETINGS });
    const store = await refusingStore('NotAllowedError');
    const { result } = renderHook(() => useRecordingStart(store));

    await waitFor(() => expect(result.current.consentBlocked).toBeNull());
    // Null here means "nothing to say", not "allowed" — the service is the
    // gate that refuses. What must never happen is a *positive* claim that
    // consent is confirmed when nothing answered.
    expect(result.current.error).toBeNull();
  });
});
