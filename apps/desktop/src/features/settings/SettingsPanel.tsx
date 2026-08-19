import { useState } from 'react';

import './SettingsPanel.css';
import {
  AUTH_MODE_SECRET,
  useSettings,
  type AuthMode,
  type ConnectorSettings,
  type SpeechVendor,
  type SecretKey,
  type SecretStatus,
  type UseSettingsResult,
} from './useSettings';


/**
 * What each vendor is good at, in the operator's terms. Shown inline because
 * the choice is not obvious from the names, and picking the wrong engine for
 * the live path costs latency the meeting cannot spare.
 */
const VENDOR_LABELS: Record<SpeechVendor, string> = {
  assemblyai: 'AssemblyAI',
  deepgram: 'Deepgram',
};

const LIVE_VENDOR_NOTE: Record<SpeechVendor, string> = {
  assemblyai: 'Ends a turn when the sentence sounds finished, which cuts the wait before a nudge.',
  deepgram: 'Ends a turn after a fixed silence. Predictable, but slower to react.',
};

const SECRET_LABELS: Record<SecretKey, string> = {
  anthropic_api_key: 'Anthropic API key',
  anthropic_oauth_token: 'Anthropic OAuth token',
  asr_vendor_api_key: 'Speech-to-text vendor key',
  capture_vendor_api_key: 'Managed capture vendor key',
};

const SECRET_HELP: Record<SecretKey, string> = {
  anthropic_api_key: 'A key issued from the Anthropic console (starts sk-ant-).',
  anthropic_oauth_token: 'A token from `claude setup-token`, if your organisation issues those instead of keys.',
  asr_vendor_api_key: 'Used to transcribe the meeting on both the live and record paths.',
  capture_vendor_api_key: 'Used to join the meeting and capture per-participant audio.',
};

function SecretField({
  status,
  value,
  onChange,
  onClear,
  onTest,
  result,
  inUse = false,
}: {
  status: SecretStatus;
  value: string;
  onChange: (next: string) => void;
  onClear: () => void;
  onTest: () => void;
  result: string | undefined;
  inUse?: boolean;
}) {
  const label = SECRET_LABELS[status.key];
  return (
    <div className="settings-field">
      <div className="settings-label-row">
        {/* The badge sits outside the label on purpose: an input's accessible
            name must not change as state changes, or every assistive
            technology announces a different field than the one before. */}
        <label htmlFor={status.key}>{label}</label>
        {inUse ? <span className="settings-inuse">in use</span> : null}
      </div>
      <p className="settings-help">{SECRET_HELP[status.key]}</p>
      <div className="settings-secret-row">
        <input
          id={status.key}
          type="password"
          autoComplete="off"
          spellCheck={false}
          value={value}
          placeholder={
            status.configured ? `Configured — ends ${status.hint}` : 'Not configured'
          }
          onChange={(event) => onChange(event.target.value)}
          aria-describedby={`${status.key}-state`}
        />
        <button type="button" onClick={onTest} disabled={!status.configured}>
          Test
        </button>
        {status.configured ? (
          <button type="button" className="settings-danger" onClick={onClear}>
            Clear
          </button>
        ) : null}
      </div>
      <p id={`${status.key}-state`} className="settings-state">
        {result ??
          (status.configured
            ? `A key is stored. Leave this blank to keep it.`
            : 'No key is stored yet.')}
      </p>
    </div>
  );
}

/**
 * The operator's admin screen for vendor credentials and endpoints.
 *
 * Three rules shape this form, and each exists because of how secrets work:
 *
 * 1. A secret input always starts empty. The service never returns a stored
 *    key, so there is nothing to prefill -- the placeholder carries the last
 *    four characters instead, which is enough to tell one key from another.
 * 2. Leaving a secret blank means "leave it alone". Only fields the operator
 *    typed into are sent, so saving the model name cannot wipe a key.
 * 3. Clearing is a separate, explicit action, because it is not recoverable.
 */
