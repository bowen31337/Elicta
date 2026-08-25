import { useEffect, useMemo, useSyncExternalStore } from 'react';

import { useResource, type Resource, type ResourceStatus } from './useResource';
import { apiUrl } from './apiClient';

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

/**
 * Everything currently reading the selection.
 *
 * The choice cannot live in a `useState` inside the hook, because the control
 * that changes it and the screen that obeys it are different components — the
 * picker is in the toolbar and the screen is in the pane. A copy per hook call
 * means a choice made in one is invisible to the other until a reload, which
 * is the "manual refresh" this exists to remove. So the store is the module,
 * the hooks subscribe to it, and localStorage is the value.
 */
const listeners = new Set<() => void>();

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function write(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* see `read` */
  }
  // Copied first: a listener that re-reads and re-selects must not mutate the
  // set being iterated.
  for (const listener of [...listeners]) listener();
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

/**
 * What the toolbar is *showing*, which is not always what was chosen.
 *
 * Both hooks below fall back when nothing was chosen or the choice no longer
 * exists, and deliberately do not persist that fallback. Every screen reads
 * through the hooks and so agrees with the toolbar; the audio bridge does not,
 * because it runs where no hook does. Reading the stored choice there refused
 * to attach a recording to the meeting the operator could plainly see
 * selected, and told them to choose one.
 *
 * Held in memory rather than written back: persisting is the thing the
 * fallback exists to avoid, and a resolution is only true for as long as the
 * list it was resolved against.
 */
let showingEngagementId: string | null = null;
let showingMeetingId: string | null = null;

/** The engagement a recording belongs to: what the toolbar shows. */
export function loadEffectiveEngagementId(): string | null {
  return showingEngagementId ?? loadSelectedEngagementId();
}

/** The meeting a recording belongs to: what the toolbar shows. */
export function loadEffectiveMeetingId(): string | null {
  return showingMeetingId ?? loadSelectedMeetingId();
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
  /** Re-reads the engagement list — what a screen calls after creating one. */
  readonly reload: () => void;
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
  const list = useResource<EngagementListBody>(apiUrl('/api/engagements'));
  // Read straight through to storage on every render rather than caching the
  // value here: a cached copy outlives a `localStorage.clear()` and starts
  // answering for a store that no longer holds it.
  const chosen = useSyncExternalStore(
    subscribe,
    loadSelectedEngagementId,
    loadSelectedEngagementId,
  );

  const engagements = useMemo(() => list.data?.items ?? [], [list.data]);

  const engagement =
    engagements.find((candidate) => candidate.engagement_id === chosen) ??
    engagements[0] ??
    null;

  const engagementId = engagement?.engagement_id ?? null;
  useEffect(() => {
    showingEngagementId = engagementId;
  }, [engagementId]);

  return {
    engagementId,
    engagement,
    engagements,
    // The service answering with nothing is `ready`, not `missing`: an empty
    // list is a real answer about a service that has no engagements yet.
    status: list.status,
    error: list.error,
    select: saveSelectedEngagementId,
    reload: list.reload,
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
    engagementId === null ? null : apiUrl(`/api/engagements/${encodeURIComponent(engagementId)}/meetings`),
  );
  const chosen = useSyncExternalStore(subscribe, loadSelectedMeetingId, loadSelectedMeetingId);

  // The body names the engagement it answers for, and that is checked rather
  // than assumed: `useResource` holds the previous answer until the next one
  // arrives, so for a moment after the operator switches engagement the last
  // engagement's meetings are still in hand. Showing them in the toolbar menu
  // would put one client's meeting under another client's name.
  const meetings = useMemo(
    () =>
      list.data === null || list.data.engagement_id !== engagementId ? [] : list.data.meetings,
    [list.data, engagementId],
  );

  const meeting =
    meetings.find((candidate) => candidate.meeting_id === chosen) ??
    meetings[meetings.length - 1] ??
    null;

  // Only an explicit `select` is persisted. Writing the fallback back would
  // pin the operator to whatever happened to be newest the first time they
  // opened the screen, and a meeting created afterwards would never surface.

  const meetingId = meeting?.meeting_id ?? null;
  useEffect(() => {
    showingMeetingId = meetingId;
  }, [meetingId]);

  return {
    meetingId,
    meeting,
    meetings,
    status: list.status,
    error: list.error,
    select: saveSelectedMeetingId,
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

/**
 * What a per-meeting screen says when it has no meeting to be about.
 *
 * The four screens that need this all shipped with the same line — "No
 * meeting exists yet" — and on the machine that found this bug it was simply
 * untrue. Meetings existed; they belonged to an engagement the app had never
 * been told to look at, because there was no way to tell it. An operator
 * reading that line would reasonably conclude the service had lost their work.
 *
 * So the two causes are said apart. Nothing at all is one sentence; an empty
 * engagement is another, and it names which engagement is empty — and, when
 * there are others, says where the meetings might be instead.
 */
export function meetingIdleHint(
  current: Pick<CurrentEngagement, 'engagement' | 'engagements'>,
  consequence: string,
): string {
  if (current.engagement === null) {
    return (
      'No engagement is selected, because the service holds none yet. ' +
      'Create an engagement, then a meeting under it.'
    );
  }
  const empty = `${current.engagement.client_organisation} has no meetings yet. ${consequence}`;
  return current.engagements.length > 1
    ? `${empty} Another engagement may have one — choose it from the engagement menu.`
    : empty;
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
