import { useCallback, useState } from 'react';

import { captureSession, type CaptureStore } from '../../services/captureSession';
import { useCurrentEngagement, useCurrentMeeting } from '../../services/selection';
import { useResource } from '../../services/useResource';
import { goLive } from './goLive';
import { apiUrl } from '../../services/apiClient';

/**
 * Beginning a meeting, from the screen that can show you the microphone.
 *
 * The consent gate is read here as well as on the consent screen, and that is
 * deliberate rather than duplicated by accident: nothing stops an operator
 * navigating straight to this screen, and a gate that only guards the screen
 * in front of it is a warning rather than a gate. The service refuses too — it
 * asks its own gate before allocating anything and answers 403 — but a screen
 * that offers a control, takes the click and then explains is worse than one
 * that does not offer it.
 */
interface WireGate {
  readonly status: 'not_required' | 'awaiting_confirmation' | 'confirmed';
}

export interface RecordingStart {
  /** Why recording cannot begin for consent reasons, or `null`. */
  readonly consentBlocked: string | null;
  /** What went wrong on the last attempt, in the service's own words. */
  readonly error: string | null;
  readonly busy: boolean;
  /** Opens the input without recording, so it can be seen working. */
  readonly check: (sourceId?: string) => void;
  /** Opens the input if needed, books the meeting, and records. */
  readonly start: (sourceId?: string) => void;
}

export function useRecordingStart(store?: CaptureStore): RecordingStart {
  const engagement = useCurrentEngagement();
  const meeting = useCurrentMeeting(engagement.engagementId);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const gate = useResource<WireGate>(
    meeting.meetingId === null || engagement.engagementId === null
      ? null
      : apiUrl(`/api/meetings/${encodeURIComponent(meeting.meetingId)}/consent-gate`) +
          `?engagement_id=${encodeURIComponent(engagement.engagementId)}`,
  );

  // Absent means unknown, and unknown may not open the gate: a screen that
  // recorded because it could not read the gate would be recording a meeting
  // that may have no consent at all.
  const consentBlocked =
    gate.status === 'ready' && gate.data?.status !== 'awaiting_confirmation'
      ? null
      : gate.status === 'ready'
        ? 'Consent has not been confirmed for this meeting. Confirm it on the consent screen first.'
        : null;

  const { meetingId } = meeting;

  const check = useCallback(
    (sourceId?: string) => {
      setError(null);
      void (store ?? captureSession).check(sourceId).catch((cause: unknown) => {
        setError(cause instanceof Error ? cause.message : 'The microphone could not be opened.');
      });
    },
    [store],
  );

  const start = useCallback(
    (sourceId?: string) => {
      if (meetingId === null) {
        setError('No meeting is selected, so there is nothing to record.');
        return;
      }
      setError(null);
      setBusy(true);
      void goLive(meetingId, { store, sourceId })
        .catch((cause: unknown) => {
          setError(cause instanceof Error ? cause.message : 'That did not work.');
        })
        .finally(() => setBusy(false));
    },
    [meetingId, store],
  );

  return { consentBlocked, error, busy, check, start };
}
