import { describe, expect, it, vi } from 'vitest';

import type { ApiClient } from '../apiClient';
import { DEFAULT_SERVICE_BASE_URL, serviceBaseUrl } from '../apiClient';
import { recordNudgeDisposition } from '../nudgeDisposition';

function stubClient(impl: ApiClient['POST']): ApiClient {
  return { POST: impl } as unknown as ApiClient;
}

describe('recordNudgeDisposition', () => {
  it('posts the disposition to the meeting and nudge it belongs to', async () => {
    const post = vi.fn().mockResolvedValue({ response: { ok: true } });

    await recordNudgeDisposition({
      meetingId: 'meeting-1',
      nudgeId: 'nudge-7',
      disposition: 'taken',
      client: stubClient(post),
    });

    expect(post).toHaveBeenCalledWith(
      '/api/meetings/{meeting_id}/nudges/{nudge_id}/disposition',
      {
        params: { path: { meeting_id: 'meeting-1', nudge_id: 'nudge-7' } },
        body: { disposition: 'taken' },
      },
    );
  });

  it('reports success when the service accepts the disposition', async () => {
    const post = vi.fn().mockResolvedValue({ response: { ok: true } });

    const synced = await recordNudgeDisposition({
      meetingId: 'meeting-1',
      nudgeId: 'nudge-7',
      disposition: 'parked',
      client: stubClient(post),
    });

    expect(synced).toBe(true);
  });

  it('reports failure without throwing when the service rejects it', async () => {
    const post = vi.fn().mockResolvedValue({ response: { ok: false } });

    const synced = await recordNudgeDisposition({
      meetingId: 'unknown-meeting',
      nudgeId: 'nudge-7',
      disposition: 'taken',
      client: stubClient(post),
    });

    expect(synced).toBe(false);
  });

  it('swallows a network failure so a dropped sync never surfaces mid-meeting', async () => {
    const post = vi.fn().mockRejectedValue(new Error('connection refused'));

    const synced = await recordNudgeDisposition({
      meetingId: 'meeting-1',
      nudgeId: 'nudge-7',
      disposition: 'taken',
      client: stubClient(post),
    });

    expect(synced).toBe(false);
  });
});

describe('serviceBaseUrl', () => {
  it('falls back to the local service so a dev run needs no configuration', () => {
    expect(serviceBaseUrl()).toBe(DEFAULT_SERVICE_BASE_URL);
  });
});
