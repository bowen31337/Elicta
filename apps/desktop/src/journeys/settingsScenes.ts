import type { ServiceSettings, UseSettingsResult } from '../features/settings/useSettings';

/**
 * Settings fixtures for journey screenshots.
 *
 * The controller is stubbed rather than pointed at a running service so the
 * captures are deterministic and, more importantly, so no real credential is
 * ever near a screenshot. The hints below are invented.
 */
const BASE: ServiceSettings = {
  inference: {
    model: 'claude-opus-5',
    base_url: null,
    auth_mode: 'api_key',
    provider: 'anthropic',
    region: null,
    project_id: null,
    resource: null,
  },
  vendors: { asr_base_url: null, capture_base_url: null },
  connectors: {
    record_vendors: ['deepgram', 'assemblyai'],
    keyterm_prompting: true,
    disable_vendor_retention: true,
    region: 'eu',
  },
  // A default install keeps everything in one file on the machine. Without
  // this the screenshots showed a badge claiming otherwise.
  storage: {
    database: 'sqlite:////home/you/.elicta/state.db',
    applies_on_restart: true,
  },
  // Two providers, which is what the record path's pair of engines needs and
  // what the screenshot should therefore show. One key would document a
  // half-configured install as the normal one.
  speech: {
    policy: 'single',
    active_id: 'dg',
    credentials: [
      { id: 'dg', vendor: 'deepgram', label: 'Northwind', enabled: true },
      { id: 'aai', vendor: 'assemblyai', label: 'Northwind', enabled: true },
    ],
  },
  secrets: [
    { key: 'anthropic_api_key', configured: true, hint: 'x7q2' },
    { key: 'anthropic_oauth_token', configured: false, hint: null },
    { key: 'capture_vendor_api_key', configured: false, hint: null },
  ],
  durable: true,
};

const UNCONFIGURED: ServiceSettings = {
  ...BASE,
  speech: { credentials: [], policy: 'single', active_id: null },
  secrets: BASE.secrets.map((secret) => ({ ...secret, configured: false, hint: null })),
  durable: false,
};

function controller(settings: ServiceSettings): UseSettingsResult {
  return {
    settings,
    loading: false,
    saving: false,
    error: null,
    save: async () => true,
    test: async () => 'Verified (…x7q2).',
    // A scene is a still of one state, not a working screen. These exist so
    // the component renders; nothing in a screenshot run clicks them.
    addSpeechKey: async () => null,
    setSpeechKeyEnabled: async () => null,
    removeSpeechKey: async () => null,
    testSpeechKey: async () => 'Verified (…k3m8).',
    setSpeechPolicy: async () => null,
  };
}

export const STUB_SETTINGS_CONTROLLER: Record<string, UseSettingsResult> = {
  'settings-configured': controller(BASE),
  'settings-first-run': controller(UNCONFIGURED),
  'settings-compatible': controller({
    ...BASE,
    inference: {
      ...BASE.inference,
      provider: 'anthropic_compatible',
      base_url: 'https://llm.internal/v1',
    },
  }),
};
