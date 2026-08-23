import { describe, expect, it, vi } from 'vitest';

import {
  browserCaptureBlockedReason,
  listBrowserSources,
  openBrowserCapture,
} from '../browserCapture';

/**
 * Capture in a browser.
 *
 * The screen said "Audio capture is unavailable outside the desktop app" for
 * every case, which collapsed four different situations into one sentence: no
 * Tauri shell, a page served over plain HTTP (where the browser withholds
 * `mediaDevices` entirely), a refused permission prompt, and a machine with no
 * microphone. Only the first of those is about the desktop app, and only the
 * operator can fix the other three — so each has to say which one it is.
 */
function fakeTrack(kind = 'audio') {
  return { kind, enabled: true, stopped: false, stop() { this.stopped = true; } };
}

function fakeMediaDevices(devices: unknown[], tracks = [fakeTrack()]) {
  return {
    enumerateDevices: vi.fn(async () => devices),
    getUserMedia: vi.fn(async (_constraints: unknown) => ({
      getAudioTracks: () => tracks,
      getTracks: () => tracks,
    })),
  };
}

describe('why capture is blocked', () => {
  it('names the insecure page rather than blaming the desktop app', () => {
    const reason = browserCaptureBlockedReason({ isSecureContext: false, mediaDevices: undefined });

    expect(reason).toMatch(/secure/i);
    expect(reason).toMatch(/https|localhost/i);
    expect(reason).not.toMatch(/desktop app/i);
  });

  it('says the browser offers no microphone access when the page is secure but the API is absent', () => {
    const reason = browserCaptureBlockedReason({ isSecureContext: true, mediaDevices: undefined });

    expect(reason).toMatch(/browser/i);
    expect(reason).not.toMatch(/secure/i);
  });

  it('reports nothing blocking when the browser can reach a microphone', () => {
    const reason = browserCaptureBlockedReason({
      isSecureContext: true,
      mediaDevices: fakeMediaDevices([]),
    });

    expect(reason).toBeNull();
  });
});

describe('listing the microphones a browser can see', () => {
  it('offers the audio inputs and ignores everything else', async () => {
    const media = fakeMediaDevices([
      { kind: 'audioinput', deviceId: 'mic-1', label: 'Scarlett Solo USB' },
      { kind: 'videoinput', deviceId: 'cam-1', label: 'FaceTime HD' },
      { kind: 'audiooutput', deviceId: 'spk-1', label: 'Speakers' },
    ]);

    const sources = await listBrowserSources(media);

    expect(sources.map((s) => s.id)).toEqual(['mic-1']);
    expect(sources[0].label).toBe('Scarlett Solo USB');
  });

  /**
   * A browser withholds device labels until permission has been granted, so
   * before the prompt every label is `''`. Rendering a blank row would read as
   * a broken screen rather than an un-permissioned one.
   *
   * The `deviceId` is blank for the same reason and on the same condition.
   * This fixture used to pair an empty label with a real id, which is a
   * combination no browser produces — and pairing them that way is what let
   * the empty id reach `getUserMedia` unnoticed for as long as it did.
   */
  it('gives an unnamed device something readable to show', async () => {
    const media = fakeMediaDevices([{ kind: 'audioinput', deviceId: '', label: '' }]);

    const sources = await listBrowserSources(media);

    expect(sources[0].label).toMatch(/microphone/i);
    expect(sources[0].label.trim()).not.toBe('');
  });

  /**
   * The screen maps `degraded` onto "room microphone — picks up echo and
   * cross-talk". A browser cannot tell a desk mic from a wired feed off a
   * mixing desk, and calling an unknown device "wired — the cleanest signal"
   * would be a confident claim we cannot support. Every browser input is
   * therefore treated as acoustic, which is the reading that warns rather than
   * reassures.
   */
  it('treats every browser input as a room microphone', async () => {
    const media = fakeMediaDevices([
      { kind: 'audioinput', deviceId: 'mic-1', label: 'Scarlett Solo USB' },
    ]);

    const sources = await listBrowserSources(media);

    expect(sources[0].degraded).toBe(true);
  });
});

