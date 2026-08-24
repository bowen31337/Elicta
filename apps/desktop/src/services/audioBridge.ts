import type { ConsentGateStatus } from '../features/consent/route';
import { createChunkUploader, type ChunkUploader } from './chunkUploader';
import { loadSelectedEngagementId, loadSelectedMeetingId } from './selection';
import { apiUrl } from './apiClient';

/**
 * Whether this recording's audio may leave the machine — and, if it may,
 * getting it to the service and asking for a transcript at the end.
 *
 * The capture session's job is a device: open it, meter it, release it. This
 * is the other half, kept separate because it answers a different kind of
 * question. Capture asks "is a microphone open"; this asks "is this meeting
 * one whose audio we are allowed to send to two transcription vendors", which
 * is a promise the Consent screen makes out loud to the people in the room.
 *
 * **Every unclear answer means no.** An outstanding confirmation, a gate that
 * cannot be read, a recording not attached to any meeting: all record locally
 * and upload nothing. The alternative — assuming a yes when the service is
 * briefly unreachable — sends a client's voice to a vendor on the strength of
 * a failed HTTP request, and there is no taking that back.
 *
 * The operator is always told which, because a meeting that produced no
 * transcript and gave no reason is indistinguishable from a broken build.
 */

export interface AudioBridgeDeps {
  /** The meeting this recording belongs to, or `null` for a loose one. */
  meetingId(): string | null;
  engagementId(): string | null;
  /** The meeting's consent gate, or `null` when the service had no answer. */
  readGate(meetingId: string, engagementId: string): Promise<ConsentGateStatus | null>;
  createUploader(meetingId: string, onFailure: (message: string) => void): ChunkUploader;
  /** Starts the record path over the audio the service now holds. */
  transcribe(meetingId: string): Promise<void>;
  /** Publishes the note to whoever is showing it. */
  onNote(note: string | null): void;
}

export interface AudioBridge {
  /** Decides whether this recording uploads. Called as capture starts. */
  start(): Promise<void>;
  push(samples: Int16Array): void;
  /** Sends the tail and asks for a transcript. Called as capture stops. */
  stop(): Promise<void>;
  /** Something the operator needs to know about this recording, or `null`. */
  readonly note: string | null;
  /** Used by the uploader to report a failure part-way through. */
  reportFailure(message: string): void;
}

const NO_MEETING =
  'This recording is not attached to a meeting, so it is not being uploaded and ' +
  'will not be transcribed. Choose a meeting before recording.';

const AWAITING_CONSENT =
  'Nobody has confirmed consent for this meeting, so the audio stays on this ' +
  'machine and will not be transcribed. Confirm consent and record again.';

const GATE_UNREADABLE =
  'The consent gate could not be read, so nothing is being uploaded — audio is ' +
  'never sent on an unanswered gate. Check the service and record again.';

const TRANSCRIPTION_REFUSED =
  'The recording was uploaded, but transcription could not be started. Try it ' +
  'again from the Recording screen.';

/** The real gate read, for callers that are not a test. */
export async function readConsentGate(
  meetingId: string,
  engagementId: string,
): Promise<ConsentGateStatus | null> {
  const response = await fetch(
    apiUrl(`/api/meetings/${encodeURIComponent(meetingId)}/consent-gate`) +
      `?engagement_id=${encodeURIComponent(engagementId)}`,
    { headers: { Accept: 'application/json' } },
  );
  if (!response.ok) return null;
  const body = (await response.json()) as { status?: ConsentGateStatus };
  return body.status ?? null;
}

/** The real record-path kick-off, for callers that are not a test. */
export async function startRecordPath(meetingId: string): Promise<void> {
  const response = await fetch(
    apiUrl(`/api/meetings/${encodeURIComponent(meetingId)}/record/transcribe`),
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      // The hold is keyed by the id the chunks were posted under, which for
      // the record path is the meeting's — see `read_session_audio`.
      body: JSON.stringify({ audio_ref: `session:${meetingId}` }),
    },
  );
  if (!response.ok) throw new Error(`The service answered ${response.status}.`);
}

/** Consent that permits sending. Anything else, including `null`, does not. */
function permitsUpload(status: ConsentGateStatus | null): boolean {
  return status === 'confirmed' || status === 'not_required';
}

export function createAudioBridge(deps: AudioBridgeDeps): AudioBridge {
  let uploader: ChunkUploader | null = null;
  let meeting: string | null = null;
  let note: string | null = null;

  function setNote(next: string | null): void {
    note = next;
    deps.onNote(next);
  }

  const bridge: AudioBridge = {
    async start() {
      uploader = null;
      meeting = null;
      // Cleared first: a warning left over from the last recording, sitting on
      // screen through a recording that *is* uploading, is worse than none.
      setNote(null);

      const meetingId = deps.meetingId();
      if (meetingId === null) {
        setNote(NO_MEETING);
        return;
      }
      const engagementId = deps.engagementId();
      if (engagementId === null) {
        setNote(GATE_UNREADABLE);
        return;
      }

      let status: ConsentGateStatus | null;
      try {
        status = await deps.readGate(meetingId, engagementId);
      } catch {
        status = null;
      }
      if (!permitsUpload(status)) {
        setNote(status === null ? GATE_UNREADABLE : AWAITING_CONSENT);
        return;
      }

      meeting = meetingId;
      uploader = deps.createUploader(meetingId, (message) => bridge.reportFailure(message));
    },

    push(samples) {
      uploader?.push(samples);
    },

    async stop() {
      const open = uploader;
      const meetingId = meeting;
      uploader = null;
      meeting = null;
      if (open === null || meetingId === null) return;

      await open.flush();
      // A recording cut short is still worth transcribing: the operator has
      // already been told it is partial, and half a transcript beats none.
      if (open.accepted === 0) return;

      try {
        await deps.transcribe(meetingId);
      } catch {
        setNote(TRANSCRIPTION_REFUSED);
      }
    },

    reportFailure(message) {
      setNote(message);
    },

    get note() {
      return note;
    },
  };

  return bridge;
}

/** The bridge this application runs, wired to the real service. */
export function defaultAudioBridge(onNote: (note: string | null) => void): AudioBridge {
  return createAudioBridge({
    meetingId: loadSelectedMeetingId,
    engagementId: loadSelectedEngagementId,
    readGate: readConsentGate,
    createUploader: (meetingId, onFailure) => createChunkUploader({ meetingId, onFailure }),
    transcribe: startRecordPath,
    onNote,
  });
}
