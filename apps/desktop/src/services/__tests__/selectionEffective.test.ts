import { renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  loadEffectiveMeetingId,
  loadSelectedMeetingId,
  useCurrentMeeting,
} from '../selection';

/**
 * The divergence this covers: the toolbar shows a meeting the operator never
 * picked, because the hook falls back to the most recent one. Every screen
 * reads through that hook and is right. The audio bridge does not -- it reads
 * the stored choice -- so a recording refuses to attach to the meeting the
 * operator can plainly see selected, and says to choose one.
 */
describe('the meeting a recording attaches to', () => {
  afterEach(() => {
    window.localStorage.clear();
    vi.unstubAllGlobals();
  });

  function serving(meetings: readonly { meeting_id: string }[]) {
    return vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => ({ engagement_id: 'eng-1', meetings }),
    })) as unknown as typeof fetch;
  }

  it('is the one on screen, even when nothing was ever explicitly chosen', async () => {
    vi.stubGlobal('fetch', serving([{ meeting_id: 'meeting-1' }, { meeting_id: 'meeting-2' }]));

    const { result } = renderHook(() => useCurrentMeeting('eng-1'));
    await waitFor(() => expect(result.current.meetingId).toBe('meeting-2'));

    // Unchanged, and deliberately so: persisting the fallback would pin the
    // operator to whatever was newest the first time they opened the screen.
    expect(loadSelectedMeetingId()).toBeNull();

    // But what the operator sees selected is what a recording must use.
    expect(loadEffectiveMeetingId()).toBe('meeting-2');
  });
});
