import { base64OfInt16 } from '../features/capture/pcm';
import { apiUrl } from './apiClient';

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
 * Chunks rather than one upload at the end, because a tenth-of-a-second slice
 * that never arrives costs a tenth of a second — a browser that dies
 * mid-meeting holding the whole recording costs the meeting.
 *
 * **The chunk is also the live path's latency floor**, which is what set this
 * size. Nothing is recognised until the chunk holding it has been filled,
 * uploaded and buffered into a window on the other side, so a five-second
 * chunk meant a question could not reach the operator for five seconds before
 * the recogniser had seen a byte. Measured against the model itself — 0.2s to
 * recognise a window — the chunk was over ninety per cent of the delay.
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

/**
 * Tells the service a recording is starting, before any of it is sent.
 *
 * The hold on the other end is opened deliberately and never conjured by a
 * chunk arriving, so that a stray chunk and a genuine second recording of the
 * same meeting can be told apart. That distinction is what lets a meeting be
 * recorded again: before it, one whose audio had been destroyed -- which is
 * every meeting that was ever recorded and written up -- answered 410 to
 * every chunk for ever, and a false start burned the meeting.
 */
export type OpenRecording = (meetingId: string) => Promise<ChunkResponse>;

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
  readonly open?: OpenRecording;
  /** Samples per chunk. A tenth of a second at 16kHz, by default. */
  readonly chunkSamples?: number;
  /** Tries per chunk, including the first. */
  readonly attempts?: number;
  readonly wait?: (ms: number) => Promise<void>;
  /** Told once, the first time uploading stops. */
  readonly onFailure?: (message: string) => void;
}

/**
 * A tenth of a second of 16kHz mono.
 *
 * **This is the live path's remaining latency floor**, and it is now the
 * whole of it: with a streaming recogniser there is no window to fill on the
 * other side, so nothing is transcribed until the chunk holding it has been
 * filled and posted. Every millisecond here is a millisecond an operator
 * waits, and it has come down 5s → 1s → this as each larger cost above it was
 * removed.
 *
 * A tenth of a second because Deepgram asks for eighty milliseconds and this
 * is the nearest round number above it that divides a second — ten posts a
 * second, to a service on this machine, each carrying about four kilobytes.
 * Smaller buys single-digit milliseconds against a real cost: the uploader
 * sends strictly one chunk at a time, so the round trip has to stay
 * comfortably shorter than the chunk or the queue grows for the rest of the
 * meeting.
 *
 * It no longer has to match the service's window. That mattered when the
 * window was the floor — unequal, the remainder grew a second per chunk until
 * two windows fired at once and the lag oscillated — but a chunk *smaller*
 * than the window simply fills it in several pieces, and against a stream
 * there is no window at all.
 */
const A_TENTH_OF_A_SECOND_AT_16KHZ = 1_600;
const DEFAULT_ATTEMPTS = 3;

/** The real `POST` that opens the recording, for callers that are not a test. */
export const openAudioRecording: OpenRecording = async (meetingId) => {
  const response = await fetch(apiUrl(`/api/sessions/${encodeURIComponent(meetingId)}/recording`), {
    method: 'POST',
    headers: { Accept: 'application/json' },
  });
  return { ok: response.ok, status: response.status };
};

/** The real `POST`, for callers that are not a test. */
export const postAudioChunk: PostChunk = async (meetingId, body) => {
  const response = await fetch(apiUrl(`/api/sessions/${encodeURIComponent(meetingId)}/audio-chunk`), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify(body),
  });
  return { ok: response.ok, status: response.status };
};

/** A refusal this uploader cannot correct by trying again. */
function permanentRefusal(status: number): string | null {
  if (status === 410) {
    // Not "this meeting is finished for ever" any more: the service is no
    // longer holding a recording for this session, which means this one was
    // closed underneath us — its audio destroyed, or swept for going quiet.
    return (
      'The service is no longer holding a recording for this meeting, so the ' +
      'rest of it could not be sent. Stop and start the recording again.'
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
    open = openAudioRecording,
    chunkSamples = A_TENTH_OF_A_SECOND_AT_16KHZ,
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
  /**
   * The open request, started when the first chunk is actually due.
   *
   * Lazy rather than at construction so a microphone that opens and delivers
   * nothing -- which is the failure the silence watchdog exists for -- leaves
   * no recording open on the service. Held as the promise rather than a
   * boolean because the sends are serialised through `queue` and this must
   * happen once, before the first of them.
   */
  let opening: Promise<boolean> | null = null;

  async function opened(): Promise<boolean> {
    opening ??= open(meetingId).then((response) => {
      if (!response.ok) {
        stop(
          `The service could not start a recording for this meeting (${response.status}), ` +
            'so none of it was uploaded.',
        );
        return false;
      }
      return true;
    });
    return await opening;
  }

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
    if (!(await opened())) return;
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
