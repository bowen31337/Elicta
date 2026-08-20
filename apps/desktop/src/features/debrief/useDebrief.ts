import { useMemo } from 'react';

import {
  meetingTitle,
  selectionStatus,
  useCurrentEngagement,
  useCurrentMeeting,
} from '../../services/selection';
import { combineStatus, useResource, type ResourceStatus } from '../../services/useResource';
import type { Claim, DebriefScreenProps } from './route';

/**
 * What the debrief artifacts screen shows, read from the service (PRD FR-8.3, FR-8.4, FR-8.5, FR-8.8).
 *
 * The record path keys its artifacts by the meeting id and calls it a session
 * id, which is why these are `/api/sessions/{meetingId}/...`.
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

export interface DebriefData extends DebriefScreenProps {
  readonly status: ResourceStatus;
  readonly error: string | null;
  readonly meetingId: string | null;
}

export function useDebrief(): DebriefData {
  const engagement = useCurrentEngagement();
  const meeting = useCurrentMeeting(engagement.engagementId);
  const id = meeting.meetingId;
  const scoped = (suffix: string) =>
    id === null ? null : `/api/sessions/${encodeURIComponent(id)}/${suffix}`;

  const questions = useResource<readonly WireOpenQuestion[]>(scoped('open-questions'));
  const decisions = useResource<readonly WireDecision[]>(scoped('decision-log'));
  const brief = useResource<WireBrief>(scoped('project-brief'));

  return {
    meetingTitle: meetingTitle(engagement.engagement, meeting.meeting),
    openQuestions: useMemo(
      (): readonly Claim[] =>
        (questions.data ?? []).map((question) => ({
          id: `question-${question.impact_rank}`,
          text: question.text,
          provenance: provenanceOf(question.provenance),
          citation: citationOf(question.citations),
        })),
      [questions.data],
    ),
    decisions: useMemo(
      (): readonly Claim[] =>
        (decisions.data ?? []).map((decision, index) => ({
          id: `decision-${index}`,
          text: decision.text,
          provenance: provenanceOf(decision.provenance),
          citation: citationOf(decision.citations),
        })),
      [decisions.data],
    ),
    brief:
      brief.data === null || brief.data === undefined
        ? null
        : {
            id: 'brief',
            text: brief.data.body,
            provenance: provenanceOf(brief.data.provenance),
            citation: citationOf(brief.data.citations),
          },
    // All three 404 for a meeting that has not been debriefed, and that is
    // content: the screen renders with nothing in it rather than claiming a
    // fault. Only the selection reads decide whether it can render at all.
    status:
      id === null
        ? selectionStatus(combineStatus(engagement.status, meeting.status), id)
        : combineStatus(engagement.status, meeting.status),
    error: engagement.error ?? meeting.error ?? questions.error ?? decisions.error ?? brief.error,
    meetingId: id,
  };
}
