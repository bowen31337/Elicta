import { useMemo } from 'react';

import {
  meetingIdleHint,
  meetingTitle,
  selectionStatus,
  useCurrentEngagement,
  useCurrentMeeting,
} from '../../services/selection';
import { combineStatus, useResource, type ResourceStatus } from '../../services/useResource';
import type { Claim, DebriefScreenProps } from './route';
import { apiUrl } from '../../services/apiClient';

/**
 * What the debrief artifacts screen shows, read from the service (PRD FR-8.3, FR-8.4, FR-8.5, FR-8.8).
 *
 * The record path keys its artifacts by the meeting id and calls it a session
 * id, which is why these are apiUrl(`/api/sessions/{meetingId}/...`).
 *
 * FR-8.8 is the rule that shapes every mapping here: anything the system
 * inferred rather than heard must be visibly flagged as inference. The service
 * already fails safe in that direction — an unrecognised provenance value
 * becomes `inferred` rather than `stated` — and this does the same, because an
 * operator wrongly told "the client said this" cannot un-hear it.
 */
type WireProvenance = string;

interface WireCitation {
  readonly utterance_id: string;
  readonly start_seconds: number;
  readonly speaker_tag: string;
  readonly quoted_text: string;
}

interface WireOpenQuestion {
  readonly text: string;
  readonly impact_rank: number;
  readonly provenance: WireProvenance;
  readonly citations: readonly WireCitation[];
}

interface WireDecision {
  readonly text: string;
  readonly decided_by: string;
  readonly provenance: WireProvenance;
  readonly citations: readonly WireCitation[];
}

/** What the §7 run managed, and what stopped it (NFR-4.1). */
interface WireCompletion {
  readonly complete: boolean;
  readonly stopped_at: string | null;
  /** Written for whoever is debugging the pipeline. Never rendered. */
  readonly reason: string | null;
  readonly cause: 'not_configured' | 'failed' | 'unknown' | null;
}

/**
 * What each stage is doing, in the words of someone who does not work here.
 *
 * A stage with no entry falls back to its own name with the hyphens taken out,
 * which reads acceptably ("state merge") and — crucially — still shows the
 * notice. Falling silent on an unrecognised stage would hide the warning in
 * exactly the case nobody anticipated.
 */
const STAGE_IN_PLAIN_WORDS: Record<string, string> = {
  diarization: 'telling the voices apart',
  cleaning: 'tidying up the transcript',
  translation: 'translating the transcript',
  classification: 'sorting what was said into sections',
  'analyst-chain': 'drafting the documents',
};

interface WireBrief {
  readonly body: string;
  readonly provenance: WireProvenance;
  readonly citations: readonly WireCitation[];
}

/** Only an explicit `stated` is stated. Everything else is flagged (FR-8.8). */
function provenanceOf(value: WireProvenance): Claim['provenance'] {
  return value === 'stated' ? 'stated' : 'inferred';
}

