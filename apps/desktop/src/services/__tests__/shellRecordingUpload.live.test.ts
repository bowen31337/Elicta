import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';

import { createCaptureStore } from '../captureSession';

/**
 * Does a desktop recording actually reach the service?
 *
 * Nothing answered this. The upload path was unit-tested piece by piece and
 * joined only at runtime, and the one journey that joins it —
 * `audio-upload.mjs` — drives the *browser* path through `getUserMedia`. The
 * shell path is different code: Rust normalises the audio and emits it as
 * `capture://pcm`, and the store feeds that to the bridge.
 *
 * This drives that path for real: the real bridge, the real chunk uploader,
 * the real consent gate, real `fetch` against a running service. The only
 * stubbed part is the Tauri event itself, which is the one hop already proven
 * to work — `service://ready` reaches the webview in the signed bundle, which
 * is what fixed the cold start.
 *
 * Skips when no service is listening, the same way the journeys do.
 */
const SERVICE = 'http://127.0.0.1:8000';
const MEETING = 'meeting-2';
const ENGAGEMENT = 'eng-1';

let live = false;

beforeAll(async () => {
  live = await fetch(`${SERVICE}/openapi.json`)
    .then((r) => r.ok)
    .catch(() => false);
});

function pcmBase64(sampleCount: number): string {
  const bytes = new Uint8Array(sampleCount * 2);
  for (let i = 0; i < sampleCount; i += 1) {
    // Something audible rather than silence, so a service that inspected the
    // samples would see speech-shaped data rather than a flat line.
    const value = Math.round(Math.sin(i / 8) * 8000);
    bytes[i * 2] = value & 0xff;
    bytes[i * 2 + 1] = (value >> 8) & 0xff;
  }
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

describe('a desktop recording, end to end against a running service', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    window.localStorage.clear();
  });

  it('sends the audio the shell emits to the service', async () => {
    if (!live) {
      console.warn('no service on 127.0.0.1:8000 — skipping the live upload check');
      return;
    }

    // The shell is what makes `apiUrl()` name the service instead of using a
    // relative path there is no dev-server proxy for here.
    vi.stubGlobal('window', window);
    (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__ = {};
    window.localStorage.setItem('elicta.selection.meetingId', MEETING);
    window.localStorage.setItem('elicta.selection.engagementId', ENGAGEMENT);

    const seen: { url: string; method: string; status: number }[] = [];
    const realFetch = globalThis.fetch.bind(globalThis);
    vi.stubGlobal('fetch', async (input: RequestInfo | URL, init?: RequestInit) => {
      const response = await realFetch(input, init);
      seen.push({
        url: String(input),
        method: (init?.method ?? 'GET').toUpperCase(),
        status: response.status,
      });
      return response;
    });

    const emit: Record<string, (payload: unknown) => void> = {};
    const store = createCaptureStore({
      shellAvailable: () => true,
      environment: () => ({ isSecureContext: true, mediaDevices: undefined }),
      audioContext: () => null,
      invoke: (async (command: string) =>
        command === 'start_capture'
          ? { state: 'capturing', source: null, frames: 0 }
          : command === 'list_audio_sources'
            ? []
            : null) as never,
      listen: async (name: string, handler: (event: { payload: unknown }) => void) => {
        emit[name] = (payload) => handler({ payload });
        return () => undefined;
      },
      // No createBridge override: the real one, talking to the real service.
    });

    await store.refresh();
    await store.beginRecording();
    expect(store.getSnapshot().uploadNote).toBeNull();

    for (let sequence = 1; sequence <= 4; sequence += 1) {
      emit['capture://pcm']?.({ sequence, pcm: pcmBase64(4000) });
    }
    // Stop flushes the tail, which is what sends a recording shorter than one
    // whole chunk — the ordinary case for a short check.
    await store.stop();

    const recordingOpened = seen.filter(
      (call) => call.method === 'POST' && call.url.includes('/recording'),
    );
    const chunks = seen.filter(
      (call) => call.method === 'POST' && call.url.includes('/audio-chunk'),
    );

    expect(recordingOpened.length, 'the recording was never opened').toBeGreaterThan(0);
    expect(recordingOpened.every((c) => c.status < 400)).toBe(true);
    expect(chunks.length, 'no audio chunk was ever posted').toBeGreaterThan(0);
    expect(chunks.every((c) => c.status < 400)).toBe(true);
  }, 30000);
});
