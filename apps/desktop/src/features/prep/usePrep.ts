import { useEffect, useMemo } from 'react';

import {
  selectionStatus,
  useCurrentEngagement,
  type EngagementSummary,
} from '../../services/selection';
import { combineStatus, useResource, type ResourceStatus } from '../../services/useResource';
import type {
  PreparedMeeting,
  QuestionBank,
  ReferenceDocument,
  VocabularyEntry,
} from './types';
import { apiUrl } from '../../services/apiClient';

/**
 * What the preparation screen shows, read from the service (PRD FR-3.1, FR-3.6, FR-4.8).
 *
 * Three reads against one engagement, deliberately not one: the documents, the
 * vocabulary and the compiled bank are written by three different routes at
 * three different times, and an engagement mid-setup has some and not others.
 * Collapsing them into a single call would make "documents attached, bank not
 * compiled yet" — the normal state of a real engagement — indistinguishable
 * from a failure.
 */
interface WireDocument {
  readonly document_id: string;
  readonly name: string;
  readonly status: string;
}

interface WireDocumentList {
  readonly documents: readonly WireDocument[];
}

interface WireVocabulary {
  readonly terms: readonly { term_id?: string; term: string }[];
}

interface WireMeeting {
  readonly meeting_id: string;
  readonly capture_mode: string;
  readonly state: string;
  readonly scheduled_at: string | null;
  readonly session_purpose: string | null;
}

interface WireMeetingList {
  readonly meetings: readonly WireMeeting[];
}

/** How far the last compile got, and what stopped it. See `compileNotice`. */
interface WireCompileOutcome {
  /**
   * `running`, `awaiting`, `complete` or `stopped`.
   *
   * `awaiting` is the drafting job sitting with the provider as a batch —
   * everything asked of the chain is done and the result comes back on its
   * own. It was reported as `stopped` until a live compile told an operator
   * their successful submission had produced no usable bank.
   */
  readonly state?: 'running' | 'awaiting' | 'complete' | 'stopped';
  readonly complete: boolean;
  /** Which stages finished. Sent by the service; useful for saying so. */
  readonly stages_completed?: readonly string[];
  /** When the compile was accepted, so the meter can move within a stage. */
  readonly started_at?: string | null;
  readonly stopped_at: string | null;
  /** Written for whoever maintains the pipeline. Never rendered. */
  readonly reason: string | null;
  readonly cause: string | null;
}

/** What each compile stage is doing, in the words of someone outside the team. */
const COMPILE_STAGE: Record<string, string> = {
  extraction: 'reading the documents',
  structuring: 'sorting what it found in them',
  'batch-submission': 'sending off the drafting job',
  'batch-collection': 'collecting the drafted questions',
  // The route taken when the drafting job cannot be sent off at all.
  'analyst-pass-direct': 'drafting the questions',
  'the compile itself': 'running the compile',
};

/**
 * What each kind of failure means for the person who has to fix it.
 *
 * Kept apart because the remedies are: a throttle clears on its own, a
 * credential the plan does not cover never will, and telling the second it is
 * the first sends an operator away to wait for something that is not coming.
 * That is not hypothetical — a real compile stopped four times on a model the
 * credential could not use, and the screen said "Not compiled yet" each time.
 */
const COMPILE_CAUSE: Record<string, string> = {
  not_configured:
    'No AI provider is set up yet — add one in Settings, and this will work without a restart.',
  not_entitled:
    'Your credential is not permitted to do it: either the model chosen in Settings is one '
    + 'your plan does not include, or the token cannot submit the batch job that drafts the '
    + 'questions. Waiting will not help; the plan or the permission is the thing to change.',
  credential_rejected:
    'The provider refused the credential. Re-enter it in Settings.',
  rate_limited:
    'The provider is throttling this deployment. Nothing is misconfigured, and it should '
    + 'clear on its own.',
  unavailable:
    'The provider could not be reached. This is usually the network from this machine.',
};

/**
 * The sentence the screen shows when a compile ran and stopped.
 *
 * `null` covers both "it finished" and "none has been asked for". The second
 * is why this reads the compile route rather than inferring from an empty
 * bank: an engagement nobody has compiled yet is not a failure, and a warning
 * shown on every one of those is a warning nobody reads by the second week.
 *
 * `reason` is never rendered. It is the stage record's own text, written for
 * whoever maintains the pipeline — the debrief screen showed one of those
 * verbatim once, and an operator ended up reading `anthropic_debrief_engines()`.
 */
/** Whether a compile is on the wire right now. */
export function compileRunning(outcome: WireCompileOutcome | null | undefined): boolean {
  return outcome?.state === 'running';
}

/**
 * The stages the service says are finished, for the meter to draw.
 *
 * Reported by the run itself as each one completes, and dropped on the floor
 * until now — which is why "Compiling" said the same thing at ten seconds and
 * at six minutes, and why two reports came back saying it took for ever.
 */
