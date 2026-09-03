import { useEffect, useState } from 'react';

import { apiUrl } from '../../../services/apiClient';
import type { BankQuestion } from './types';

/**
 * The meeting's own bank, for the rail on the panel.
 *
 * Read from `GET /api/meetings/{id}/bank` rather than from the engagement's
 * compile, and the difference matters in the room: the meeting's recompile
 * puts every question the last meeting left open ahead of everything else
 * (FR-4.8). Those are the questions the client has already failed to answer
 * once, which is exactly the ranking an operator wants at the top of a rail.
 *
 * Fetched once when the meeting is chosen, and not polled. The bank is
 * compiled before the meeting and does not change during it — unlike the
 * coverage and the nudges, which is why those ride a stream and this does not.
 *
 * A failure resolves to an empty bank rather than propagating. The rail is one
 * region of the panel and the nudges are on a different connection; a bank the
 * service could not answer for must not take down the screen an operator is
 * running a meeting from.
 */

interface WireBankCandidate {
  id: string;
  template_section: string;
  phrasing: string;
  priority: number;
  inherited_from_open_question?: boolean;
  stub?: string | null;
}

interface WireMeetingBank {
  meeting_id: string;
  candidates: WireBankCandidate[];
}

export interface MeetingBank {
  readonly questions: readonly BankQuestion[];
  /**
   * Whether the answer is in — either way. Distinct from `questions.length`,
   * because "not asked yet" and "asked, and the bank is empty" want different
   * words on screen and the second is something the operator can go and fix.
   */
  readonly loaded: boolean;
}

const NOTHING: MeetingBank = { questions: [], loaded: false };

export function useMeetingBank(meetingId: string | null): MeetingBank {
  const [bank, setBank] = useState<MeetingBank>(NOTHING);

  useEffect(() => {
    if (meetingId === null) {
      setBank(NOTHING);
      return;
    }

    // A panel can be pointed at a different meeting mid-request, and a late
    // answer must not overwrite what replaced it.
    let live = true;

    void (async () => {
      try {
        const response = await fetch(apiUrl(`/api/meetings/${encodeURIComponent(meetingId)}/bank`));
        if (!response.ok) throw new Error(`bank: ${response.status}`);
        const payload = (await response.json()) as WireMeetingBank;
        if (!live) return;
        setBank({
          questions: (payload.candidates ?? []).map(
            (candidate): BankQuestion => ({
              id: candidate.id,
              phrasing: candidate.phrasing,
              // Absence passed through as absence. A bank compiled before the
              // stub reached the panel has none, and the rail derives keywords
              // for it — but only because it can still tell.
              stub: candidate.stub ?? '',
              priority: candidate.priority,
              templateSection: candidate.template_section,
              inherited: candidate.inherited_from_open_question === true,
            }),
          ),
          loaded: true,
        });
      } catch {
        if (!live) return;
        // Loaded, and empty. The rail says the bank is empty, which is honest
        // about what is on screen; the panel keeps running on the stream.
        setBank({ questions: [], loaded: true });
      }
    })();

    return () => {
      live = false;
    };
  }, [meetingId]);

  return bank;
}
