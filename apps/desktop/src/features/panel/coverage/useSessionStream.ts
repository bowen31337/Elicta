import { useEffect, useRef, useState } from 'react';
import { parseSessionStreamEvent } from './sessionStreamEvents';
import type { DetectedLanguage } from '../language/types';
import type { CoverageSummary, SessionStreamNudge, SessionStreamUtterance } from './types';
import { apiUrl } from '../../../services/apiClient';

/**
 * The subset of `EventSource` this hook relies on. Kept as a narrow
 * interface rather than depending on the global `EventSource` directly, so
 * tests can supply a fake source and drive it deterministically instead of
 * needing a real SSE connection (or a jsdom polyfill for one).
 */
export interface SessionStreamSource {
  addEventListener(type: string, listener: (event: MessageEvent<string>) => void): void;
  removeEventListener(type: string, listener: (event: MessageEvent<string>) => void): void;
  close(): void;
}

export type SessionStreamSourceFactory = (url: string) => SessionStreamSource;

const defaultCreateSource: SessionStreamSourceFactory = (url) => new EventSource(url);

export interface UseSessionStreamOptions {
  /** Called for every nudge event the stream carries. */
  onNudge?: (nudge: SessionStreamNudge) => void;
  /** Overridable for tests; defaults to opening a real `EventSource`. */
  createSource?: SessionStreamSourceFactory;
}

export interface UseSessionStreamResult {
  /** Languages on the panel strip: expected until something is heard. */
  readonly languages: readonly DetectedLanguage[];
  /**
   * The meeting so far, oldest first — every speaker, whether or not the line
   * earned a nudge.
   *
   * Held here rather than forwarded through a callback like the nudges,
   * because there is no queueing decision to make about it. A nudge competes
   * for the one prominent slot and is rate-limited; a transcript is simply
   * the record, and the panel renders all of it.
   */
  readonly transcript: readonly SessionStreamUtterance[];
  /** The most recent coverage summary the stream has delivered. */
  coverage: CoverageSummary | null;
  /**
   * Whether the slow lane can reach a model. Starts `true` and is only ever
   * lowered by the service saying so: a panel that assumed the worst until
   * told otherwise would show the degraded banner for the first second of
   * every meeting, and a banner that cries wolf stops being read.
   */
  modelReachable: boolean;
  /** Why the lane is degraded, when it is. */
  degradedReason: string | null;
  /**
   * Whether anything said in the room will be transcribed at all. Starts
   * `true` and is only ever lowered by the service saying so, for the same
   * reason `modelReachable` does.
   */
  liveTranscription: boolean;
  liveModel: string | null;
  liveTranscriptionReason: string | null;
  /** Whether audio is arriving right now. Starts false: nothing has been
   *  captured until something has. */
  receivingAudio: boolean;
  /**
   * When this run of capture began, or `null` when nothing is being
   * captured. The recording's clock, not the meeting's.
   */
  capturingSince: number | null;
}

/**
 * Consumes `GET /api/meetings/{id}/session/stream` for the second-screen
 * panel (architecture §7: desktop captures, phone renders). The stream
 * carries both coverage updates and nudges; this hook surfaces coverage as
 * state (FR-6.5's persistent indicator needs "the current summary" to
 * render, not "the log of updates") and forwards nudges through a callback,
 * since nudge queueing and rate-limiting belong to `panel/nudge`, not here.
 */