export function compileStages(
  outcome: WireCompileOutcome | null | undefined,
): readonly string[] {
  return outcome?.stages_completed ?? [];
}

/**
 * How a compile's own notice reads: something to wait out, look at, or fix.
 *
 * A run that stopped is an error — a stage could not run and somebody has to
 * do something. A run that *finished* and produced no usable bank is a
 * warning: nothing broke, and there is still something to look at. Everything
 * else is work in progress, which is not a problem at all.
 */
/**
 * When the compile began, as the meter needs it.
 *
 * `null` for anything unparseable rather than a guess: a start time invented
 * here would make the bar creep from a moment that never happened.
 */
export function compileStartedAt(
  outcome: WireCompileOutcome | null | undefined,
): number | null {
  if (!outcome?.started_at) return null;
  const at = Date.parse(outcome.started_at);
  return Number.isNaN(at) ? null : at;
}

export function compileTone(
  outcome: WireCompileOutcome | null | undefined,
): 'working' | 'warning' | 'error' {
  if (outcome?.state === 'stopped' || outcome?.stopped_at) return 'error';
  if (outcome?.complete) return 'warning';
  return 'working';
}

export function compileNotice(outcome: WireCompileOutcome | null | undefined): string | null {
  if (compileRunning(outcome)) {
    return 'Compiling now — reading the documents and drafting candidates. Minutes, not seconds.';
  }
  /* The halfway point, and where a compile spends most of its life. The
     drafting job goes to the provider as a batch and comes back minutes or
     hours later; the chain returns at that point having done everything asked
     of it. It used to be recorded as a stop, so forty seconds after a
     submission that had just succeeded the operator was told the compile
     "stopped while collecting the drafted questions" and that "the drafting
     itself did not produce a usable bank". Every clause wrong, while the
     provider was still working. */
  if (outcome?.state === 'awaiting') {
    return (
      'The drafting job has been sent off and is with the provider. It comes '
      + 'back on its own — usually minutes, sometimes hours — and the bank '
      + 'fills in when it does. Nothing needs doing.'
    );
  }
  if (!outcome || outcome.complete || outcome.stopped_at === null) return null;
  const stage = COMPILE_STAGE[outcome.stopped_at] ?? outcome.stopped_at.replace(/-/g, ' ');
  // `failed` is everything that is not a provider problem — a bug here, or a
  // draft that did not meet the standard the bank has to hold to. The service
  // records exactly what happened; that text is written for whoever maintains
  // it, so this says where to find it rather than reciting it.
  const because =
    COMPILE_CAUSE[outcome.cause ?? '']
    ?? 'Nothing was refused — the drafting itself did not produce a usable bank. '
      + 'The service recorded what went wrong.';
  return `The last compile stopped while ${stage}. ${because}`;
}

interface WireBankCandidate {
  readonly id: string;
  readonly phrasing: string;
  readonly priority: number;
  readonly pruned: boolean;
  readonly source_doc?: string | null;
  readonly authority_match?: readonly string[];
}

interface WireBank {
  readonly sections: readonly {
    readonly template_section: string;
    readonly candidates: readonly WireBankCandidate[];
  }[];
}

/** The three statuses the screen's own props recognise. */
const DOCUMENT_STATUSES: readonly ReferenceDocument['status'][] = [
  'ground truth',
  'hypothesis',
  'superseded',
];

function toDocumentStatus(status: string): ReferenceDocument['status'] {
  // The service's enum values carry a space ('ground truth'), and a value it
  // grows later must not be rendered as one of the three that already mean
  // something — an unknown tag reads as a hypothesis, the weakest claim,
  // rather than being promoted to ground truth by accident.
  const known = DOCUMENT_STATUSES.find((candidate) => candidate === status);
  return known ?? 'hypothesis';
}

export interface PrepData {
  readonly clientOrganisation: string;
  readonly documents: readonly ReferenceDocument[];
  readonly vocabulary: readonly VocabularyEntry[];
  readonly bank: QuestionBank | null;
  /** Why the bank is empty, when a compile ran and stopped. */
  readonly compileNotice: string | null;
  /** True while a compile is on the wire. */
  readonly compileRunning: boolean;
  /** Where the compile is, for the meter to draw. */
  readonly compileState: 'idle' | 'running' | 'awaiting' | 'complete' | 'stopped';
  /** Which stages the service says are finished. */
  readonly compileStages: readonly string[];
  /** How the notice reads: something to wait out, look at, or fix. */
  readonly compileTone: 'working' | 'warning' | 'error';
  /** When the compile began, in epoch milliseconds, or `null`. */
  readonly compileStartedAt: number | null;
  readonly meetings: readonly PreparedMeeting[];
  readonly status: ResourceStatus;
  readonly error: string | null;
  readonly engagement: EngagementSummary | null;
  readonly engagementId: string | null;
  /**
   * Re-reads all four, which is what an edit on this screen needs: attaching a
   * document changes the document list, adding a term changes the vocabulary,
   * and creating an engagement changes which engagement the screen is about.
   * Cheaper than tracking which write invalidates which read, and there is no
   * meaningful cost to a screen the operator visits between meetings.
   */
  readonly reload: () => void;
}

