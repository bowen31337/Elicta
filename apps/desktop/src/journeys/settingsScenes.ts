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
    live_vendor: 'assemblyai',
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
  secrets: [
    { key: 'anthropic_api_key', configured: true, hint: 'x7q2' },
    { key: 'anthropic_oauth_token', configured: false, hint: null },
    { key: 'asr_vendor_api_key', configured: true, hint: 'k3m8' },
    { key: 'capture_vendor_api_key', configured: false, hint: null },
  ],
  durable: true,
};

const UNCONFIGURED: ServiceSettings = {
  ...BASE,
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
