import type { PanelState } from '../features/panel/route';

/**
 * Fixture state for journey screenshots.
 *
 * Kept out of the product entry on purpose: this is documentation scaffolding,
 * and a demo fixture that can reach production code is how a stub ends up in
 * front of a client. The panel takes its state as props, so nothing here is a
 * special case inside the component itself.
 *
 * The content is deliberately realistic — a logistics discovery meeting with a
 * vague adjective in it — because a screenshot of lorem ipsum documents
 * nothing about what the operator is meant to notice.
 */
const NOW = 1_755_600_000_000;

/**
 * What the room has said, for the scenes that are mid-meeting.
 *
 * Both speakers, and one line that earns no question at all — that is most of
 * a requirements meeting (FR-5.7), and it is the case the transcript was added
 * for: before it, a panel with nothing to ask looked exactly like a microphone
 * that had stopped.
 */
const HEARD = [
  { seq: 0, text: 'So how are arrivals booked in today?', speaker: 'operator', at: NOW - 62_000 },
  {
    seq: 1,
    // `other`, not `client`. Live verification answers exactly three things —
    // the operator, not-the-operator, or it could not tell — so a screenshot
    // showing "Client" would document a label the product cannot produce.
    // These pictures are the handbook's, and a fixture that flatters the
    // feature is a lie told to a reader who cannot check it.
    text: 'The haulier phones the gate office and someone writes it on the whiteboard.',
    speaker: 'other',
    at: NOW - 54_000,
  },
  // Nobody enrolled is the ordinary deployment, so an unattributed line
  // belongs in the picture too.
  { seq: 2, text: 'And the dashboard just has to be fast.', speaker: null, at: NOW - 4_000 },
];

/**
 * The bank, as the rail offers it.
 *
 * Stubs of three or four words, which is the whole point of the rail: the
 * phrasings beneath them run to a hundred characters and cannot be read
 * without breaking eye contact. One is carried forward from the last meeting,
 * which the rail marks — it is a question the client has already left
 * unanswered once.
 */
const BANK = [
  {
    id: 'c-1',
    stub: 'Monthly arrivals',
    phrasing: 'How many arrivals do you handle in a month, across all three sites?',
    priority: 1,
    templateSection: 'Volumes',
    inherited: false,
  },
  {
    id: 'c-2',
    stub: 'Late vessel, booking',
    phrasing: 'What happens to a booking when a vessel is late — does the slot hold, move, or go back to the pool?',
    priority: 2,
    templateSection: 'Exceptions',
    inherited: true,
  },
  {
    id: 'c-3',
    stub: 'Whiteboard, who reads it',
    phrasing: 'Who else needs to see what is on that whiteboard, and how do they see it today?',
    priority: 3,
    templateSection: 'Integrations',
    inherited: false,
  },
];

export const BEFORE_MEETING: PanelState = {
  active: null,
  history: [],
  coverage: {
    slots: [
      { id: 'performance', label: 'Performance', filled: false },
      { id: 'integrations', label: 'Integrations', filled: false },
      { id: 'volumes', label: 'Volumes', filled: false },
      { id: 'compliance', label: 'Compliance', filled: false },
    ],
    timeRemainingMs: 45 * 60 * 1000,
  },
  // Before anyone speaks, the strip shows what Elicta is *listening for* —
  // derived from the client background when the engagement was made. Nothing
  // has been heard, so nothing carries a support badge.
  languages: [
    { language: 'en', tier: null, heard: false },
    { language: 'zh', tier: null, heard: false },
  ],
  // The bank is compiled before the meeting, so it is on the rail from the
  // moment the panel opens — that is what makes it reachable without leaving
  // the screen once the meeting starts. Nothing has been heard yet.
  bankQuestions: BANK,
  transcript: [],
};

/**
 * A frozen half-second of input, for the recording bar's wave.
 *
 * Written out rather than generated, so the picture in the handbook and the
 * one the accessibility audit measures are the same picture every run. Shaped
 * like real speech — a syllable rising and falling — because a flat row reads
 * as a dead microphone and a random row reads as noise.
 */
