import {
  meetingTitle,
  selectionStatus,
  useCurrentEngagement,
  useCurrentMeeting,
} from '../../services/selection';
import { combineStatus, useResource, type ResourceStatus } from '../../services/useResource';
import type { ConsentScreenProps } from './route';

/**
 * What the consent screen shows, read from the service (PRD L1/L2, D3).
 *
 * Two reads, because they answer different questions and only one of them is
 * allowed to be missing. The **gate** says whether capture may begin; the
 * **record** says on whose word. A meeting nobody has confirmed yet has a gate
 * and no record, and that 404 is the normal state before a meeting rather than
 * a failure — so it renders as "not confirmed", not as an error.
 *
 * The screen is a gate the operator has to pass, so nothing here guesses. If
 * the gate cannot be read at all, the screen refuses to render rather than
 * defaulting to either answer: showing "confirmed" would be unsafe and showing
 * "required" would be a lie about a meeting that may well have consent.
 */
type GateStatus = 'not_required' | 'awaiting_confirmation' | 'confirmed';

interface WireGate {
  readonly status: GateStatus;
}

interface WireConsentRecord {
  readonly meeting_id: string;
  readonly confirmed_by: string;
  readonly confirmed_at: string;
}

/** A timestamp an operator can read, from the service's ISO-8601. */
export function readableTimestamp(iso: string): string {
  const at = new Date(iso);
  return Number.isNaN(at.getTime())
    ? iso
    : at.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}

export interface ConsentData extends ConsentScreenProps {
  readonly status: ResourceStatus;
  readonly error: string | null;
}

export function useConsent(): ConsentData {
  const engagement = useCurrentEngagement();
  const meeting = useCurrentMeeting(engagement.engagementId);

  const gatePath =
    meeting.meetingId === null || engagement.engagementId === null
      ? null
      : `/api/meetings/${encodeURIComponent(meeting.meetingId)}/consent-gate` +
        `?engagement_id=${encodeURIComponent(engagement.engagementId)}`;

  const gate = useResource<WireGate>(gatePath);
  const record = useResource<WireConsentRecord>(
    meeting.meetingId === null
      ? null
      : `/api/meetings/${encodeURIComponent(meeting.meetingId)}/consent-record`,
  );

  const gateStatus = gate.data?.status ?? null;

  return {
    meetingTitle: meetingTitle(engagement.engagement, meeting.meeting),
    // The gate does not report the engagement's consent model directly, but
    // it is what decides `not_required`: consent captured once for the whole
    // engagement is why this meeting is not being asked again.
    consentModel: gateStatus === 'not_required' ? 'standing for the engagement' : 'per meeting',
    confirmedBy: record.data?.confirmed_by ?? null,
    confirmedAt:
      record.data === null || record.data === undefined
        ? null
        : readableTimestamp(record.data.confirmed_at),
    captureMode: meeting.meeting?.capture_mode ?? 'Not set',
    // `record` is left out of the combined status on purpose: its 404 means
    // "nobody has confirmed yet", which this screen exists to display.
    status:
      meeting.meetingId === null
        ? selectionStatus(combineStatus(engagement.status, meeting.status), meeting.meetingId)
        : combineStatus(engagement.status, meeting.status, gate.status),
    error: engagement.error ?? meeting.error ?? gate.error,
  };
}
