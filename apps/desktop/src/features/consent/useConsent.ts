import { useCallback } from 'react';

import {
  meetingIdleHint,
  meetingTitle,
  selectionStatus,
  useCurrentEngagement,
  useCurrentMeeting,
} from '../../services/selection';
import { combineStatus, useResource, type ResourceStatus } from '../../services/useResource';
import { confirmConsent, startSession, type SessionStarted } from './consentActions';
import type { ConsentGateStatus, ConsentScreenProps } from './route';

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
interface WirePrompt {
  readonly title: string;
  readonly body: string;
  readonly legal_basis: string;
}

interface WireGate {
  readonly status: ConsentGateStatus;
  /** Sent only while confirmation is outstanding; the screen shows it then. */
  readonly prompt?: WirePrompt | null;
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
  /** What to say when there is no meeting — see `meetingIdleHint`. */
  readonly idleHint: string;
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

  // Until the gate has answered, the safe assumption is the one that asks:
  // a screen that guessed `confirmed` would open capture on a meeting that
  // may have no consent at all. `status` keeps this off screen anyway —
  // `ConsentRoute` renders `ScreenState` until the read completes — but the
  // default is chosen so that a future caller reaching past that cannot be
  // let through by an absent answer.
  const gateStatus: ConsentGateStatus = gate.data?.status ?? 'awaiting_confirmation';
  const wirePrompt = gate.data?.prompt ?? null;

  const { meetingId } = meeting;
  const { reload: reloadGate } = gate;
  const { reload: reloadRecord } = record;

  /**
   * Confirming re-reads both halves rather than assuming what the write did.
   * The gate is the service's decision and the record is its attribution;
   * writing one and inferring the other locally is the shape of the bug that
   * left consent recorded and read back as never given.
   */
  const confirm = useCallback(
    async (confirmedBy: string) => {
      if (meetingId === null) {
        throw new Error('No meeting is selected, so there is nothing to confirm consent for.');
      }
      await confirmConsent(meetingId, confirmedBy);
      reloadGate();
      reloadRecord();
    },
    [meetingId, reloadGate, reloadRecord],
  );

  /**
   * The service asks its own gate before allocating anything, so a start
   * refused for want of consent comes back as a 403 naming consent rather
   * than as a screen that quietly did nothing.
   */
  const start = useCallback(async (): Promise<SessionStarted> => {
    if (meetingId === null) {
      throw new Error('No meeting is selected, so there is nothing to start.');
    }
    return await startSession(meetingId);
  }, [meetingId]);

  return {
    meetingTitle: meetingTitle(engagement.engagement, meeting.meeting),
    // The gate does not report the engagement's consent model directly, but
    // it is what decides `not_required`: consent captured once for the whole
    // engagement is why this meeting is not being asked again.
    consentModel: gateStatus === 'not_required' ? 'standing for the engagement' : 'per meeting',
    gateStatus,
    prompt:
      wirePrompt === null || wirePrompt === undefined
        ? null
        : {
            title: wirePrompt.title,
            body: wirePrompt.body,
            legalBasis: wirePrompt.legal_basis,
          },
    actions: { confirm, start },
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
    idleHint: meetingIdleHint(engagement, 'Create one before recording anything.'),
  };
}
