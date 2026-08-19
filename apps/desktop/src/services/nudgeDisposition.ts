import type { ApiClient } from './apiClient';
import { getApiClient } from './apiClient';

/**
 * What the operator did with a surfaced nudge (PRD FR-6.6/6.7). Mirrors the
 * service's `OperatorNudgeDisposition` enum, which the generated schema
 * types enforce at the call below.
 */
export type OperatorNudgeDisposition = 'taken' | 'parked';

export interface RecordDispositionArgs {
  readonly meetingId: string;
  readonly nudgeId: string;
  readonly disposition: OperatorNudgeDisposition;
  readonly client?: ApiClient;
}

/**
 * Syncs one nudge disposition to the service — the "whatever eventually
 * syncs `satisfied_at` back to the service" that `useAskedItChip`'s
 * `onAsked` seam was written for, and which did not exist while the panel
 * had no client at all.
 *
 * Deliberately fire-and-forget from the caller's point of view: the chip
 * confirms to the operator by mutating local state in the same render pass
 * (FR-6.6), so a slow or failed round trip must never hold up the panel
 * mid-meeting. A failure resolves to `false` rather than throwing, so a
 * dropped sync degrades to a missing analytics row instead of an error in
 * front of a client.
 */
export async function recordNudgeDisposition({
  meetingId,
  nudgeId,
  disposition,
  client = getApiClient(),
}: RecordDispositionArgs): Promise<boolean> {
  try {
    const { response } = await client.POST(
      '/api/meetings/{meeting_id}/nudges/{nudge_id}/disposition',
      {
        params: { path: { meeting_id: meetingId, nudge_id: nudgeId } },
        body: { disposition },
      },
    );
    return response.ok;
  } catch {
    // Network unreachable — the operator is mid-meeting and must not see
    // this. Degraded mode is a documented state, not an error path.
    return false;
  }
}
