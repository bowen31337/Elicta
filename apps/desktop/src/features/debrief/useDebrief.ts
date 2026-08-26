import { useEffect, useMemo, useState } from 'react';

import {
  meetingIdleHint,
  meetingTitle,
  selectionStatus,
  useCurrentEngagement,
  useCurrentMeeting,
} from '../../services/selection';
import { combineStatus, useResource, type ResourceStatus } from '../../services/useResource';
import type { Claim, DebriefScreenProps } from './route';
import { apiUrl } from '../../services/apiClient';

/**
 * What the debrief artifacts screen shows, read from the service (PRD FR-8.3, FR-8.4, FR-8.5, FR-8.8).
 *
 * The record path keys its artifacts by the meeting id and calls it a session
 * id, which is why these are apiUrl(`/api/sessions/{meetingId}/...`).
 *
 * FR-8.8 is the rule that shapes every mapping here: anything the system
 * inferred rather than heard must be visibly flagged as inference. The service
 * already fails safe in that direction — an unrecognised provenance value
 * becomes `inferred` rather than `stated` — and this does the same, because an
 * operator wrongly told "the client said this" cannot un-hear it.
 */
type WireProvenance = string;

interface WireCitation {
  readonly utterance_id: string;
  readonly start_seconds: number;
  readonly speaker_tag: string;
  readonly quoted_text: string;
}

interface WireOpenQuestion {
  readonly text: string;
  readonly impact_rank: number;
  readonly provenance: WireProvenance;
  readonly citations: readonly WireCitation[];
}

interface WireDecision {
  readonly text: string;
  readonly decided_by: string;
  readonly provenance: WireProvenance;
  readonly citations: readonly WireCitation[];
}

/** What the §7 run managed, and what stopped it (NFR-4.1). */
interface WireCompletion {
  readonly complete: boolean;
  readonly stopped_at: string | null;
  /** Written for whoever is debugging the pipeline. Never rendered. */
  readonly reason: string | null;
  readonly cause:
    | 'not_configured'
    | 'failed'
    | 'input_gone'
    | 'rate_limited'
    | 'unavailable'
    | 'credential_rejected'
    | 'not_entitled'
    | 'unknown'
    | null;
  /** Whether the pipeline is working on it right now. */
  readonly running?: boolean;
}

/**
 * What each stage is doing, in the words of someone who does not work here.
 *
 * A stage with no entry falls back to its own name with the hyphens taken out,
 * which reads acceptably ("state merge") and — crucially — still shows the
 * notice. Falling silent on an unrecognised stage would hide the warning in
 * exactly the case nobody anticipated.
 */
const STAGE_IN_PLAIN_WORDS: Record<string, string> = {
  diarization: 'telling the voices apart',
  cleaning: 'tidying up the transcript',
  translation: 'translating the transcript',
  classification: 'sorting what was said into sections',
  'analyst-chain': 'drafting the documents',
};

interface WireBrief {
  readonly body: string;
  readonly provenance: WireProvenance;
  readonly citations: readonly WireCitation[];
}

/** Only an explicit `stated` is stated. Everything else is flagged (FR-8.8). */
function provenanceOf(value: WireProvenance): Claim['provenance'] {
  return value === 'stated' ? 'stated' : 'inferred';
}

