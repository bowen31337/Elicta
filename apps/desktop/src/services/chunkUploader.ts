import { base64OfInt16 } from '../features/capture/pcm';

/**
 * A meeting's audio, on its way to the service one chunk at a time.
 *
 * **The sequence is the whole design.** `POST /api/sessions/{id}/audio-chunk`
 * appends to a buffer that expects exactly the next chunk and refuses anything
 * else with a 409 — and goes on refusing, because the buffer's idea of "next"
 * never advances. A skipped chunk therefore does not cost the seconds it held;
 * it costs every second after it. So chunks leave strictly in order, one at a
 * time, and a failure that cannot be corrected stops the upload and is
 * reported rather than being stepped over.
 *
 * Chunks rather than one upload at the end, because a five-second slice that
 * never arrives costs five seconds — a browser that dies mid-meeting holding
 * the whole recording costs the meeting.
 *
 * Written over an injected `post` for the same reason everything else in this
 * directory is: the failure paths are the interesting ones, and they are not
 * reachable against a real service.
 */

/** What the service said, reduced to what this module decides on. */
export interface ChunkResponse {
  readonly ok: boolean;
  readonly status: number;
}

export interface ChunkBody {
  readonly sequence: number;
  readonly pcm: string;
}

export type PostChunk = (meetingId: string, body: ChunkBody) => Promise<ChunkResponse>;

export interface ChunkUploader {
  /** Buffers samples, sending whole chunks as they become due. */
  push(samples: Int16Array): void;
  /** Sends what is buffered as a final, short chunk, and waits for it. */
  flush(): Promise<void>;
  /** Resolves when everything queued so far has been sent or has failed. */
  settled(): Promise<void>;
  /** Why uploading stopped, or `null` while it is working. */
  readonly failure: string | null;
  /** How many chunks the service has accepted. */
  readonly accepted: number;
}

export interface ChunkUploaderOptions {
  readonly meetingId: string;
  readonly post?: PostChunk;
  /** Samples per chunk. Five seconds at 16kHz, by default. */
  readonly chunkSamples?: number;
  /** Tries per chunk, including the first. */
  readonly attempts?: number;
  readonly wait?: (ms: number) => Promise<void>;
  /** Told once, the first time uploading stops. */
  readonly onFailure?: (message: string) => void;
}

const FIVE_SECONDS_AT_16KHZ = 16_000 * 5;
const DEFAULT_ATTEMPTS = 3;

/** The real `POST`, for callers that are not a test. */
export const postAudioChunk: PostChunk = async (meetingId, body) => {
  const response = await fetch(`/api/sessions/${encodeURIComponent(meetingId)}/audio-chunk`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify(body),
  });
  return { ok: response.ok, status: response.status };
};

/** A refusal this uploader cannot correct by trying again. */
function permanentRefusal(status: number): string | null {
  if (status === 410) {
    return (
      'This meeting’s audio has already been destroyed on the service, so no ' +
      'more of it can be sent.'
    );
  }
  if (status === 409) {
    // The hold and this uploader disagree about which chunk comes next, and
    // resending cannot bring them back into step.
    return 'The service is expecting a different part of the recording, so uploading stopped.';
  }
  if (status >= 400 && status < 500) {
    return `The service refused the recording (${status}), so uploading stopped.`;
  }
  return null;
}

export function createChunkUploader(options: ChunkUploaderOptions): ChunkUploader {
  const {
    meetingId,
    post = postAudioChunk,
    chunkSamples = FIVE_SECONDS_AT_16KHZ,
    attempts = DEFAULT_ATTEMPTS,
    wait = async (ms: number) => await new Promise((resolve) => setTimeout(resolve, ms)),
    onFailure,
  } = options;

  let pending: Int16Array[] = [];
  let pendingLength = 0;
  let sequence = 0;
  let accepted = 0;
  let failure: string | null = null;
  /** The tail of the send chain. Appending to it is what serialises the posts. */
  let queue: Promise<void> = Promise.resolve();

  function stop(message: string): void {
    if (failure !== null) return;
    failure = message;
    // Nothing buffered can ever be sent now, and holding a meeting's audio in
    // a dead uploader is just a leak.
    pending = [];
    pendingLength = 0;
    onFailure?.(message);
  }

  function take(count: number): Int16Array {
    const chunk = new Int16Array(count);
    let filled = 0;
    while (filled < count) {
      const head = pending[0];
      const wanted = count - filled;
      if (head.length <= wanted) {
        chunk.set(head, filled);
        filled += head.length;
        pending.shift();
      } else {
        chunk.set(head.subarray(0, wanted), filled);
        pending[0] = head.subarray(wanted);
        filled += wanted;
      }
    }
    pendingLength -= count;
    return chunk;
  }

  async function send(chunk: Int16Array): Promise<void> {
    if (failure !== null) return;
    const body: ChunkBody = { sequence, pcm: base64OfInt16(chunk) };

    for (let attempt = 1; attempt <= attempts; attempt += 1) {
      try {
        const response = await post(meetingId, body);
        if (response.ok) {
          sequence += 1;
          accepted += 1;
          return;
        }
        const permanent = permanentRefusal(response.status);
        if (permanent !== null) {
          stop(permanent);
          return;
        }
        // A 5xx is the service having a bad moment rather than an answer
        // about this chunk, so the same chunk goes again.
      } catch {
        // Unreachable, which on a laptop is usually a sleeping wifi card and
        // is worth several goes before a meeting is written off.
      }
      if (attempt < attempts) await wait(attempt * 500);
    }

    stop(
      'The service could not be reached, so the rest of this recording was not ' +
        'uploaded and will not be transcribed.',
    );
  }

  function enqueue(chunk: Int16Array): void {
    queue = queue.then(async () => await send(chunk));
  }

  return {
    push(samples) {
      if (failure !== null || samples.length === 0) return;
      pending.push(samples);
      pendingLength += samples.length;
      while (pendingLength >= chunkSamples) enqueue(take(chunkSamples));
    },

    async flush() {
      if (failure === null && pendingLength > 0) enqueue(take(pendingLength));
      await this.settled();
    },

    async settled() {
      // The chain grows while it is awaited — a send that completes lets the
      // next one start — so this waits until it has stopped growing.
      let last: Promise<void>;
      do {
        last = queue;
        await last;
      } while (queue !== last);
    },

    get failure() {
      return failure;
    },

    get accepted() {
      return accepted;
    },
  };
}