describe('opening the microphone', () => {
  it('asks for the chosen device with platform voice processing off', async () => {
    const media = fakeMediaDevices([]);

    await openBrowserCapture(media, 'mic-1');

    const constraints = media.getUserMedia.mock.calls[0][0] as {
      audio: Record<string, unknown>;
    };
    expect(constraints.audio.deviceId).toEqual({ exact: 'mic-1' });
    // The product's own claim on the consent screen: processing tuned for a
    // listener removes detail the transcriber uses.
    expect(constraints.audio.echoCancellation).toBe(false);
    expect(constraints.audio.noiseSuppression).toBe(false);
    expect(constraints.audio.autoGainControl).toBe(false);
  });

  it('pauses by silencing the track, without releasing the device', async () => {
    const track = fakeTrack();
    const media = fakeMediaDevices([], [track]);

    const session = await openBrowserCapture(media, 'mic-1');
    session.pause();

    expect(track.enabled).toBe(false);
    expect(track.stopped).toBe(false);
  });

  it('resumes without asking for the microphone a second time', async () => {
    const track = fakeTrack();
    const media = fakeMediaDevices([], [track]);

    const session = await openBrowserCapture(media, 'mic-1');
    session.pause();
    session.resume();

    expect(track.enabled).toBe(true);
    expect(media.getUserMedia).toHaveBeenCalledTimes(1);
  });

  it('hands back the stream it opened, so the level meter has something to tap', async () => {
    // Without this the capture screen can say "Recording" over a muted input
    // for forty minutes and look identical to one that is working. The level
    // meter is the only thing on the screen that tells those two apart, and it
    // needs the stream the session is already holding.
    const track = fakeTrack();
    const media = fakeMediaDevices([], [track]);

    const session = await openBrowserCapture(media, 'mic-1');

    expect(session.stream.getAudioTracks()).toEqual([track]);
  });

  /** Journey 11's claim: the device is released when you stop. */
  it('releases the device on stop', async () => {
    const track = fakeTrack();
    const media = fakeMediaDevices([], [track]);

    const session = await openBrowserCapture(media, 'mic-1');
    session.stop();

    expect(track.stopped).toBe(true);
  });

  it('turns a refused permission into a sentence the operator can act on', async () => {
    const media = {
      enumerateDevices: vi.fn(async () => []),
      getUserMedia: vi.fn(async () => {
        throw Object.assign(new Error('denied'), { name: 'NotAllowedError' });
      }),
    };

    await expect(openBrowserCapture(media, 'mic-1')).rejects.toThrow(/refused|blocked|permission/i);
  });

  it('says so when the machine has no microphone at all', async () => {
    const media = {
      enumerateDevices: vi.fn(async () => []),
      getUserMedia: vi.fn(async () => {
        throw Object.assign(new Error('none'), { name: 'NotFoundError' });
      }),
    };

    await expect(openBrowserCapture(media, 'mic-1')).rejects.toThrow(/no microphone/i);
  });
});

