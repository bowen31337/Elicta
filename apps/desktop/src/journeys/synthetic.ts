/**
 * Synthetic data for the journey screens.
 *
 * One engagement, told consistently across every screen: Northwind Logistics,
 * a fixed-price discovery, three meetings in. Consistency matters more than it
 * sounds — a reader moving between journey documents should recognise the same
 * client, the same open question, the same misheard product name, because that
 * is what makes the screens read as a product rather than as eight unrelated
 * mockups.
 *
 * Everything is invented. No real client, no real credential, no real
 * utterance. The content is realistic because a screenshot of lorem ipsum
 * documents nothing about what the operator is meant to notice.
 */

import type { AboutScreenProps } from '../features/about/route';
import type { ArcScreenProps } from '../features/arc/route';
import type { CaptureScreenProps } from '../features/capture/route';
import type { ConsentScreenProps } from '../features/consent/route';
import type { DebriefScreenProps } from '../features/debrief/route';
import type { EngagementsScreenProps } from '../features/engagements/route';
import type { PrepScreenProps } from '../features/prep/route';
import type { RecordingScreenProps } from '../features/recording/route';
import type { ReplayScreenProps } from '../features/replay/route';

export const CLIENT = 'Northwind Logistics';
export const MEETING = 'Discovery 3 — integrations and volumes';

export const ENGAGEMENTS: EngagementsScreenProps = {
  engagements: [
    {
      id: 'eng-1',
      clientOrganisation: CLIENT,
      sector: 'Freight and logistics',
      commercialContext: 'Fixed-price discovery, three meetings',
    },
    {
      id: 'eng-2',
      clientOrganisation: 'Calder & Rowe',
      sector: 'Professional services',
      commercialContext: 'Matter-management replacement',
    },
  ],
  currentId: 'eng-1',
  actions: {
    open: () => undefined,
    create: async () => undefined,
    remove: async () => undefined,
  },
};

export const PREP: PrepScreenProps = {
  clientOrganisation: CLIENT,
  documents: [
    { id: 'doc-1', name: 'Current-state scoping deck', status: 'ground truth' },
    { id: 'doc-2', name: 'Warehouse throughput study 2025', status: 'ground truth' },
    { id: 'doc-3', name: 'Proposed integration approach', status: 'hypothesis' },
    { id: 'doc-4', name: 'Original RFP response', status: 'superseded' },
  ],
  meetings: [
    {
      id: 'meeting-1',
      purpose: 'Discovery 3 — integrations and volumes',
      captureMode: 'line-in',
      state: 'scheduled',
      scheduledAt: '2026-08-25T09:00:00Z',
    },
  ],
  vocabulary: [
    { id: 'term-1', term: 'Northwind' },
    { id: 'term-2', term: 'Zephyr WMS' },
    { id: 'term-3', term: 'Consignment' },
    { id: 'term-4', term: 'Cross-dock' },
    { id: 'term-5', term: 'SLA-4' },
  ],
  bank: {
    sections: [
      {
        templateSection: 'Performance',
        candidates: [
          {
            id: 'c-1',
            phrasing: 'When you say the dashboard has to be fast, what does that mean in seconds?',
            priority: 1,
            sourceDoc: '01-scoping-deck.pptx',
            authorityMatch: ['ground truth'],
          },
          {
            id: 'c-2',
            phrasing: 'Is that response time at median load, or at your Monday morning peak?',
            priority: 2,
            sourceDoc: '02-throughput-study.xlsx',
            authorityMatch: ['ground truth'],
          },
        ],
      },
      {
        templateSection: 'Integrations',
        candidates: [
          {
            id: 'c-3',
            phrasing: 'Which systems does Zephyr WMS have to talk to on day one?',
            priority: 1,
            sourceDoc: '03-integration-assumptions.docx',
            authorityMatch: ['hypothesis'],
          },
          {
            id: 'c-4',
            phrasing: 'Are those integrations real-time, or is a nightly batch acceptable?',
            priority: 2,
            sourceDoc: null,
            authorityMatch: [],
          },
        ],
      },
      {
        templateSection: 'Volumes',
        candidates: [
          {
            id: 'c-5',
            phrasing: 'How many consignments a day at peak, and how far above average is that?',
            priority: 1,
            sourceDoc: '02-throughput-study.xlsx',
            authorityMatch: ['ground truth'],
          },
        ],
      },
    ],
  },
  // A screenshot is taken with no service behind it, so the writes resolve
  // without going anywhere. This is the one place in the codebase where an
  // inert control is correct: the harness is photographing the screen, not
  // operating it. The shipped route supplies calls that reach the service.
  actions: {
    prune: async () => undefined,
    move: async () => undefined,
    compile: async () => undefined,
    addTerm: async () => undefined,
    attach: async () => undefined,
    upload: async () => undefined,
    removeDocument: async () => undefined,
    removeTerm: async () => undefined,
    renameMeeting: async () => undefined,
    removeMeeting: async () => undefined,
    addMeeting: async () => undefined,
    retag: async () => undefined,
  },
};

