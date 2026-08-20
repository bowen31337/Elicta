import { useMemo, useState } from 'react';

import { useResource, type Resource, type ResourceStatus } from './useResource';

/**
 * Which engagement, and which meeting, the screens are currently about.
 *
 * Every full screen takes an engagement id or a meeting id, and until the
 * service grew `GET /api/engagements` and
 * `GET /api/engagements/{id}/meetings` there was no way to obtain one — so the
 * screens shipped with hardcoded empty props and the debrief chat with the
 * literal `'meeting-1'`. This module is the answer to "which one?".
 *
 * The choice is persisted, because an operator who closes the app mid-
 * engagement and reopens it expects to be where they left off, and because
 * the alternative — always the newest — silently moves the whole app the
 * moment a colleague creates something.
 *
 * It is deliberately *not* a router parameter. The desktop router is a file
 * scan over `features/*\/route.tsx` (`router.tsx`) that passes no props and
 * parses no URL, so a selection has to live somewhere every screen can read.
 */
const ENGAGEMENT_KEY = 'elicta.selection.engagementId';
const MEETING_KEY = 'elicta.selection.meetingId';

function read(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    // A locked-down webview can refuse storage entirely. Falling back to
    // "nothing remembered" is correct; failing to render a screen is not.
    return null;
  }
}

function write(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* see `read` */
  }
}

export function loadSelectedEngagementId(): string | null {
  return read(ENGAGEMENT_KEY);
}

export function saveSelectedEngagementId(engagementId: string): void {
  write(ENGAGEMENT_KEY, engagementId);
}

export function loadSelectedMeetingId(): string | null {
  return read(MEETING_KEY);
}

export function saveSelectedMeetingId(meetingId: string): void {
  write(MEETING_KEY, meetingId);
}

/** One row of `GET /api/engagements`. */
export interface EngagementSummary {
  readonly engagement_id: string;
  readonly client_organisation: string;
  readonly sector: string;
  readonly commercial_context: string;
  readonly purpose: string | null;
  readonly scope_boundary: string | null;
  readonly target_requirements_template: string | null;
}

interface EngagementListBody {
  readonly items: readonly EngagementSummary[];
  readonly total: number;
}

/** One row of `GET /api/engagements/{id}/meetings`. */
export interface MeetingSummary {
  readonly meeting_id: string;
  readonly engagement_id: string;
  readonly state: string;
  readonly capture_mode: string;
  readonly scheduled_at: string | null;
  readonly session_purpose: string | null;
  readonly sections_filled: number | null;
  readonly sections_total: number | null;
}

interface MeetingListBody {
  readonly engagement_id: string;
  readonly meetings: readonly MeetingSummary[];
}

export interface CurrentEngagement {
  readonly engagementId: string | null;
  readonly engagement: EngagementSummary | null;
  readonly engagements: readonly EngagementSummary[];
  readonly status: ResourceStatus;
  readonly error: string | null;
  readonly select: (engagementId: string) => void;
}

/**
 * The engagement the screens are about: the one last chosen if it still
 * exists, otherwise the first the service knows about.
 *
 * Falling back rather than showing nothing matters on a fresh install, where
 * no choice has been made yet and the operator should still see their only
 * engagement without first being asked to pick it out of a list of one.
 */
export function useCurrentEngagement(): CurrentEngagement {
  const list = useResource<EngagementListBody>('/api/engagements');
  const [chosen, setChosen] = useState<string | null>(() => loadSelectedEngagementId());

  const engagements = useMemo(() => list.data?.items ?? [], [list.data]);

  const engagement =
    engagements.find((candidate) => candidate.engagement_id === chosen) ??
    engagements[0] ??
    null;

  return {
    engagementId: engagement?.engagement_id ?? null,
    engagement,
    engagements,
    // The service answering with nothing is `ready`, not `missing`: an empty
    // list is a real answer about a service that has no engagements yet.
    status: list.status,
    error: list.error,
    select: (engagementId: string) => {
      saveSelectedEngagementId(engagementId);
      setChosen(engagementId);
    },
  };
}

export interface CurrentMeeting {
  readonly meetingId: string | null;
  readonly meeting: MeetingSummary | null;
  readonly meetings: readonly MeetingSummary[];
  readonly status: ResourceStatus;
  readonly error: string | null;
  readonly select: (meetingId: string) => void;
}

/**
 * The meeting the per-meeting screens are about — the one last chosen if it
 * belongs to `engagementId`, otherwise that engagement's most recent.
 *
 * Most recent, not first: consent, recording and debrief are all about the
 * meeting that just happened or is about to.
 */
export function useCurrentMeeting(engagementId: string | null): CurrentMeeting {
  const list = useResource<MeetingListBody>(
    engagementId === null ? null : `/api/engagements/${encodeURIComponent(engagementId)}/meetings`,
  );
  const [chosen, setChosen] = useState<string | null>(() => loadSelectedMeetingId());

  const meetings = useMemo(() => list.data?.meetings ?? [], [list.data]);

  const meeting =
    meetings.find((candidate) => candidate.meeting_id === chosen) ??
    meetings[meetings.length - 1] ??
    null;

  // Only an explicit `select` is persisted. Writing the fallback back would
  // pin the operator to whatever happened to be newest the first time they
  // opened the screen, and a meeting created afterwards would never surface.

  return {
    meetingId: meeting?.meeting_id ?? null,
    meeting,
    meetings,
    status: list.status,
    error: list.error,
    select: (meetingId: string) => {
      saveSelectedMeetingId(meetingId);
      setChosen(meetingId);
    },
  };
}

/**
 * What a screen that needs an id should show, given the read that was meant
 * to supply one.
 *
 * A service that answered with an empty list is `ready` as a *fetch* and
 * `idle` as a *screen*: there is genuinely nothing to be about yet, which is
 * a different thing to say than "here is your engagement, and it is empty".
 * Keeping the two apart is what stops a fresh install looking like a broken
 * one.
 */
export function selectionStatus(status: ResourceStatus, id: string | null): ResourceStatus {
  return status === 'ready' && id === null ? 'idle' : status;
}

/** A meeting's human label, for a screen heading. */
export function meetingTitle(
  engagement: EngagementSummary | null,
  meeting: MeetingSummary | null,
): string {
  if (meeting === null) return engagement?.client_organisation ?? 'No meeting selected';
  const organisation = engagement?.client_organisation ?? meeting.engagement_id;
  return meeting.session_purpose === null
    ? organisation
    : `${organisation} — ${meeting.session_purpose}`;
}

export type { Resource, ResourceStatus };
