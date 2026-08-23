import { describe, expect, it, vi } from 'vitest';

import { createChunkUploader, type ChunkResponse, type PostChunk } from '../chunkUploader';

/**
 * Getting a meeting's audio to the service, one chunk at a time.
 *
 * The hold on the other end (`asr-record/audio_hold.py`) refuses a chunk that
 * is not the next one expected, and goes on refusing every chunk after it — so
 * **a skipped sequence does not cost a gap, it costs the rest of the meeting**.
 * Most of what is asserted here is that one rule, from both directions: chunks
 * leave in order and one at a time, and a failure that cannot be corrected
 * stops the upload and says so rather than carrying on into a wall of 409s.
 */

const CHUNK = 4;

function ok(): ChunkResponse {
  return { ok: true, status: 202 };
}

function refusal(status: number): ChunkResponse {
  return { ok: false, status };
}

/** A post whose calls are recorded, resolving successfully by default. */
function recordingPost(reply: (sequence: number) => Promise<ChunkResponse> = async () => ok()) {
  const sequences: number[] = [];
  const post: PostChunk = vi.fn(async (_meetingId, body) => {
    sequences.push(body.sequence);
    return await reply(body.sequence);
  });
  return { post, sequences };
}

function uploader(post: PostChunk, overrides: Record<string, unknown> = {}) {
  return createChunkUploader({
    meetingId: 'meeting-1',
    post,
    chunkSamples: CHUNK,
    // Awaited but never slept through: retry timing is not what these assert.
    wait: async () => {},
    ...overrides,
  });
}

describe('createChunkUploader', () => {
  it('holds a part-full chunk rather than sending a short one', async () => {
    const { post, sequences } = recordingPost();
    const upload = uploader(post);

    upload.push(new Int16Array(CHUNK - 1));
    await upload.settled();

    expect(sequences).toEqual([]);
  });

  it('sends a chunk the moment one is due', async () => {
    const { post, sequences } = recordingPost();
    const upload = uploader(post);

    upload.push(new Int16Array(CHUNK));
    await upload.settled();

    expect(sequences).toEqual([0]);
  });

  it('numbers chunks from zero, in order', async () => {
    const { post, sequences } = recordingPost();
    const upload = uploader(post);

    upload.push(new Int16Array(CHUNK * 3));
    await upload.settled();

    expect(sequences).toEqual([0, 1, 2]);
  });

  it('waits for one chunk to be accepted before sending the next', async () => {
    // Held in an object rather than a bare `let`: assigning it inside a
    // callback leaves TypeScript narrowing the variable to `null`.
    const held: { release: (() => void) | null } = { release: null };
    const { post, sequences } = recordingPost(
      async (sequence) =>
        await new Promise<ChunkResponse>((resolve) => {
          if (sequence === 0) held.release = () => resolve(ok());
          else resolve(ok());
        }),
    );
    const upload = uploader(post);

    upload.push(new Int16Array(CHUNK * 2));
    await Promise.resolve();
    await Promise.resolve();

    // Chunk 1 is buffered and must stay there: the hold expects 0 first, and
    // two posts in flight can arrive in either order.
    expect(sequences).toEqual([0]);

    held.release?.();
    await upload.settled();
    expect(sequences).toEqual([0, 1]);
  });

  it('sends what is left as a final chunk when the recording stops', async () => {
    const { post, sequences } = recordingPost();
    const upload = uploader(post);

    upload.push(new Int16Array(CHUNK + 1));
    await upload.flush();

    expect(sequences).toEqual([0, 1]);
  });

  it('sends nothing on a flush with an empty buffer', async () => {
    const { post, sequences } = recordingPost();
    const upload = uploader(post);

    upload.push(new Int16Array(CHUNK));
    await upload.flush();
    await upload.flush();

    expect(sequences).toEqual([0]);
  });

  it('retries the same sequence when the service could not be reached', async () => {
    let attempts = 0;
    const { post, sequences } = recordingPost(async () => {
      attempts += 1;
      if (attempts < 3) throw new Error('network down');
      return ok();
    });
    const upload = uploader(post);

    upload.push(new Int16Array(CHUNK));
    await upload.settled();

    expect(sequences).toEqual([0, 0, 0]);
    expect(upload.failure).toBeNull();
  });

  it('gives up after the last attempt, and stops uploading rather than skipping a chunk', async () => {
    const { post, sequences } = recordingPost(async () => {
      throw new Error('network down');
    });
    const upload = uploader(post, { attempts: 2 });

    upload.push(new Int16Array(CHUNK * 2));
    await upload.settled();

    // Two attempts at chunk 0 and nothing else. Chunk 1 must not go out: the
    // hold is still expecting 0, so it would be refused and take everything
    // after it down with it.
    expect(sequences).toEqual([0, 0]);
    expect(upload.failure).toContain('could not be reached');
  });

  it('stops without retrying when the audio has already been destroyed', async () => {
    const { post, sequences } = recordingPost(async () => refusal(410));
    const upload = uploader(post);

    upload.push(new Int16Array(CHUNK * 2));
    await upload.settled();

    expect(sequences).toEqual([0]);
    expect(upload.failure).toContain('destroyed');
  });

  it('stops without retrying when the hold refuses the sequence', async () => {
    const { post, sequences } = recordingPost(async () => refusal(409));
    const upload = uploader(post);

    upload.push(new Int16Array(CHUNK * 2));
    await upload.settled();

    // Retrying a 409 cannot help — the hold wants a different chunk than the
    // one this uploader has, and no amount of resending changes that.
    expect(sequences).toEqual([0]);
    expect(upload.failure).not.toBeNull();
  });

  it('reports the first failure once, not once per chunk that follows it', async () => {
    const failures: string[] = [];
    const { post } = recordingPost(async () => refusal(410));
    const upload = uploader(post, { onFailure: (message: string) => failures.push(message) });

    upload.push(new Int16Array(CHUNK * 3));
    await upload.settled();

    expect(failures).toHaveLength(1);
  });
});
