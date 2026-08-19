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
  languages: [],
};

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
  languages: [{ language: 'en', tier: 'tier-1', confidence: 0.97 }],
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
    { language: 'en', tier: 'tier-1', confidence: 0.94 },
    { language: 'zh', tier: 'tier-1', confidence: 0.89 },
  ],
  activeTier: 'tier-1',
};

/** Journey 5 — the model is unreachable and the panel says so. */
export const DEGRADED: PanelState = {
  ...NUDGE_SURFACED,
  modelReachable: false,
};

export const SCENES: Record<string, PanelState> = {
  'before-meeting': BEFORE_MEETING,
  'nudge-surfaced': NUDGE_SURFACED,
  'code-switched': CODE_SWITCHED,
  degraded: DEGRADED,
};