function timestamp(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`;
}

/** The first citation, as the screen renders it — or `null` if nothing backs the claim. */
function citationOf(citations: readonly WireCitation[]): Claim['citation'] {
  const first = citations[0];
  if (first === undefined) return null;
  return {
    speaker: first.speaker_tag,
    at: timestamp(first.start_seconds),
    quote: first.quoted_text,
  };
}

/**
 * The sentence the screen shows when the write-up stopped early.
 *
 * `null` covers both "it finished" and "it was never run": a notice on the
 * second would appear on every meeting whose debrief is simply still to come,
 * which is how a warning becomes wallpaper. The stage name carries the notice
 * on its own — a stage refused before it was attempted records no reason, and
 * withholding the notice for want of one would hide the very case where the
 * operator has least to go on.
 */
export function incompleteNotice(
  completion: WireCompletion | null | undefined,
): string | null {
  if (!completion || completion.complete || completion.stopped_at === null) return null;

  const stage = STAGE_IN_PLAIN_WORDS[completion.stopped_at] ?? completion.stopped_at.replace(/-/g, ' ');
  // `reason` is deliberately not rendered. A live run put a stage record's own
  // text on this screen — "supply `diarize` to anthropic_debrief_engines()
  // (architecture §3.3, ADR-011)" — which is true, and is addressed to
  // somebody else. The service classifies the kind of failure; the sentence is
  // composed here, where the reader is.
  const because =
    completion.cause === 'not_configured'
      ? ' Something it needs is not set up yet.'
      : completion.cause === 'failed'
        ? ' The call it needed did not get through.'
        : '';
  return `The write-up stopped while ${stage}.${because} Nothing below is missing on purpose.`;
}

/** Said when the screen has nothing on it, and the run never started. */
const NEVER_RUN =
  'No write-up has been produced for this meeting yet — one runs on its own once the recording has been transcribed.';

/** Said when the run finished and still produced nothing. */
const FINISHED_EMPTY = 'The write-up finished without producing any of these.';

/**
 * Why the screen is empty, when it is.
 *
 * An empty debrief means two things an operator acts on differently: no
 * write-up has been made yet, or one was made and found nothing. Both rendered
 * as two bare headings, which reads as the second — the same mistake the
 * recording review used to make when it reported an agreement it had never
 * measured.
 *
 * Three cases stay silent. A screen with artifacts on it explains itself; a
 * stopped run is already covered by `incompleteNotice`, which ends "Nothing
 * below is missing on purpose"; and a run still in flight has not earned
 * either sentence yet.
 */
export function emptyNotice(
  hasArtifacts: boolean,
  incomplete: string | null,
  settled: boolean,
  completionStatus: ResourceStatus,
  completion: WireCompletion | null,
): string | null {
  if (hasArtifacts || incomplete !== null || !settled) return null;
  if (completionStatus === 'missing') return NEVER_RUN;
  return completion?.complete === true ? FINISHED_EMPTY : null;
}

/** A resource that has answered, either with a body or with a 404. */
function settledStatus(status: ResourceStatus): boolean {
  return status === 'ready' || status === 'missing';
}

export interface DebriefData extends DebriefScreenProps {
  readonly status: ResourceStatus;
  readonly error: string | null;
  readonly meetingId: string | null;
  /** What to say when there is no meeting — see `meetingIdleHint`. */
  readonly idleHint: string;
}

export function useDebrief(): DebriefData {
  const engagement = useCurrentEngagement();
  const meeting = useCurrentMeeting(engagement.engagementId);
  const id = meeting.meetingId;
  const scoped = (suffix: string) =>
    id === null ? null : apiUrl(`/api/sessions/${encodeURIComponent(id)}/${suffix}`);

  const questions = useResource<readonly WireOpenQuestion[]>(scoped('open-questions'));
  const decisions = useResource<readonly WireDecision[]>(scoped('decision-log'));
  const brief = useResource<WireBrief>(scoped('project-brief'));
  // Keyed by meeting rather than session: this one is about the pipeline run,
  // not about an artifact the record path filed under a session id.
  const completion = useResource<WireCompletion>(
    id === null ? null : apiUrl(`/api/meetings/${encodeURIComponent(id)}/debrief/completion`),
  );

  const incomplete = incompleteNotice(completion.data);

  const openQuestions = useMemo(
    (): readonly Claim[] =>
      (questions.data ?? []).map((question) => ({
        id: `question-${question.impact_rank}`,
        text: question.text,
        provenance: provenanceOf(question.provenance),
        citation: citationOf(question.citations),
      })),
    [questions.data],
  );
  const decisions_ = useMemo(
    (): readonly Claim[] =>
      (decisions.data ?? []).map((decision, index) => ({
        id: `decision-${index}`,
        text: decision.text,
        provenance: provenanceOf(decision.provenance),
        citation: citationOf(decision.citations),
      })),
    [decisions.data],
  );
  const brief_ =
    brief.data === null || brief.data === undefined
      ? null
      : {
          id: 'brief',
          text: brief.data.body,
          provenance: provenanceOf(brief.data.provenance),
          citation: citationOf(brief.data.citations),
        };

  // Every read has to have answered before the screen may call itself empty:
  // a notice that flashes while the artifacts are still arriving is one people
  // learn to read past.
  const settled =
    settledStatus(questions.status) &&
    settledStatus(decisions.status) &&
    settledStatus(brief.status) &&
    settledStatus(completion.status);

  return {
    meetingTitle: meetingTitle(engagement.engagement, meeting.meeting),
    incomplete,
    empty: emptyNotice(
      brief_ !== null || openQuestions.length > 0 || decisions_.length > 0,
      incomplete,
      settled,
      completion.status,
      completion.data,
    ),
    openQuestions,
    decisions: decisions_,
    brief: brief_,
    // All three 404 for a meeting that has not been debriefed, and that is
    // content: the screen renders with nothing in it rather than claiming a
    // fault. Only the selection reads decide whether it can render at all.
    status:
      id === null
        ? selectionStatus(combineStatus(engagement.status, meeting.status), id)
        : combineStatus(engagement.status, meeting.status),
    // `completion.error` is deliberately absent: a 404 there is the ordinary
    // case, and letting it decide the screen's error would replace a rendered
    // debrief with a failure message on every meeting that finished cleanly.
    error: engagement.error ?? meeting.error ?? questions.error ?? decisions.error ?? brief.error,
    meetingId: id,
    idleHint: meetingIdleHint(engagement, 'Artifacts appear after one has been debriefed.'),
  };
}