const WAVE: readonly number[] = [
  0.08, 0.14, 0.31, 0.52, 0.71, 0.83, 0.74, 0.55, 0.38, 0.24, 0.16, 0.29,
  0.47, 0.66, 0.79, 0.88, 0.72, 0.51, 0.33, 0.19, 0.11, 0.07, 0.13, 0.22,
];

export const NUDGE_SURFACED: PanelState = {
  active: {
    id: 'nudge-1',
    stub: 'How fast is fast?',
    question: 'When you say the dashboard has to be fast — what does that mean in seconds?',
    triggerReason: 'unquantified adjective — "fast"',
    createdAt: NOW,
  },
  history: [],
  coverage: {
    slots: [
      { id: 'performance', label: 'Performance', filled: false },
      { id: 'integrations', label: 'Integrations', filled: true },
      { id: 'volumes', label: 'Volumes', filled: false },
      { id: 'compliance', label: 'Compliance', filled: false },
    ],
    timeRemainingMs: 22 * 60 * 1000,
  },
  languages: [{ language: 'en', tier: 'tier-1', heard: true, confidence: 0.97 }],
  transcript: HEARD,
  // The question the nudge came from is gone from the rail: it is live above,
  // and the rail is what to ask next.
  bankQuestions: BANK,
  // Eight and a half minutes in, which is what the recording bar reads. A
  // duration, not an instant: a scene is frozen and a real clock is not, so an
  // absolute timestamp here reads as the fixture's age — it showed
  // `9098:09:34` before this was a duration.
  capturingForMs: 508_000,
  waveform: WAVE,
  // Named in the scene so the journey screenshots and the audit draw the
  // label at all — and a cloud model here against the local one in the
  // code-switched scene, so both readings are measured.
  liveModel: 'nova-3',
};


export const CODE_SWITCHED: PanelState = {
  active: {
    id: 'nudge-2',
    stub: 'How many, exactly?',
    question: 'You mentioned 三百五十万 orders — is that 3,500,000 a year or a month?',
    triggerReason: 'unquantified quantity — numeral grouping',
    createdAt: NOW,
  },
  history: [NUDGE_SURFACED.active!],
  coverage: NUDGE_SURFACED.coverage,
  languages: [
    { language: 'en', tier: 'tier-1', heard: true, confidence: 0.94 },
    { language: 'zh', tier: 'tier-1', heard: true, confidence: 0.89 },
  ],
  activeTier: 'tier-1',
  capturingForMs: 508_000,
  // The other half of the control. `nudge-surfaced` draws Pause and this
  // draws Resume, so both labels and both grounds are measured — a state the
  // audit never visits is one it reports clean without drawing.
  waveform: WAVE,
  paused: true,
  liveModel: 'whisper-small',
  transcript: [
    ...HEARD,
    {
      seq: 3,
      text: '我们一年大概三百五十万单。',
      speaker: 'other',
      at: NOW - 2_000,
    },
  ],
  bankQuestions: BANK,
};

/** Journey 5 — the model is unreachable and the panel says so. */
export const DEGRADED: PanelState = {
  ...NUDGE_SURFACED,
  modelReachable: false,
  // A refused credential rather than a bare outage, because it is the reason
  // an operator can do something about — and the one a banner reading only
  // "the model is unreachable" would send them looking for the wrong fix.
  degradedReason: 'The AI provider refused the configured credential. Re-enter it in Settings.',
};

/**
 * Capture is running and nothing will be written down.
 *
 * A state with no colour of its own until now, and one an operator cannot
 * diagnose from the panel: "Nothing heard yet." covers a quiet room, a stopped
 * microphone and a deployment that never bought speech. It is a scene so the
 * accessibility audit can see the notice at all — a state no scene renders is
 * a state whose contrast is never checked, which is how the transcript and the
 * bank rail were nearly shipped unaudited.
 */
export const TRANSCRIPTION_OFF: PanelState = {
  ...BEFORE_MEETING,
  transcript: [],
  liveTranscription: false,
};

export const SCENES: Record<string, PanelState> = {
  'before-meeting': BEFORE_MEETING,
  'transcription-off': TRANSCRIPTION_OFF,
  'nudge-surfaced': NUDGE_SURFACED,
  'code-switched': CODE_SWITCHED,
  degraded: DEGRADED,
};
