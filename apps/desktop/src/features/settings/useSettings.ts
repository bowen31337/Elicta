import type { CapabilityReadiness } from './ReadinessWarnings';

import { useCallback, useEffect, useState } from 'react';

import { getApiClient, type ApiClient } from '../../services/apiClient';

export type SecretKey =
  | 'anthropic_api_key'
  | 'anthropic_oauth_token'
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

export type SpeechVendor = 'deepgram' | 'assemblyai' | 'gemini' | 'custom';

/**
 * How the pool picks which key serves the next request.
 *
 * `single` names one and uses it until told otherwise. `rotate` moves through
 * the enabled keys in order, which is what spreads a meeting's load across
 * several accounts rather than exhausting one.
 */
export type SelectionPolicy = 'single' | 'rotate';

export interface SpeechCredential {
  readonly id: string;
  readonly vendor: SpeechVendor;
  readonly label: string;
  readonly enabled: boolean;
}

export interface SpeechCredentialPool {
  readonly credentials: readonly SpeechCredential[];
  readonly policy: SelectionPolicy;
  readonly active_id: string | null;
}

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

/**
 * Which recogniser the live path runs on.
 *
 * The live path's one selector: a cloud model resolves its key through the
 * credential pool, a local model needs no key and resolves an address
 * instead. Kept as a union of the wire strings rather than a lookup, because
 * the service holds the same closed set and a value outside it is a request
 * the vendor refuses mid-meeting.
 */
export type LiveSpeechModel =
  | 'flux-general-en'
  | 'flux-general-multi'
  | 'nova-3'
  | 'nova-2'
  | 'enhanced'
  | 'whisper-large-v3-turbo'
  | 'whisper-medium'
  | 'whisper-small'
  | 'parakeet-tdt-0.6b-v2';

/**
 * The models driven over a socket rather than a request per fixed window.
 *
 * Not a preference: Flux is `/v2/listen`-only and a Nova model on that
 * endpoint never produces a turn, so the model decides the transport. The
 * same set is held in the service and asserted equal there.
 */
export const STREAMED_LIVE_MODELS: readonly LiveSpeechModel[] = [
  'flux-general-en',
  'flux-general-multi',
];

export function isStreamed(model: LiveSpeechModel): boolean {
  return STREAMED_LIVE_MODELS.includes(model);
}

/** The models that transcribe on this machine, sending no audio anywhere. */
export const LOCAL_LIVE_MODELS: readonly LiveSpeechModel[] = [
  'whisper-large-v3-turbo',
  'whisper-medium',
  'whisper-small',
  'parakeet-tdt-0.6b-v2',
];

export function runsLocally(model: LiveSpeechModel): boolean {
  return LOCAL_LIVE_MODELS.includes(model);
}

/**
 * Only Nova-3 accepts keyterms, so the engagement vocabulary reaches the
 * transcriber on that model and no other. The service already drops the
 * parameter rather than sending it to be ignored; this is what lets the
 * screen say so, instead of leaving the switch above it quietly inert.
 */
export function takesVocabulary(model: LiveSpeechModel): boolean {
  return model === 'nova-3';
}

export interface ConnectorSettings {
  readonly custom_vendor_name?: string | null;
  readonly custom_base_url?: string | null;
  readonly record_vendors: readonly SpeechVendor[];
  readonly live_model: LiveSpeechModel;
  readonly local_asr_base_url: string | null;
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
  /**
   * The speech keys, and which one serves. Not part of `secrets` because
   * these are not one named field each: there are as many as the operator
   * has, and they are added and removed rather than overwritten.
   */
  readonly speech?: SpeechCredentialPool;
  readonly documents?: DocumentSourceSettings;
  readonly storage?: StorageSettings;
  readonly consent?: ConsentSettings;
  readonly secrets: readonly SecretStatus[];
  /**
   * What cannot run, and what it costs. Computed by the service from the
   * secrets and the modes actually selected, so the screen never has to know
   * which key matters for which capability — a rule that lived only in the
   * composition root, where no operator could read it.
   */
  readonly readiness?: readonly CapabilityReadiness[];
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
  /**
   * The four pool operations. Unlike everything else on this screen they
   * apply the moment they are called rather than waiting for Save, because
   * each is its own request — there is no field on the settings body that
   * could carry "one more key" alongside the rest of the form.
   *
   * Each returns null on success and a sentence to show the operator
   * otherwise, and reloads the settings so the list on screen is the
   * service's, never an optimistic guess.
   */
  readonly addSpeechKey: (
    vendor: SpeechVendor,
    label: string,
    value: string,
  ) => Promise<string | null>;
  readonly setSpeechKeyEnabled: (id: string, enabled: boolean) => Promise<string | null>;
  readonly removeSpeechKey: (id: string) => Promise<string | null>;
  readonly setSpeechPolicy: (policy: SelectionPolicy) => Promise<string | null>;
  /**
   * The verdict on one key, in a sentence to show beside it. Unlike the other
   * four this changes nothing, so it does not reload the settings.
   */
  readonly testSpeechKey: (id: string) => Promise<string>;
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

  /**
   * One request, then a reload. The reload is the point: the pool the screen
   * shows after a change is the one the service holds, so a rejected write
   * cannot leave a key rendered that is not there.
   */
  const poolWrite = useCallback(
    async (send: () => Promise<{ error?: unknown }>): Promise<string | null> => {
      try {
        const { error: failure } = await send();
        if (failure) return 'The service rejected that change.';
        await load();
        return null;
      } catch {
        return 'The service is unreachable. Nothing was changed.';
      }
    },
    [load],
  );

  const addSpeechKey = useCallback(
    (vendor: SpeechVendor, label: string, value: string) =>
      poolWrite(() =>
        client.POST('/api/admin/settings/speech/credentials', {
          body: { vendor, label, value } as never,
        }),
      ),
    [client, poolWrite],
  );

  const setSpeechKeyEnabled = useCallback(
    (id: string, enabled: boolean) =>
      poolWrite(() =>
        client.PATCH('/api/admin/settings/speech/credentials/{credential_id}', {
          params: { path: { credential_id: id } },
          body: { enabled } as never,
        }),
      ),
    [client, poolWrite],
  );

  const removeSpeechKey = useCallback(
    (id: string) =>
      poolWrite(() =>
        client.DELETE('/api/admin/settings/speech/credentials/{credential_id}', {
          params: { path: { credential_id: id } },
        }),
      ),
    [client, poolWrite],
  );

  const testSpeechKey = useCallback(
    async (id: string): Promise<string> => {
      try {
        const { data } = await client.POST(
          '/api/admin/settings/speech/credentials/{credential_id}/test',
          { params: { path: { credential_id: id } } },
        );
        return data ? (data as { detail: string }).detail : 'Could not test this key.';
      } catch {
        return 'The service is unreachable.';
      }
    },
    [client],
  );

  const setSpeechPolicy = useCallback(
    (policy: SelectionPolicy) =>
      poolWrite(() =>
        client.PUT('/api/admin/settings/speech/policy', { body: { policy } as never }),
      ),
    [client, poolWrite],
  );

  return {
    settings,
    loading,
    saving,
    error,
    save,
    test,
    addSpeechKey,
    setSpeechKeyEnabled,
    removeSpeechKey,
    testSpeechKey,
    setSpeechPolicy,
  };
}