/**
 * One meeting, before and after consent is confirmed.
 *
 * These two were not the same scenario: the pending one overrode
 * `consentModel` to 'per meeting' while the confirmed one said 'standing for
 * the engagement', so read in sequence — which is how journey 2 presents them
 * — confirming consent appeared to change how the engagement captures it.
 * Worse, the confirmed fixture described a screen the product cannot produce:
 * 'standing for the engagement' is what the screen says when the gate answers
 * `not_required`, and that state records no confirmation, so it can never
 * carry a named confirmer. Both now run the one per-meeting scenario the
 * journey narrates.
 */
export const CONSENT_PENDING: ConsentScreenProps = {
  meetingTitle: MEETING,
  consentModel: 'per meeting',
  gateStatus: 'awaiting_confirmation',
  prompt: {
    title: 'Recording consent required',
    body:
      'This meeting will be recorded and transcribed. Continuing confirms that ' +
      'every participant has been informed and has consented to being recorded.',
    legalBasis: 'NSW Surveillance Devices Act — all-party consent',
  },
  confirmedBy: null,
  confirmedAt: null,
  actions: {
    confirm: async () => undefined,
    proceed: () => undefined,
  },
};

export const CONSENT_CONFIRMED: ConsentScreenProps = {
  ...CONSENT_PENDING,
  gateStatus: 'confirmed',
  prompt: null,
  confirmedBy: 'Priya Raman (delivery lead)',
  confirmedAt: '18 Aug 2026, 09:58',
};

/**
 * The state every engagement is in at this stage.
 *
 * `DEFAULT_CONSENT_MODEL` is engagement-level, so an engagement nobody has
 * configured never asks for a per-meeting confirmation and the gate answers
 * `not_required`. The two fixtures above show the asking model, which is real
 * and supported but reached only by configuring it — so without this one the
 * handbook would illustrate the consent screen exclusively in a state no
 * reader of this build will see.
 */
export const CONSENT_NOT_REQUIRED: ConsentScreenProps = {
  ...CONSENT_PENDING,
  consentModel: 'standing for the engagement',
  gateStatus: 'not_required',
  prompt: null,
};

export const RECORDING: RecordingScreenProps = {
  meetingTitle: MEETING,
  recorded: true,
  engines: [
    { name: 'Deepgram Nova-3', status: 'complete' },
    { name: 'AssemblyAI Universal-2', status: 'complete' },
  ],
  agreementPercent: 97,
  divergences: [
    {
      id: 'd-1',
      startSeconds: 743,
      endSeconds: 749,
      speaker: 'Client — Ops',
      readings: [
        { engine: 'Deepgram', text: 'we run about three fifty a day through cross-dock' },
        { engine: 'AssemblyAI', text: 'we run about 350 a day through cross-dock' },
      ],
    },
    {
      id: 'd-2',
      startSeconds: 1284,
      endSeconds: 1291,
      speaker: 'Client — IT',
      readings: [
        { engine: 'Deepgram', text: 'Zephyr WMS pushes to the ledger nightly' },
        { engine: 'AssemblyAI', text: 'Zephyr W M S pushes to the ledger nightly' },
      ],
    },
    {
      id: 'd-3',
      startSeconds: 1902,
      endSeconds: 1907,
      speaker: 'Client — Ops',
      readings: [
        { engine: 'Deepgram', text: 'the SLA is four hours end to end' },
        { engine: 'AssemblyAI', text: 'the SLA-4 is hours end to end' },
      ],
    },
  ],
  audioDestroyedAt: '18 Aug 2026, 11:42',
};

/**
 * The same screen for a meeting nobody has recorded yet — the state every
 * meeting is in until it happens, and the one the service answers with three
 * 404s. Kept as its own scene because it is the version an operator meets
 * first, and it went unlooked-at while only the populated one had a picture.
 */
export const RECORDING_NOT_RECORDED: RecordingScreenProps = {
  meetingTitle: MEETING,
  recorded: false,
  engines: [],
  agreementPercent: null,
  divergences: [],
  audioDestroyedAt: null,
};