describe('a secure page that simply has no microphone', () => {
  /**
   * A live run photographed this screen with "Start recording" greyed out, the
   * Input section an empty heading, and nothing anywhere saying why. The page
   * was on localhost — a secure context — and the browser offered
   * `mediaDevices`, so both existing checks passed and the screen concluded
   * there was nothing to explain. There was: the machine had no microphone.
   *
   * A dead button beside an empty list is the exact failure this whole file
   * exists to prevent. An operator can act on "no microphone"; they cannot act
   * on a control that does nothing.
   */
  it('names the missing microphone rather than leaving a dead button', () => {
    expect(
      browserCaptureBlockedReason({
        isSecureContext: true,
        mediaDevices: {} as MediaDevices,
        inputCount: 0,
      }),
    ).toMatch(/no microphone/i);
  });

  it('says nothing when the browser has one', () => {
    expect(
      browserCaptureBlockedReason({
        isSecureContext: true,
        mediaDevices: {} as MediaDevices,
        inputCount: 1,
      }),
    ).toBeNull();
  });

  it('does not claim a missing microphone when it has not been asked yet', () => {
    // `inputCount` is unknown until the devices have been enumerated, and
    // "no microphone" said before looking is a guess, not a reading.
    expect(
      browserCaptureBlockedReason({
        isSecureContext: true,
        mediaDevices: {} as MediaDevices,
      }),
    ).toBeNull();
  });

  it('still leads with the insecure page, which is the fixable one', () => {
    expect(
      browserCaptureBlockedReason({
        isSecureContext: false,
        mediaDevices: undefined,
        inputCount: 0,
      }),
    ).toMatch(/secure page/i);
  });
});

/**
 * A browser withholds the `deviceId` on the same condition it withholds the
 * label: until microphone permission has been granted. Before the prompt,
 * `enumerateDevices` returns one blank placeholder per device *kind* — every
 * field the empty string — and this file's fixtures used to give those
 * placeholders a real id, which is the one combination a browser never
 * produces.
 *
 * That gap cost a live run every recording. The screen listed "Microphone 1",
 * enabled Start, and opened it with `deviceId: { exact: '' }` — a constraint
 * no device can satisfy. Chrome answered `NotFoundError`, the screen said "No
 * microphone matching that input was found", and because nothing ever asked
 * for permission plainly, the id stayed empty and the next attempt failed the
 * same way. For ever.
 */
describe('opening a device the browser has refused to name', () => {
  it('asks for the default microphone rather than a device id nothing can match', async () => {
    const media = fakeMediaDevices([]);

    await openBrowserCapture(media, '');

    const constraints = media.getUserMedia.mock.calls[0][0] as {
      audio: Record<string, unknown>;
    };
    // Not `deviceId: { exact: '' }`, and not `deviceId: {}` either — the
    // absence of the constraint is what means "whichever one you default to".
    expect(constraints.audio).not.toHaveProperty('deviceId');
  });

  it('keeps platform voice processing off for the default microphone too', async () => {
    const media = fakeMediaDevices([]);

    await openBrowserCapture(media, '');

    const constraints = media.getUserMedia.mock.calls[0][0] as {
      audio: Record<string, unknown>;
    };
    // `audio: true` would pass the test above and quietly undo the promise the
    // consent screen makes to the client.
    expect(constraints.audio.echoCancellation).toBe(false);
    expect(constraints.audio.noiseSuppression).toBe(false);
    expect(constraints.audio.autoGainControl).toBe(false);
  });

  it('still pins the device once the browser has named one', async () => {
    const media = fakeMediaDevices([]);

    await openBrowserCapture(media, 'mic-1');

    const constraints = media.getUserMedia.mock.calls[0][0] as {
      audio: Record<string, unknown>;
    };
    expect(constraints.audio.deviceId).toEqual({ exact: 'mic-1' });
  });
});

describe('which device was actually opened', () => {
  /**
   * When the caller asked for the default microphone there is no id to carry
   * forward — the browser chose, and only the track it handed back knows what
   * it chose. Without asking it, the screen cannot mark the row that is live.
   */
  it('reports the id the browser settled on', async () => {
    const track = { ...fakeTrack(), getSettings: () => ({ deviceId: 'mic-1' }) };
    const media = fakeMediaDevices([], [track]);

    const session = await openBrowserCapture(media, '');

    expect(session.deviceId).toBe('mic-1');
  });

  it('reports nothing rather than guessing when the track will not say', async () => {
    const media = fakeMediaDevices([], [fakeTrack()]);

    const session = await openBrowserCapture(media, '');

    expect(session.deviceId).toBeNull();
  });
});
