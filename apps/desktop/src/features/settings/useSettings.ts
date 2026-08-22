import { useCallback, useEffect, useState } from 'react';

import { getApiClient, type ApiClient } from '../../services/apiClient';

export type SecretKey =
  | 'anthropic_api_key'
  | 'anthropic_oauth_token'
  | 'asr_vendor_api_key'
  | 'capture_vendor_api_key'
  | 'microsoft_graph_client_secret'
  | 'state_database_url';

/**
 * Which credential the service authenticates Claude calls with. Both are
 * bring-your-own: an API key from the console, or an OAuth token from
 * `claude setup-token`. Which one an operator has depends on how their
 * organisation issues access.
 */
export type AuthMode = 'api_key' | 'oauth_token';

export const AUTH_MODE_SECRET: Record<AuthMode, SecretKey> = {
  api_key: 'anthropic_api_key',
  oauth_token: 'anthropic_oauth_token',
};

export interface SecretStatus {
  readonly key: SecretKey;
  readonly configured: boolean;
  readonly hint: string | null;
}

export type SpeechVendor = 'deepgram' | 'assemblyai' | 'custom';

/**
 * Where Claude calls are routed. Every option speaks the Anthropic Messages
 * API — that is a constraint, not a gap. The service depends on structured
 * outputs and cache-boundary control that only exist on that surface, so an
 * OpenAI-shaped endpoint would fail per stage rather than at setup.
 */
export type LlmProvider =
  | 'anthropic'
  | 'bedrock'
  | 'vertex'
  | 'foundry'
  | 'anthropic_compatible';

export interface InferenceSettings {
  model: string;
  base_url: string | null;
  auth_mode: AuthMode;
  provider: LlmProvider;
  region: string | null;
  project_id: string | null;
  resource: string | null;
}

export interface ConnectorSettings {
  readonly custom_vendor_name?: string | null;
  readonly custom_base_url?: string | null;
  readonly live_vendor: SpeechVendor;
  readonly record_vendors: readonly SpeechVendor[];
  readonly keyterm_prompting: boolean;
  readonly disable_vendor_retention: boolean;
  readonly region: string | null;
}

/**
 * The app registration a linked SharePoint or OneDrive document is read
 * through. Identifiers, not credentials — the secret half is
 * `microsoft_graph_client_secret`, and is write-only like every other secret
 * here.
 */
export interface DocumentSourceSettings {
  readonly tenant_id: string | null;
  readonly client_id: string | null;
}

/**
 * Where an engagement's memory is kept. `database` is read-only and already
 * has any password stripped out of it; moving a deployment means saving the
 * `state_database_url` secret, which is write-only like every other one.
 */
export interface StorageSettings {
  readonly database: string;
  readonly applies_on_restart: boolean;
}

/**
 * Whether a meeting stops to confirm consent before capture.
 *
 * `engagement_level` is the default and the permissive one: the gate answers
 * "not required", no meeting shows the prompt, and no consent record is
 * written. It says the organisation holds consent for the engagement as a
 * whole — it does not establish that, and nothing here can check it.
 */
export type ConsentModelSetting = 'per_meeting' | 'engagement_level';

export interface ConsentSettings {
  readonly model: ConsentModelSetting;
}

export interface ServiceSettings {
  readonly inference: InferenceSettings;
  readonly vendors: { asr_base_url: string | null; capture_base_url: string | null };
  readonly connectors: ConnectorSettings;
  readonly documents?: DocumentSourceSettings;
  readonly storage?: StorageSettings;
  readonly consent?: ConsentSettings;
  readonly secrets: readonly SecretStatus[];
  readonly durable: boolean;
}

export interface SettingsDraft {
  readonly inference?: InferenceSettings;
  readonly vendors?: { asr_base_url: string | null; capture_base_url: string | null };
  /**
   * Only the secrets the operator actually typed into. A key absent here is
   * left alone by the service; an empty string clears it. The form must never
   * send back a value it did not receive from the operator, because it never
   * receives the stored one -- it only ever sees a four-character hint.
   */
  readonly connectors?: ConnectorSettings;
  readonly documents?: DocumentSourceSettings;
  readonly consent?: ConsentSettings;
  readonly secrets?: readonly { key: SecretKey; value: string }[];
}

export interface UseSettingsResult {
  readonly settings: ServiceSettings | null;
  readonly loading: boolean;
  readonly saving: boolean;
  readonly error: string | null;
  readonly save: (draft: SettingsDraft) => Promise<boolean>;
  readonly test: (key: SecretKey) => Promise<string>;
}

/**
 * Loads and saves the service's operator-administered settings.
 *
 * The service is the store, not this hook: after every save the returned
 * settings come from the response rather than from an optimistic local merge,
 * so the secret hints on screen always reflect what the service actually
 * holds. Guessing them locally is impossible anyway -- the client never sees
 * a secret value.
 */
export function useSettings(client: ApiClient = getApiClient()): UseSettingsResult {
  const [settings, setSettings] = useState<ServiceSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data, error: failure } = await client.GET('/api/admin/settings', {});
      if (failure || !data) {
        setError('Could not load settings from the service.');
      } else {
        setSettings(data as unknown as ServiceSettings);
        setError(null);
      }
    } catch {
      setError('The service is unreachable. Check that it is running.');
    } finally {
      setLoading(false);
    }
  }, [client]);

  useEffect(() => {
    void load();
  }, [load]);

  const save = useCallback(
    async (draft: SettingsDraft): Promise<boolean> => {
      setSaving(true);
      try {
        const { data, error: failure } = await client.PUT('/api/admin/settings', {
          body: draft as never,
        });
        if (failure || !data) {
          setError('The service rejected these settings.');
          return false;
        }
        setSettings(data as unknown as ServiceSettings);
        setError(null);
        return true;
      } catch {
        setError('The service is unreachable. Your changes were not saved.');
        return false;
      } finally {
        setSaving(false);
      }
    },
    [client],
  );

  const test = useCallback(
    async (key: SecretKey): Promise<string> => {
      try {
        const { data } = await client.POST('/api/admin/settings/{key}/test', {
          params: { path: { key } },
        });
        return data ? (data as { detail: string }).detail : 'Could not test this credential.';
      } catch {
        return 'The service is unreachable.';
      }
    },
    [client],
  );

  return { settings, loading, saving, error, save, test };
}
