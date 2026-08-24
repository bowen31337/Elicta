import { useMemo } from 'react';

import {
  selectionStatus,
  useCurrentEngagement,
  useCurrentMeeting,
  type MeetingSummary,
} from '../../services/selection';
import { combineStatus, useResource, type ResourceStatus } from '../../services/useResource';
import type { ArcScreenProps, Meeting, StandingQuestion } from './route';
import { apiUrl } from '../../services/apiClient';

/**
 * What the engagement arc screen shows, read from the service (PRD FR-3.11, FR-4.8, FR-8.9).
 *
 * Two reads: the engagement's meetings, and its standing state — the open
 * questions prior meetings left behind and the requirements confirmed so far.
 * The second is the whole point of an engagement-scoped product, so it comes
 * from the service's own carried-forward state rather than being recomputed
 * per meeting here.
 */
interface WireOpenQuestion {
  readonly text: string;
  readonly impact_rank: number;
}

interface WireEngagementState {
  readonly engagement_id: string;
  readonly inherited_open_questions: readonly WireOpenQuestion[];
  readonly requirements_state: { readonly confirmed_requirements: readonly unknown[] } | null;
}

/** A meeting's label: what the session was for, else how it was captured. */
function title(meeting: MeetingSummary): string {
  return meeting.session_purpose ?? `${meeting.capture_mode} capture`;
}

function date(meeting: MeetingSummary): string {
  if (meeting.scheduled_at === null) return 'Not scheduled';
  const at = new Date(meeting.scheduled_at);
  return Number.isNaN(at.getTime())
    ? meeting.scheduled_at
    : at.toLocaleDateString(undefined, { dateStyle: 'medium' });
}

export interface ArcData extends ArcScreenProps {
  readonly status: ResourceStatus;
  readonly error: string | null;
}

export function useArc(): ArcData {
  const engagement = useCurrentEngagement();
  const meetings = useCurrentMeeting(engagement.engagementId);
  const id = engagement.engagementId;

  const state = useResource<WireEngagementState>(
    id === null ? null : apiUrl(`/api/engagements/${encodeURIComponent(id)}/state`),
  );

  return {
    engagement: engagement.engagement?.client_organisation ?? 'No engagement yet',
    meetings: useMemo(
      (): readonly Meeting[] =>
        meetings.meetings.map((meeting) => ({
          id: meeting.meeting_id,
          title: title(meeting),
          date: date(meeting),
          // A meeting whose debrief has not classified sections has no
          // coverage, which is not the same as coverage of zero out of zero —
          // but the screen's props have no third state, and 0 of 0 at least
          // renders as "nothing covered yet" rather than as a false total.
          sectionsCovered: meeting.sections_filled ?? 0,
          sectionsTotal: meeting.sections_total ?? 0,
        })),
      [meetings.meetings],
    ),
    standingQuestions: useMemo(
      (): readonly StandingQuestion[] =>
        (state.data?.inherited_open_questions ?? []).map((question) => ({
          id: `rank-${question.impact_rank}-${question.text}`,
          text: question.text,
          // The service carries a standing question's text and its impact
          // rank, and nothing else: the durable `open_questions` table has
          // exactly two columns. Which meeting first raised it, and how many
          // it has survived, are not recorded anywhere — so this says so
          // rather than naming a meeting it cannot know, and counts one
          // meeting rather than claiming a streak it cannot see.
          raisedIn: 'an earlier meeting',
          meetingsOpen: 1,
        })),
      [state.data],
    ),
    confirmedRequirements: state.data?.requirements_state?.confirmed_requirements.length ?? 0,
    status:
      id === null
        ? selectionStatus(engagement.status, id)
        : combineStatus(engagement.status, meetings.status, state.status),
    error: engagement.error ?? meetings.error ?? state.error,
  };
}
