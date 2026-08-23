import { useMemo } from 'react';

import {
  meetingIdleHint,
  meetingTitle,
  selectionStatus,
  useCurrentEngagement,
  useCurrentMeeting,
} from '../../services/selection';
import { combineStatus, useResource, type ResourceStatus } from '../../services/useResource';
import { readableTimestamp } from '../consent/useConsent';
import type { Divergence, RecordingScreenProps } from './route';

/**
 * What the recording review screen shows, read from the service (PRD FR-2.6, FR-2.8, NFR-2.4).
 *
 * Three reads, and each one's 404 means something the screen has to be able to
 * say out loud:
 *
 * - **divergences** absent — this meeting was never transcribed. That is the
 *   normal state of a meeting that has not happened, not a failure.
 * - **transcripts** absent — likewise; there is nothing to name the engines.
 * - **audio destruction** absent — no attempt has been made yet, which is
 *   pointedly different from a failed one. A failed destruction means the raw
 *   audio may still be sitting there, and the screen must not render that as
 *   "destroyed".
 */
interface WireAlignedSpan {
  readonly start_seconds: number;
  readonly end_seconds: number;
  readonly reference_engine: string;
  readonly reference_text: string;
  readonly other_engine: string;
  readonly other_text: string;
  readonly agreement_score: number;
  readonly is_divergent: boolean;
}

interface WireAlignment {
  readonly session_id: string;
  readonly reference_engine: string;
  readonly other_engine: string;
  readonly spans: readonly WireAlignedSpan[];
}

interface WireSegment {
  readonly start_seconds: number;
  readonly end_seconds: number;
  readonly text: string;
  readonly speaker: string | null;
}

interface WireTranscript {
  readonly engine: string;
  readonly status: string;
  readonly segments: readonly WireSegment[];
}

interface WireDestruction {
  readonly status: string;
  readonly completed_at: string;
}

/** Whose words these were, from the engine transcript that carries speakers. */
function speakerAt(segments: readonly WireSegment[], span: WireAlignedSpan): string {
  const midpoint = (span.start_seconds + span.end_seconds) / 2;
  const covering = segments.find(
    (segment) => segment.start_seconds <= midpoint && midpoint <= segment.end_seconds,
  );
  // Diarization is a separate stage from transcription and can legitimately
  // not have run. Saying so beats attributing a divergence to the wrong
  // person, which is the one mistake this screen cannot afford: a reviewer
  // resolves a disagreement partly by who they remember saying it.
  return covering?.speaker ?? 'Unattributed';
}

export interface RecordingData extends RecordingScreenProps {
  readonly status: ResourceStatus;
  readonly error: string | null;
  /** What to say when there is no meeting — see `meetingIdleHint`. */
  readonly idleHint: string;
}

export function useRecording(): RecordingData {
  const engagement = useCurrentEngagement();
  const meeting = useCurrentMeeting(engagement.engagementId);
  const id = meeting.meetingId;
  const encoded = id === null ? null : encodeURIComponent(id);

  const alignment = useResource<WireAlignment>(
    encoded === null ? null : `/api/meetings/${encoded}/record/divergences`,
  );
  const transcripts = useResource<readonly WireTranscript[]>(
    encoded === null ? null : `/api/sessions/${encoded}/record-path-transcript`,
  );
  const destruction = useResource<WireDestruction>(
    encoded === null ? null : `/api/sessions/${encoded}/audio-destruction`,
  );

  const spans = alignment.data?.spans ?? [];
  const divergent = spans.filter((span) => span.is_divergent);
  const segments = useMemo(() => {
    const reference = alignment.data?.reference_engine;
    return (
      (transcripts.data ?? []).find((transcript) => transcript.engine === reference)?.segments ?? []
    );
  }, [transcripts.data, alignment.data]);

  const engineTranscripts = transcripts.data ?? [];

  return {
    meetingTitle: meetingTitle(engagement.engagement, meeting.meeting),
    // Whether this meeting has been recorded at all, which is a different
    // question from what the engines found. All three reads 404 for a meeting
    // that never happened, and a screen built to report a comparison has
    // nothing true to say about one — so it says *that* instead of rendering
    // itself with the numbers taken out.
    recorded: engineTranscripts.length > 0,
    engines: engineTranscripts.map((transcript) => ({
      name: transcript.engine,
      status: transcript.status === 'complete' ? ('complete' as const) : ('failed' as const),
    })),
    // The share of aligned spans the two engines agreed on, or `null` when
    // there is nothing to take a share of.
    //
    // This used to read 0 for an empty set, on the reasoning that engines
    // which have not run have not agreed about anything and that 100 would be
    // the most flattering possible lie. Both halves are right and the
    // conclusion was wrong: a live run photographed "Engines agreed 0%" beside
    // "Needs a look 0" — two finished engines, no disagreements, and a
    // headline saying they matched on nothing. 0 is not the cautious answer,
    // it is the alarming lie. Neither number is a measurement, so neither is
    // reported.
    agreementPercent:
      spans.length === 0
        ? null
        : Math.round(((spans.length - divergent.length) / spans.length) * 100),
    divergences: useMemo(
      (): readonly Divergence[] =>
        divergent.map((span, index) => ({
          id: `${span.start_seconds}-${span.end_seconds}-${index}`,
          startSeconds: span.start_seconds,
          endSeconds: span.end_seconds,
          speaker: speakerAt(segments, span),
          readings: [
            { engine: span.reference_engine, text: span.reference_text },
            { engine: span.other_engine, text: span.other_text },
          ],
        })),
      // eslint-disable-next-line react-hooks/exhaustive-deps
      [alignment.data, segments],
    ),
    // Only a completed destruction is reported as one. A failed attempt means
    // the audio may still be there, and rendering that as a destruction time
    // would be the most misleading thing this screen could do.
    audioDestroyedAt:
      destruction.data?.status === 'complete'
        ? readableTimestamp(destruction.data.completed_at)
        : null,
    // The three reads' own 404s are the screen's content, so only the
    // selection reads decide whether it can render at all.
    status:
      id === null
        ? selectionStatus(combineStatus(engagement.status, meeting.status), id)
        : combineStatus(
            engagement.status,
            meeting.status,
            alignment.status === 'missing' ? 'ready' : alignment.status,
            transcripts.status === 'missing' ? 'ready' : transcripts.status,
          ),
    error: engagement.error ?? meeting.error ?? alignment.error ?? transcripts.error,
    idleHint: meetingIdleHint(
      engagement,
      'A recording is reconciled after one has been captured.',
    ),
  };
}