export const DEBRIEF: DebriefScreenProps = {
  meetingTitle: MEETING,
  brief: {
    id: 'b-1',
    text: 'Northwind needs Zephyr WMS integrated with the finance ledger and the carrier portal, with same-day visibility of consignment status for operations staff.',
    provenance: 'inferred',
    citation: {
      speaker: 'Client — IT',
      at: '21:24',
      quote: 'Zephyr WMS pushes to the ledger nightly, and ops can never see where a consignment actually is.',
    },
  },
  openQuestions: [
    {
      id: 'q-1',
      text: 'What does “fast” mean for the operations dashboard, in seconds?',
      provenance: 'stated',
      citation: {
        speaker: 'Client — Ops',
        at: '08:15',
        quote: 'The dashboard just has to be fast, that is the main thing.',
      },
    },
    {
      id: 'q-2',
      text: 'Is nightly ledger sync acceptable at go-live, or is real-time required?',
      provenance: 'inferred',
      citation: {
        speaker: 'Client — IT',
        at: '21:24',
        quote: 'Zephyr WMS pushes to the ledger nightly.',
      },
    },
    {
      id: 'q-3',
      text: 'Does SLA-4 mean four hours end to end, or four hours per hop?',
      provenance: 'stated',
      citation: {
        speaker: 'Client — Ops',
        at: '31:42',
        quote: 'The SLA is four hours end to end.',
      },
    },
  ],
  decisions: [
    {
      id: 'd-1',
      text: 'Carrier portal integration is in scope for phase one.',
      provenance: 'stated',
      citation: {
        speaker: 'Client — Programme',
        at: '38:07',
        quote: 'Carrier portal has to be in the first release, that is not negotiable.',
      },
    },
    {
      id: 'd-2',
      text: 'Reporting is deferred to phase two.',
      provenance: 'stated',
      citation: {
        speaker: 'Client — Programme',
        at: '39:50',
        quote: 'Reporting can wait — we can live with exports for a while.',
      },
    },
  ],
};

export const ARC: ArcScreenProps = {
  engagement: CLIENT,
  confirmedRequirements: 24,
  standingQuestions: [
    {
      id: 'sq-1',
      text: 'What does “fast” mean for the operations dashboard, in seconds?',
      raisedIn: 'Discovery 1',
      meetingsOpen: 3,
    },
    {
      id: 'sq-2',
      text: 'Is nightly ledger sync acceptable at go-live?',
      raisedIn: 'Discovery 3',
      meetingsOpen: 1,
    },
    {
      id: 'sq-3',
      text: 'Who signs off the carrier portal data-sharing agreement?',
      raisedIn: 'Discovery 2',
      meetingsOpen: 2,
    },
  ],
  meetings: [
    {
      id: 'm-1',
      title: 'Discovery 1 — current state',
      date: '4 Aug 2026',
      sectionsCovered: 3,
      sectionsTotal: 8,
    },
    {
      id: 'm-2',
      title: 'Discovery 2 — process and people',
      date: '11 Aug 2026',
      sectionsCovered: 6,
      sectionsTotal: 8,
    },
    {
      id: 'm-3',
      title: MEETING,
      date: '18 Aug 2026',
      sectionsCovered: 7,
      sectionsTotal: 8,
    },
  ],
};

export const REPLAY: ReplayScreenProps = {
  runLabel: 'Discovery 3 — replay 4',
  precisionPercent: 82,
  precisionThreshold: 70,
  embarrassmentCount: 0,
  // A rate is unreadable without what it was taken over: 82% of 4 ratings and
  // 82% of 400 do not mean the same thing to somebody deciding on a release.
  ratedCount: 44,
  usefulCount: 36,
  suggestions: [
    {
      id: 's-1',
      at: '08:19',
      text: 'When you say fast, what does that mean in seconds?',
      language: 'en',
      rating: 'useful',
    },
    {
      id: 's-2',
      at: '14:02',
      text: 'How many consignments a day at peak?',
      language: 'en',
      rating: 'useful',
    },
    {
      id: 's-3',
      at: '19:38',
      text: 'Could you expand on that?',
      language: 'en',
      rating: 'not useful',
    },
    {
      id: 's-4',
      at: '21:31',
      text: 'Is the nightly sync a constraint or a choice?',
      language: 'en',
      rating: null,
    },
  ],
};

/** A run that fails M2, so the gate reads as a real gate rather than decoration. */
export const REPLAY_FAILING: ReplayScreenProps = {
  ...REPLAY,
  runLabel: 'Discovery 3 — replay 2',
  precisionPercent: 64,
  embarrassmentCount: 1,
  ratedCount: 44,
  usefulCount: 28,
  suggestions: [
    ...REPLAY.suggestions.slice(0, 3),
    {
      id: 's-5',
      at: '26:10',
      text: 'Has the client considered whether this project is viable at all?',
      language: 'en',
      rating: 'embarrassing',
    },
  ],
};

// --- Journey 11: capture control ------------------------------------------


/**
 * A speech-shaped level history for the capture screen's meter.
 *
 * Generated from a fixed formula rather than sampled or randomised, because
 * these scenes are what the documentation screenshots are taken from: a wave
 * that differed between runs would put every chapter that shows this screen
 * into drift on every build.
 */
