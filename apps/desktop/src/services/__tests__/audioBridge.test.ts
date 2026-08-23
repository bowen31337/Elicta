import { describe, expect, it, vi } from 'vitest';

import { createAudioBridge, type AudioBridgeDeps } from '../audioBridge';
import type { ChunkUploader } from '../chunkUploader';

/**
 * Whether a meeting's audio may leave this machine, and what happens when it
 * does.
 *
 * This is the module that answers the question the Consent screen makes a
 * promise about. Sending a client's voice to two transcription vendors is
 * exactly the thing that screen tells the room will not happen unasked, so the
 * gate is read before the first chunk and **every unclear answer means no**:
 * an unread gate, an unreachable service and an outstanding confirmation all
 * record locally and upload nothing. The operator is told which, because
 * "nothing was transcribed" with no reason is indistinguishable from a bug.
 */

function fakeUploader(): ChunkUploader & { pushed: number; flushed: number } {
  const state = { pushed: 0, flushed: 0, accepted: 0 };
  return {
    push(samples: Int16Array) {
      state.pushed += samples.length;
      state.accepted = 1;
    },
    async flush() {
      state.flushed += 1;
    },
    async settled() {},
    get failure() {
      return null;
    },
    get accepted() {
      return state.accepted;
    },
    get pushed() {
      return state.pushed;
    },
    get flushed() {
      return state.flushed;
    },
  };
}

function bridgeDeps(overrides: Partial<AudioBridgeDeps> = {}) {
  const uploader = fakeUploader();
  const transcribe = vi.fn(async () => {});
  const notes: (string | null)[] = [];
  const deps: AudioBridgeDeps = {
    meetingId: () => 'meeting-1',
    engagementId: () => 'engagement-1',
    readGate: async () => 'confirmed',
    createUploader: () => uploader,
    transcribe,
    onNote: (note) => notes.push(note),
    ...overrides,
  };
  return { deps, uploader, transcribe, notes };
}

describe('createAudioBridge', () => {
  it('uploads once consent is confirmed', async () => {
    const { deps, uploader } = bridgeDeps();
    const bridge = createAudioBridge(deps);

    await bridge.start();
    bridge.push(new Int16Array(32));

    expect(uploader.pushed).toBe(32);
    expect(bridge.note).toBeNull();
  });

  it('uploads when consent stands for the engagement', async () => {
    const { deps, uploader } = bridgeDeps({ readGate: async () => 'not_required' });
    const bridge = createAudioBridge(deps);

    await bridge.start();
    bridge.push(new Int16Array(32));

    expect(uploader.pushed).toBe(32);
  });

  it('records locally and uploads nothing while consent is outstanding', async () => {
    const { deps, uploader } = bridgeDeps({ readGate: async () => 'awaiting_confirmation' });
    const bridge = createAudioBridge(deps);

    await bridge.start();
    bridge.push(new Int16Array(32));

    expect(uploader.pushed).toBe(0);
    expect(bridge.note).toContain('consent');
  });

  it('uploads nothing when the gate cannot be read, rather than assuming a yes', async () => {
    const { deps, uploader } = bridgeDeps({
      readGate: async () => {
        throw new Error('service down');
      },
    });
    const bridge = createAudioBridge(deps);

    await bridge.start();
    bridge.push(new Int16Array(32));

    expect(uploader.pushed).toBe(0);
    expect(bridge.note).toContain('could not');
  });

  it('says so when the recording is not attached to a meeting', async () => {
    const { deps, uploader } = bridgeDeps({ meetingId: () => null });
    const bridge = createAudioBridge(deps);

    await bridge.start();
    bridge.push(new Int16Array(32));

    expect(uploader.pushed).toBe(0);
    expect(bridge.note).toContain('meeting');
  });

  it('never asks the gate when there is no meeting to ask about', async () => {
    const readGate = vi.fn(async () => 'confirmed' as const);
    const { deps } = bridgeDeps({ meetingId: () => null, readGate });
    const bridge = createAudioBridge(deps);

    await bridge.start();

    expect(readGate).not.toHaveBeenCalled();
  });

  it('flushes the tail and starts transcription when the recording stops', async () => {
    const { deps, uploader, transcribe } = bridgeDeps();
    const bridge = createAudioBridge(deps);

    await bridge.start();
    bridge.push(new Int16Array(32));
    await bridge.stop();

    expect(uploader.flushed).toBe(1);
    expect(transcribe).toHaveBeenCalledWith('meeting-1');
  });

  it('does not ask for a transcript of a recording it never uploaded', async () => {
    const { deps, transcribe } = bridgeDeps({ readGate: async () => 'awaiting_confirmation' });
    const bridge = createAudioBridge(deps);

    await bridge.start();
    bridge.push(new Int16Array(32));
    await bridge.stop();

    expect(transcribe).not.toHaveBeenCalled();
  });

  it('still asks for a transcript of a recording that was cut short', async () => {
    // A partial recording is worth transcribing — the operator has already
    // been told it is partial, and half a transcript beats none.
    const { deps, transcribe } = bridgeDeps();
    const bridge = createAudioBridge(deps);

    await bridge.start();
    bridge.push(new Int16Array(32));
    bridge.reportFailure('the service could not be reached');
    await bridge.stop();

    expect(transcribe).toHaveBeenCalledWith('meeting-1');
    expect(bridge.note).toContain('could not be reached');
  });

  it('says the transcript could not be started when that call fails', async () => {
    const { deps } = bridgeDeps({
      transcribe: async () => {
        throw new Error('service down');
      },
    });
    const bridge = createAudioBridge(deps);

    await bridge.start();
    bridge.push(new Int16Array(32));
    await bridge.stop();

    expect(bridge.note).toContain('transcription');
  });

  it('forgets the last recording when a new one starts', async () => {
    const { deps } = bridgeDeps({ meetingId: () => null });
    const bridge = createAudioBridge(deps);

    await bridge.start();
    expect(bridge.note).not.toBeNull();

    // A second recording, this time attached to a meeting: the old warning
    // must not still be on screen saying nothing is being uploaded.
    deps.meetingId = () => 'meeting-2';
    await bridge.start();

    expect(bridge.note).toBeNull();
  });
});