function timestamp(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`;
}

/** The first citation, as the screen renders it — or `null` if nothing backs the claim. */
function citationOf(citations: readonly WireCitation[]): Claim['citation'] {
  const first = citations[0];
  if (first === undefined) return null;
  return {
    speaker: first.speaker_tag,
    at: timestamp(first.start_seconds),
    quote: first.quoted_text,
  };
}

/**
 * The sentence the screen shows when the write-up stopped early.
 *
 * `null` covers both "it finished" and "it was never run": a notice on the
 * second would appear on every meeting whose debrief is simply still to come,
 * which is how a warning becomes wallpaper. The stage name carries the notice
 * on its own — a stage refused before it was attempted records no reason, and
 * withholding the notice for want of one would hide the very case where the
 * operator has least to go on.
 */
export function incompleteNotice(
  completion: WireCompletion | null | undefined,
): string | null {
  if (!completion || completion.complete || completion.stopped_at === null) return null;

  const stage = STAGE_IN_PLAIN_WORDS[completion.stopped_at] ?? completion.stopped_at.replace(/-/g, ' ');
  // `reason` is deliberately not rendered. A live run put a stage record's own
  // text on this screen — "supply `diarize` to anthropic_debrief_engines()
  // (architecture §3.3, ADR-011)" — which is true, and is addressed to
  // somebody else. The service classifies the kind of failure; the sentence is
  // composed here, where the reader is.
  // `input_gone` had no case, so it fell to `failed` and the screen told an
  // operator their connection had dropped. Nothing had: the recording is
  // destroyed once it has been transcribed, which is what NFR-2.4 asks for,
  // and the stage wanted it back. A remedy in the wrong place is worse than
  // no remedy — the two are not the same problem and must not read alike.
  const because =
    completion.cause === 'not_configured'
      ? ' Something it needs is not set up yet.'
      : completion.cause === 'input_gone'
        ? ' The recording it needed had already been destroyed, as it is once a meeting has been transcribed.'
        : completion.cause === 'rate_limited'
          ? // The one failure with a time on it. `spentAllowance` lifts the
            // provider's own sentence out of the stage record, because it
            // names the limit and the reset in the operator's timezone and
            // nothing here has a better source for either. Rendering "the
            // call did not get through" for this sent people to look at
            // their network.
            ` The Claude allowance for this deployment is spent.${spentAllowance(completion.reason)}`
          : completion.cause === 'credential_rejected'
            ? ' The Claude credential was refused.'
            : completion.cause === 'not_entitled'
              ? ' This credential is not permitted to make that request.'
              : completion.cause === 'failed' || completion.cause === 'unavailable'
                ? ' The call it needed did not get through.'
                : '';
  return `The write-up stopped while ${stage}.${because} Nothing below is missing on purpose.`;
}

/**
 * The provider's own sentence about a spent allowance, when it gave one.
 *
 * Lifted rather than composed: the CLI says which limit and when it resets,
 * in the operator's own timezone, and there is no better source here. It
 * arrives behind the stage prefix and the `[rate_limited]` marker that
 * `upstream_failure_in` reads, so only the tail is worth showing.
 *
 * The exception to "never put the pipeline's own words on the screen", and a
 * narrow one: this text is addressed to whoever is using the credential,
 * which is the person reading it, and the reset time is the only actionable
 * thing in the whole failure.
 */
export function spentAllowance(reason: string | null | undefined): string {
  if (!reason) return '';
  const said = reason.split(']:').pop()?.trim();
  if (!said) return '';
  // Anything that reads like a stack trace or an identifier is left out — the
  // test for it is the one the citation extractor uses on quotes: if it does
  // not look like something said to a person, it is not shown to one.
  if (/[_{}<>]|\.py:|Traceback/.test(said)) return '';
  return ` ${said.charAt(0).toUpperCase()}${said.slice(1)}${said.endsWith('.') ? '' : '.'}`;
}

/** Said when the screen has nothing on it, and the run never started. */
const NEVER_RUN =
  'No write-up has been produced for this meeting yet — one runs on its own once the recording has been transcribed.';

/** Said when the run finished and still produced nothing. */
const FINISHED_EMPTY = 'The write-up finished without producing any of these.';

/**
 * Why the screen is empty, when it is.
 *
 * An empty debrief means two things an operator acts on differently: no
 * write-up has been made yet, or one was made and found nothing. Both rendered
 * as two bare headings, which reads as the second — the same mistake the
 * recording review used to make when it reported an agreement it had never
 * measured.
 *
 * Three cases stay silent. A screen with artifacts on it explains itself; a
 * stopped run is already covered by `incompleteNotice`, which ends "Nothing
 * below is missing on purpose"; and a run still in flight has not earned
 * either sentence yet.
 */
export function emptyNotice(
  hasArtifacts: boolean,
  incomplete: string | null,
  settled: boolean,
  completionStatus: ResourceStatus,
  completion: WireCompletion | null,
): string | null {
  if (hasArtifacts || incomplete !== null || !settled) return null;
  if (completionStatus === 'missing') return NEVER_RUN;
  return completion?.complete === true ? FINISHED_EMPTY : null;
}

/**
 * What the service said when it refused to start a run.
 *
 * FastAPI puts it in `detail`. Falling back to a sentence of our own rather
 * than to the status code: "409" on screen is not something anybody can act
 * on, and a refusal with no reason reads as a broken button.
 */
async function refusalOf(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === 'string' && body.detail.length > 0) return body.detail;
  } catch {
    /* not JSON, or an empty body */
  }
  return 'The write-up could not be started. Nothing has been changed.';
}

/** A resource that has answered, either with a body or with a 404. */
function settledStatus(status: ResourceStatus): boolean {
  return status === 'ready' || status === 'missing';
}

export interface DebriefData extends DebriefScreenProps {
  readonly status: ResourceStatus;
  readonly error: string | null;
  readonly meetingId: string | null;
  /** What to say when there is no meeting — see `meetingIdleHint`. */
  readonly idleHint: string;
}

export function useDebrief(): DebriefData {
  const engagement = useCurrentEngagement();
  const meeting = useCurrentMeeting(engagement.engagementId);
  const id = meeting.meetingId;
  const scoped = (suffix: string) =>
    id === null ? null : apiUrl(`/api/sessions/${encodeURIComponent(id)}/${suffix}`);

  const [producing, setProducing] = useState(false);
  /** What the service said when it would not start a run. */
  const [refused, setRefused] = useState<string | null>(null);
  const questions = useResource<readonly WireOpenQuestion[]>(scoped('open-questions'));
  const decisions = useResource<readonly WireDecision[]>(scoped('decision-log'));
  const brief = useResource<WireBrief>(scoped('project-brief'));
  // Keyed by meeting rather than session: this one is about the pipeline run,
  // not about an artifact the record path filed under a session id.
  const completion = useResource<WireCompletion>(
    id === null ? null : apiUrl(`/api/meetings/${encodeURIComponent(id)}/debrief/completion`),
  );

  const running = completion.data?.running === true;
  // A stopped run explains itself; a run still going has not earned that
  // sentence yet, and showing both at once says two contradictory things.
  const incomplete = running ? null : incompleteNotice(completion.data);

  /* Asked again while it is working.
   *
   * The run endpoint answers immediately now and the pipeline goes on behind
   * it, which is only an improvement if something notices it finishing.
   * Nothing did: `produce` re-read once, straight after the POST, when the
   * pipeline had not started a stage — so the screen showed the same nothing
   * it had before, which is what "write it up now does not work" looked like.
   *
   * Every fifteen seconds, and only while running. The pipeline is minutes of
   * model calls, so this is a handful of requests, not a poll loop. */
  useEffect(() => {
    if (!running) return undefined;
    const timer = window.setInterval(() => {
      completion.reload();
      brief.reload();
      decisions.reload();
      questions.reload();
    }, 15_000);
    return () => window.clearInterval(timer);
  }, [running, completion, brief, decisions, questions]);

  const openQuestions = useMemo(
    (): readonly Claim[] =>
      (questions.data ?? []).map((question) => ({
        id: `question-${question.impact_rank}`,
        text: question.text,
        provenance: provenanceOf(question.provenance),
        citation: citationOf(question.citations),
      })),
    [questions.data],
  );
  const decisions_ = useMemo(
    (): readonly Claim[] =>
      (decisions.data ?? []).map((decision, index) => ({
        id: `decision-${index}`,
        text: decision.text,
        provenance: provenanceOf(decision.provenance),
        citation: citationOf(decision.citations),
      })),
    [decisions.data],
  );
  const brief_ =
    brief.data === null || brief.data === undefined
      ? null
      : {
          id: 'brief',
          text: brief.data.body,
          provenance: provenanceOf(brief.data.provenance),
          citation: citationOf(brief.data.citations),
        };

  // Every read has to have answered before the screen may call itself empty:
  // a notice that flashes while the artifacts are still arriving is one people
  // learn to read past.
  const settled =
    settledStatus(questions.status) &&
    settledStatus(decisions.status) &&
    settledStatus(brief.status) &&
    settledStatus(completion.status);

  const produce = async () => {
    if (id === null) return;
    setProducing(true);
    try {
      const response = await fetch(
        apiUrl(`/api/meetings/${encodeURIComponent(id)}/debrief/run`),
        { method: 'POST', headers: { Accept: 'application/json' } },
      );
      if (!response.ok) {
        // A refusal is the service saying why, and it is the one thing the
        // operator can act on — a meeting with nothing transcribed answers
        // 409 here, and swallowing it left the button looking broken.
        setRefused(await refusalOf(response));
        return;
      }
      setRefused(null);
      // Re-read rather than assume. The run is under way rather than done, so
      // what this picks up is the `running` flag; the effect above takes it
      // from there.
      completion.reload();
    } finally {
      setProducing(false);
    }
  };

  return {
    meetingTitle: meetingTitle(engagement.engagement, meeting.meeting),
    // A refusal outranks everything: it is the answer to the thing the
    // operator just did.
    incomplete: refused ?? incomplete,
    running,
    onProduce: produce,
    producing,
    empty: emptyNotice(
      brief_ !== null || openQuestions.length > 0 || decisions_.length > 0,
      incomplete,
      settled,
      completion.status,
      completion.data,
    ),
    openQuestions,
    decisions: decisions_,
    brief: brief_,
    // All three 404 for a meeting that has not been debriefed, and that is
    // content: the screen renders with nothing in it rather than claiming a
    // fault. Only the selection reads decide whether it can render at all.
    status:
      id === null
        ? selectionStatus(combineStatus(engagement.status, meeting.status), id)
        : combineStatus(engagement.status, meeting.status),
    // `completion.error` is deliberately absent: a 404 there is the ordinary
    // case, and letting it decide the screen's error would replace a rendered
    // debrief with a failure message on every meeting that finished cleanly.
    error: engagement.error ?? meeting.error ?? questions.error ?? decisions.error ?? brief.error,
    meetingId: id,
    idleHint: meetingIdleHint(engagement, 'Artifacts appear after one has been debriefed.'),
  };
}