const SPEECH_WAVE: readonly number[] = Array.from({ length: 48 }, (_, index) =>
  Math.max(0.06, Math.min(0.94, 0.52 + 0.42 * Math.sin(index / 2.1) * Math.sin(index / 7.3))),
);

export const CAPTURING: CaptureScreenProps = {
  state: 'capturing',
  elapsed: '23:41',
  metering: { level: { rms: 0.06, peak: 0.21 }, waveform: SPEECH_WAVE },
  sources: [
    { label: 'USB interface — line-in from the meeting machine', kind: 'wired', active: true },
    { label: 'Loopback from a silent join', kind: 'loopback', active: false },
    { label: 'Built-in microphone', kind: 'acoustic', active: false },
  ],
  operatorEnrolled: true,
  enrolmentSeconds: 48,
};

/**
 * Paused reads a flat zero, and that is the point of showing it here: the
 * meter is the operator's own confirmation that the pause landed, independent
 * of the banner that claims it.
 */
export const PAUSED: CaptureScreenProps = {
  ...CAPTURING,
  state: 'paused',
  elapsed: '23:41',
  metering: { level: { rms: 0, peak: 0 }, waveform: SPEECH_WAVE.map(() => 0) },
};

/**
 * The green room, before anything is recorded.
 *
 * A browser withholds device ids *and* labels until the first permission
 * grant, so the picker before this step reads "Microphone 1" and is not a
 * choice at all; checking is what fills it in. It is also the operator's one
 * chance to see sound arriving before the choice becomes binding — capture
 * refuses to start a second session on either backend, so changing input
 * afterwards means stopping and restarting.
 */
export const CHECKING: CaptureScreenProps = {
  ...CAPTURING,
  state: 'checking',
  elapsed: '00:00',
  metering: { level: { rms: 0.05, peak: 0.18 }, waveform: SPEECH_WAVE },
};

/** The degraded input path, which the screen is expected to argue against. */
export const CAPTURING_ACOUSTIC: CaptureScreenProps = {
  ...CAPTURING,
  sources: [
    { label: 'USB interface — line-in from the meeting machine', kind: 'wired', active: false },
    { label: 'Loopback from a silent join', kind: 'loopback', active: false },
    { label: 'Built-in microphone', kind: 'acoustic', active: true },
  ],
  operatorEnrolled: false,
  enrolmentSeconds: 0,
};

// --- Journey 12: install and roll out -------------------------------------


export const ABOUT_MANAGED: AboutScreenProps = {
  version: '0.1.0 (build 274)',
  platform: 'macOS 15.3',
  architecture: 'universal',
  signed: true,
  signedBy: 'Developer ID — Northwind Consulting Pty Ltd',
  installedVia: 'MDM',
  updateChannel: 'Managed by your IT team',
  permissions: [
    { name: 'Microphone', granted: true, why: 'Captures the meeting audio.' },
    {
      name: 'Screen Recording',
      granted: true,
      why: 'Required by macOS for loopback capture of a silent join.',
    },
  ],
};

export const ABOUT_UNMANAGED: AboutScreenProps = {
  ...ABOUT_MANAGED,
  platform: 'Windows 11',
  architecture: 'x64',
  installedVia: 'Direct download',
  updateChannel: 'Checks weekly',
  permissions: [
    { name: 'Microphone', granted: true, why: 'Captures the meeting audio.' },
    {
      name: 'Screen Recording',
      granted: false,
      why: 'Required for loopback capture of a silent join.',
    },
  ],
};

/**
 * A debrief conversation two turns in (FR-7.3).
 *
 * The answer quotes and attributes rather than summarising, because the whole
 * claim of this screen is that what it tells you can be checked against what
 * was actually said.
 */
export const DEBRIEF_CHAT = {
  meetingTitle: 'Northwind Logistics — Discovery 2',
  turns: [
    { role: 'user' as const, text: 'What did they actually say about the March deadline?' },
    {
      role: 'assistant' as const,
      text: 'Priya Raman (Ops, 08:15) said “the pilot has to be live before the March peak — after that nobody has time to look at it.” She did not give a date, so March 31 is inferred from “before the March peak”, not stated. It is still an open question.',
    },
    { role: 'user' as const, text: 'Draft the follow-up paragraph about integrations.' },
    {
      role: 'assistant' as const,
      text: 'Suggested: “As discussed, the pilot covers the dispatch and telematics feeds only. The warehouse management system is out of scope for this phase — we agreed to revisit it once the dispatch integration is stable.” This rests on Dan Okoro (IT, 22:40) and the scope note in your engagement brief.',
    },
  ],
  busy: false,
  error: null,
  started: true,
};

/** The same screen before anything has been asked — the blank-page state. */
export const DEBRIEF_CHAT_EMPTY = {
  ...DEBRIEF_CHAT,
  turns: [],
};