export function useSessionStream(
  /**
   * The meeting to follow, or `null` before one has started. Null is a real
   * state rather than an oversight: the panel exists before capture does, and
   * opening a stream to nothing would reconnect in a loop against a 404.
   */
  meetingId: string | null,
  options: UseSessionStreamOptions = {},
): UseSessionStreamResult {
  const { onNudge, createSource = defaultCreateSource } = options;
  const [coverage, setCoverage] = useState<CoverageSummary | null>(null);
  // Which languages this room is expected to use (FR-2.14). The stream sends
  // them before anything is transcribed; nothing was listening for them, so
  // the panel's language strip stayed empty for every meeting.
  const [languages, setLanguages] = useState<readonly DetectedLanguage[]>([]);
  const [lane, setLane] = useState<{
    reachable: boolean;
    reason: string | null;
    transcribing: boolean;
    model: string | null;
    blockedBecause: string | null;
    hearing: boolean;
    since: number | null;
  }>({
    reachable: true,
    reason: null,
    transcribing: true,
    model: null,
    blockedBecause: null,
    hearing: false,
    since: null,
  });
  // Filed by `seq` rather than appended, which is what makes a replay
  // idempotent. The stream sends the whole meeting on every connect and
  // `EventSource` reconnects every few minutes on its own schedule, so an
  // append turned three lines into six and then nine — the same fault the
  // nudge queue had to be taught to dedupe out of.
  //
  // Sparse until the gaps fill: a frame arriving out of turn takes its own
  // place rather than the end of the line, so the transcript is never briefly
  // wrong about who answered whom.
  const [byIndex, setByIndex] = useState<readonly (SessionStreamUtterance | undefined)[]>([]);

  // `onNudge` is read through a ref so a caller passing a fresh callback
  // each render does not tear down and reopen the stream connection.
  const onNudgeRef = useRef(onNudge);
  onNudgeRef.current = onNudge;

  useEffect(() => {
    if (meetingId === null) {
      return;
    }
    const source = createSource(apiUrl(`/api/meetings/${encodeURIComponent(meetingId)}/session/stream`));

    const handleCoverage = (event: MessageEvent<string>) => {
      const parsed = parseSessionStreamEvent('coverage', event.data);
      if (parsed?.type === 'coverage') {
        setCoverage(parsed.coverage);
      }
    };

    const handleNudge = (event: MessageEvent<string>) => {
      const parsed = parseSessionStreamEvent('nudge', event.data);
      if (parsed?.type === 'nudge') {
        onNudgeRef.current?.(parsed.nudge);
      }
    };

    const handleUtterance = (event: MessageEvent<string>) => {
      const parsed = parseSessionStreamEvent('utterance', event.data);
      if (parsed?.type !== 'utterance') return;
      setByIndex((current) => {
        const { seq } = parsed.utterance;
        if (current[seq] !== undefined) return current;
        const next = current.slice();
        if (seq >= next.length) next.length = seq + 1;
        next[seq] = parsed.utterance;
        return next;
      });
    };

    const handleLane = (event: MessageEvent<string>) => {
      const parsed = parseSessionStreamEvent('lane', event.data);
      if (parsed?.type === 'lane') {
        setLane({
          reachable: parsed.lane.modelReachable,
          reason: parsed.lane.reason,
          transcribing: parsed.lane.liveTranscription,
          model: parsed.lane.liveModel,
          blockedBecause: parsed.lane.liveTranscriptionReason,
          hearing: parsed.lane.receivingAudio,
          since: parsed.lane.capturingSince,
        });
      }
    };

    const handleLanguage = (event: MessageEvent<string>) => {
      const parsed = parseSessionStreamEvent('language', event.data);
      if (parsed?.type !== 'language') return;
      setLanguages((current) =>
        current.some((entry) => entry.language === parsed.language)
          ? current
          : [...current, { language: parsed.language, tier: null, heard: false }],
      );
    };

    source.addEventListener('coverage', handleCoverage);
    source.addEventListener('language', handleLanguage);
    source.addEventListener('nudge', handleNudge);
    source.addEventListener('utterance', handleUtterance);
    source.addEventListener('lane', handleLane);

    return () => {
      source.removeEventListener('coverage', handleCoverage);
      source.removeEventListener('language', handleLanguage);
      source.removeEventListener('nudge', handleNudge);
      source.removeEventListener('utterance', handleUtterance);
      source.removeEventListener('lane', handleLane);
      source.close();
    };
  }, [meetingId, createSource]);

  // Gaps dropped on the way out: a hole is a frame not yet arrived, and the
  // panel should render the meeting it has rather than a blank row standing in
  // for one it does not.
  const transcript = byIndex.filter(
    (entry): entry is SessionStreamUtterance => entry !== undefined,
  );

  return {
    coverage,
    languages,
    transcript,
    modelReachable: lane.reachable,
    degradedReason: lane.reason,
    liveTranscription: lane.transcribing,
    liveModel: lane.model,
    liveTranscriptionReason: lane.blockedBecause,
    receivingAudio: lane.hearing,
    capturingSince: lane.since,
  };
}