export function usePrep(): PrepData {
  const current = useCurrentEngagement();
  const id = current.engagementId;
  const scoped = (suffix: string) =>
    id === null ? null : apiUrl(`/api/engagements/${encodeURIComponent(id)}/${suffix}`);

  const documents = useResource<WireDocumentList>(scoped('documents'));
  const vocabulary = useResource<WireVocabulary>(scoped('vocabulary'));
  const bank = useResource<WireBank>(scoped('bank'));
  // Why the bank is empty, when it is. 404 here means no compile has been
  // asked for — which is the ordinary case and must not read as a failure.
  const compile = useResource<WireCompileOutcome>(scoped('bank/compile'));
  // Journey 1 prepares an engagement, and a prepared engagement with no way to
  // put a meeting in it is a dead end: every journey after this one needs one.
  const meetings = useResource<WireMeetingList>(scoped('meetings'));

  /* Asked again while one is running.
   *
   * Every read on this screen happens once, at mount. That is right for a
   * document list and wrong for a compile: it takes minutes, reports each
   * stage as it finishes, and the screen showed whatever was true when it
   * opened. Reported as a meter frozen at thirteen per cent while the service
   * had the compile finished — which reads exactly like one that is stuck.
   *
   * Four seconds because stages land about twenty apart, so this catches each
   * one within a fifth of its life; and only while there is something to
   * catch, so a settled screen makes no requests at all.
   *
   * The bank is re-read with it: when the last stage lands, the questions are
   * what the operator came for.
   */
  const compiling = compile.data?.state === 'running' || compile.data?.state === 'awaiting';
  useEffect(() => {
    if (!compiling) return undefined;
    const timer = window.setInterval(() => {
      compile.reload();
      bank.reload();
    }, 4_000);
    return () => window.clearInterval(timer);
  }, [compiling, compile, bank]);

  const sections = bank.data?.sections ?? [];

  return {
    clientOrganisation: current.engagement?.client_organisation ?? 'No engagement yet',
    documents: useMemo(
      () =>
        (documents.data?.documents ?? []).map((document) => ({
          id: document.document_id,
          name: document.name,
          status: toDocumentStatus(document.status),
        })),
      [documents.data],
    ),
    vocabulary: useMemo(
      () =>
        (vocabulary.data?.terms ?? []).map((entry) => ({
          // The id is what a removal needs; a list of bare strings could show
          // the words and never take one back out.
          id: entry.term_id ?? entry.term,
          term: entry.term,
        })),
      [vocabulary.data],
    ),
    // `null` is the screen's "not compiled yet" branch, and a compile that has
    // not run returns 200 with no sections rather than a 404 — so emptiness,
    // not the status code, is what decides it.
    bank: sections.length === 0 ? null : { sections: sections.map(toSection) },
    compileNotice: compileNotice(compile.data),
    compileRunning: compileRunning(compile.data),
    compileState: (compile.data?.state ?? 'idle') as
      | 'idle'
      | 'running'
      | 'awaiting'
      | 'complete'
      | 'stopped',
    compileStages: compileStages(compile.data),
    compileTone: compileTone(compile.data),
    compileStartedAt: compileStartedAt(compile.data),
    meetings: useMemo(
      () =>
        (meetings.data?.meetings ?? []).map((meeting) => ({
          id: meeting.meeting_id,
          purpose: meeting.session_purpose,
          captureMode: meeting.capture_mode,
          state: meeting.state,
          scheduledAt: meeting.scheduled_at,
        })),
      [meetings.data],
    ),
    status:
      id === null
        ? selectionStatus(current.status, id)
        : combineStatus(current.status, documents.status, vocabulary.status, bank.status),
    // `compile.error` is deliberately absent: a 404 there is the ordinary case
    // and letting it decide the screen's state would replace a working
    // Preparation screen with a failure message for every engagement that has
    // not been compiled yet.
    error: current.error ?? documents.error ?? vocabulary.error ?? bank.error,
    engagement: current.engagement,
    engagementId: id,
    reload: () => {
      current.reload();
      documents.reload();
      meetings.reload();
      vocabulary.reload();
      bank.reload();
      // Missing until now, so nothing an operator pressed refreshed the one
      // reading that changes on its own.
      compile.reload();
    },
  };
}

function toSection(section: WireBank['sections'][number]) {
  return {
    templateSection: section.template_section,
    // A pruned candidate was explicitly excluded by a reviewer; showing it
    // again would undo the only editing action this screen offers.
    candidates: section.candidates
      .filter((candidate) => !candidate.pruned)
      .map((candidate) => ({
        id: candidate.id,
        phrasing: candidate.phrasing,
        priority: candidate.priority,
        sourceDoc: candidate.source_doc ?? null,
        authorityMatch: candidate.authority_match ?? [],
      })),
  };
}