export function SettingsPanel({ controller }: { controller?: UseSettingsResult } = {}) {
  const fallback = useSettings();
  const { settings, loading, saving, error, save, test } = controller ?? fallback;

  const [secretDrafts, setSecretDrafts] = useState<Partial<Record<SecretKey, string>>>({});
  const [model, setModel] = useState<string | null>(null);
  const [authMode, setAuthMode] = useState<AuthMode | null>(null);
  const [connectors, setConnectors] = useState<ConnectorSettings | null>(null);
  const [testResults, setTestResults] = useState<Partial<Record<SecretKey, string>>>({});
  const [saved, setSaved] = useState(false);

  if (loading) {
    return <p className="settings-loading">Loading settings…</p>;
  }

  if (!settings) {
    return (
      <div className="settings-panel" role="alert">
        <p className="settings-error">{error ?? 'Settings are unavailable.'}</p>
      </div>
    );
  }

  const currentModel = model ?? settings.inference.model;
  const currentAuthMode = authMode ?? settings.inference.auth_mode;
  const activeSecret = AUTH_MODE_SECRET[currentAuthMode];
  const currentConnectors = connectors ?? settings.connectors;

  const onSave = async () => {
    const secrets = Object.entries(secretDrafts)
      .filter(([, value]) => value !== undefined && value !== '')
      .map(([key, value]) => ({ key: key as SecretKey, value: value as string }));

    const ok = await save({
      inference: {
        model: currentModel,
        base_url: settings.inference.base_url,
        auth_mode: currentAuthMode,
      },
      connectors: currentConnectors,
      ...(secrets.length > 0 ? { secrets } : {}),
    });

    if (ok) {
      setSecretDrafts({});
      setSaved(true);
    }
  };

  const onClear = async (key: SecretKey) => {
    await save({ secrets: [{ key, value: '' }] });
    setSecretDrafts((current) => ({ ...current, [key]: undefined }));
  };

  const onTest = async (key: SecretKey) => {
    setTestResults((current) => ({ ...current, [key]: 'Testing…' }));
    const detail = await test(key);
    setTestResults((current) => ({ ...current, [key]: detail }));
  };

  return (
    <section className="settings-panel" aria-labelledby="settings-heading">
      <h1 id="settings-heading">Settings</h1>

      {settings.durable ? null : (
        <p className="settings-warning" role="status">
          These settings are held in memory and will be lost when the service
          restarts.
        </p>
      )}

      {error ? (
        <p className="settings-error" role="alert">
          {error}
        </p>
      ) : null}

      <h2>Credentials</h2>
      <fieldset className="settings-field">
        <legend>Authenticate with</legend>
        <p className="settings-help">
          Bring your own credential. Use whichever your organisation issues — a
          key or a token, not both.
        </p>
        {(['api_key', 'oauth_token'] as const).map((mode) => (
          <label key={mode} className="settings-radio">
            <input
              type="radio"
              name="auth-mode"
              value={mode}
              checked={currentAuthMode === mode}
              onChange={() => setAuthMode(mode)}
            />
            {mode === 'api_key' ? 'API key' : 'OAuth token'}
          </label>
        ))}
      </fieldset>
      {settings.secrets.map((status) => (
        <SecretField
          key={status.key}
          status={status}
          value={secretDrafts[status.key] ?? ''}
          onChange={(next) =>
            setSecretDrafts((current) => ({ ...current, [status.key]: next }))
          }
          onClear={() => void onClear(status.key)}
          onTest={() => void onTest(status.key)}
          result={testResults[status.key]}
          inUse={status.key === activeSecret}
        />
      ))}

      <h2>Inference</h2>
      <div className="settings-field">
        <label htmlFor="model">Model</label>
        <p className="settings-help">
          Used for the context compiler and the debrief pipeline.
        </p>
        <input
          id="model"
          type="text"
          value={currentModel}
          onChange={(event) => setModel(event.target.value)}
        />
      </div>

      <h2>Speech vendors</h2>
      <div className="settings-field">
        <label htmlFor="live-vendor">Live transcription</label>
        <p className="settings-help">
          Drives the in-meeting nudges. {LIVE_VENDOR_NOTE[currentConnectors.live_vendor]}
        </p>
        <select
          id="live-vendor"
          value={currentConnectors.live_vendor}
          onChange={(event) =>
            setConnectors({
              ...currentConnectors,
              live_vendor: event.target.value as SpeechVendor,
            })
          }
        >
          {(['assemblyai', 'deepgram'] as const).map((vendor) => (
            <option key={vendor} value={vendor}>
              {VENDOR_LABELS[vendor]}
            </option>
          ))}
        </select>
      </div>

      <div className="settings-field">
        <span className="settings-pseudo-label">Recording transcription</span>
        <p className="settings-help">
          Two engines transcribe the recording separately after the meeting;
          where they disagree is flagged for you to check. They must be
          different vendors — the same engine twice would always agree with
          itself.
        </p>
        <p className="settings-state">
          {currentConnectors.record_vendors
            .map((vendor) => VENDOR_LABELS[vendor])
            .join(' + ')}
        </p>
      </div>

      <div className="settings-field">
        <label className="settings-check">
          <input
            type="checkbox"
            checked={currentConnectors.keyterm_prompting}
            onChange={(event) =>
              setConnectors({
                ...currentConnectors,
                keyterm_prompting: event.target.checked,
              })
            }
          />
          Send engagement vocabulary to the transcriber
        </label>
        <p className="settings-help">
          Client and product names are transcribed far more accurately when the
          engine is told about them in advance.
        </p>
      </div>

      <div className="settings-field">
        <label className="settings-check">
          <input
            type="checkbox"
            checked={currentConnectors.disable_vendor_retention}
            onChange={(event) =>
              setConnectors({
                ...currentConnectors,
                disable_vendor_retention: event.target.checked,
              })
            }
          />
          Tell vendors not to retain client audio
        </label>
        <p className="settings-help">
          Sets the opt-out on every request. Your contract may already say
          this; sending it per request is what an audit can verify.
        </p>
      </div>

      <div className="settings-field">
        <label htmlFor="region">Region</label>
        <p className="settings-help">
          Where audio is processed. Pin it to the region your engagement
          requires; closer regions also respond faster.
        </p>
        <input
          id="region"
          type="text"
          value={currentConnectors.region ?? ''}
          placeholder="Vendor default"
          onChange={(event) =>
            setConnectors({
              ...currentConnectors,
              region: event.target.value || null,
            })
          }
        />
      </div>

      <div className="settings-actions">
        <button type="button" onClick={() => void onSave()} disabled={saving}>
          {saving ? 'Saving…' : 'Save'}
        </button>
        {saved && !saving ? <span className="settings-saved">Saved</span> : null}
      </div>
    </section>
  );
}
