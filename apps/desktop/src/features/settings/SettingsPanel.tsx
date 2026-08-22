import { useState } from 'react';

import './SettingsPanel.css';
import { ScreenEyebrow } from '../../ui/Mark';
import {
  AUTH_MODE_SECRET,
  useSettings,
  type AuthMode,
  type ConnectorSettings,
  type DocumentSourceSettings,
  type StorageSettings,
  type InferenceSettings,
  type LlmProvider,
  type SpeechVendor,
  type SecretKey,
  type SecretStatus,
  type UseSettingsResult,
} from './useSettings';

/**
 * Every provider here is an Anthropic Messages API surface. That is a
 * deliberate constraint: the compiler and debrief stages rely on
 * schema-enforced outputs and explicit prompt-cache boundaries that only
 * exist there, so an OpenAI-shaped endpoint would fail mid-meeting rather
 * than at setup.
 */
const PROVIDER_LABELS: Record<LlmProvider, string> = {
  anthropic: 'Anthropic',
  bedrock: 'AWS Bedrock',
  vertex: 'Google Vertex AI',
  foundry: 'Microsoft Foundry',
  anthropic_compatible: 'Other Anthropic-compatible endpoint',
};

const PROVIDER_NOTE: Record<LlmProvider, string> = {
  anthropic: 'Calls api.anthropic.com with the credential below.',
  bedrock: 'Uses your AWS role or credentials — no key needed here.',
  vertex: 'Uses your Google Cloud credentials — no key needed here.',
  foundry: 'Calls your Foundry resource with the credential below.',
  anthropic_compatible:
    'Any gateway that speaks the Anthropic Messages API, including a self-hosted one.',
};

/**
 * Bedrock and Vertex authenticate as the host — an AWS role, a Google service
 * account — so there is no key for an operator to paste. Asking for one anyway
 * is what made this screen read as four credentials that all might be needed.
 */
const PROVIDER_TAKES_KEY: Record<LlmProvider, boolean> = {
  anthropic: true,
  bedrock: false,
  vertex: false,
  foundry: true,
  anthropic_compatible: true,
};

const VENDOR_LABELS: Record<SpeechVendor, string> = {
  assemblyai: 'AssemblyAI',
  deepgram: 'Deepgram',
  custom: 'Other service',
};

const LIVE_VENDOR_NOTE: Record<SpeechVendor, string> = {
  assemblyai: 'Ends a turn when the sentence sounds finished, which cuts the wait before a nudge.',
  deepgram: 'Ends a turn after a fixed silence. Predictable, but slower to react.',
  custom: 'Your own service. Confirm it supports vocabulary prompting and retention opt-out.',
};

const ANTHROPIC_SECRET_LABEL: Record<AuthMode, string> = {
  api_key: 'Anthropic API key',
  oauth_token: 'Anthropic OAuth token',
};

const ANTHROPIC_SECRET_HELP: Record<AuthMode, string> = {
  api_key: 'A key issued from the Anthropic console (starts sk-ant-).',
  oauth_token: 'A token from `claude setup-token`, if your organisation issues those instead of keys.',
};

/**
 * The speech key is named after the vendor it belongs to.
 *
 * "Speech-to-text vendor key" sitting in a list next to two Anthropic
 * credentials is the sentence that made this screen confusing: it named a
 * category, not a thing an operator has in a browser tab. The label changes
 * with the vendor above it — a deliberate exception to the rule that a
 * field's accessible name should be stable, because here the field genuinely
 * becomes a different vendor's credential and only ever does so as the direct
 * result of the operator changing that vendor themselves.
 */
function speechKeyLabel(vendor: SpeechVendor, customName: string | null | undefined): string {
  if (vendor === 'custom') return `${customName?.trim() || 'Speech service'} key`;
  return `${VENDOR_LABELS[vendor]} key`;
}

type Tone = 'ok' | 'warn' | 'idle';

interface Readiness {
  readonly tone: Tone;
  readonly text: string;
}

const PILL_CLASS: Record<Tone, string> = {
  ok: 'pill pill--ok',
  warn: 'pill pill--warn',
  idle: 'pill',
};

/**
 * A section header that answers "is this part set up?" before the operator
 * reads a single field. The old screen could only be judged by opening four
 * password fields and comparing their placeholders.
 */
function Section({
  id,
  title,
  summary,
  status,
  children,
}: {
  id: string;
  title: string;
  summary: string;
  status: Readiness;
  children: React.ReactNode;
}) {
  return (
    <section className="settings-section" aria-labelledby={`${id}-title`}>
      <div className="settings-section-head">
        <h2 id={`${id}-title`}>{title}</h2>
        <span className={PILL_CLASS[status.tone]}>{status.text}</span>
      </div>
      <p className="settings-section-summary">{summary}</p>
      {children}
    </section>
  );
}

function SecretField({
  status,
  label,
  help,
  value,
  onChange,
  onClear,
  onTest,
  result,
  inUse = false,
}: {
  status: SecretStatus;
  label: string;
  help: string;
  value: string;
  onChange: (next: string) => void;
  onClear: () => void;
  onTest: () => void;
  result: string | undefined;
  inUse?: boolean;
}) {
  return (
    <div className="settings-field">
      <div className="settings-label-row">
        {/* The badge sits outside the label on purpose: an input's accessible
            name must not change as state changes, or every assistive
            technology announces a different field than the one before. */}
        <label htmlFor={status.key}>{label}</label>
        {inUse ? <span className="settings-inuse">in use</span> : null}
      </div>
      <p className="settings-help">{help}</p>
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
 * A credential that is stored but is not the one in use.
 *
 * Showing only the active credential is what makes the section readable, but
 * hiding a stored secret entirely would leave it on the service with no way to
 * see or remove it. So it is stated in one line, and it can be cleared.
 */
function StoredNotInUse({
  status,
  label,
  onClear,
}: {
  status: SecretStatus;
  label: string;
  onClear: () => void;
}) {
  return (
    <p className="settings-stale">
      <span>
        {label} is also stored (ends {status.hint}), and is not in use.
      </span>
      <button type="button" className="settings-danger" onClick={onClear}>
        Clear
      </button>
    </p>
  );
}

/**
 * The operator's admin screen for vendor credentials and endpoints.
 *
 * It is organised by *service*, not by kind of setting: everything Claude
 * needs in one section, everything the transcriber needs in the next. The
 * screen this replaced put all four credentials in a single "Credentials"
 * list, under an "Authenticate with" switch that only governed two of them —
 * so the natural reading was that the speech key was one of the ways to
 * authenticate Claude. A credential belongs with the thing it authenticates.
 *
 * Three rules shape the form, and each exists because of how secrets work:
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
  const [inference, setInference] = useState<InferenceSettings | null>(null);
  const [authMode, setAuthMode] = useState<AuthMode | null>(null);
  const [connectors, setConnectors] = useState<ConnectorSettings | null>(null);
  const [documents, setDocuments] = useState<DocumentSourceSettings | null>(null);
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

  const currentInference = inference ?? settings.inference;
  const currentModel = model ?? currentInference.model;
  const currentAuthMode = authMode ?? settings.inference.auth_mode;
  const activeSecret = AUTH_MODE_SECRET[currentAuthMode];
  const idleSecret = AUTH_MODE_SECRET[currentAuthMode === 'api_key' ? 'oauth_token' : 'api_key'];
  const currentConnectors = connectors ?? settings.connectors;
  const currentDocuments: DocumentSourceSettings =
    documents ?? settings.documents ?? { tenant_id: null, client_id: null };
  const storage: StorageSettings =
    settings.storage ?? { database: '', applies_on_restart: true };
  const databaseStatus = settings.secrets.find(
    (secret) => secret.key === 'state_database_url',
  );
  const graphStatus = settings.secrets.find(
    (secret) => secret.key === 'microsoft_graph_client_secret',
  );
  const documentsReadiness: Readiness =
    currentDocuments.tenant_id && currentDocuments.client_id && graphStatus?.configured
      ? { tone: 'ok', text: 'Connected' }
      // Not a warning: an engagement whose documents are all uploaded needs no
      // connector, and a badge that scolds an operator for a choice they made
      // deliberately teaches them to ignore badges.
      : { tone: 'idle', text: 'Links off' };

  const secretOf = (key: SecretKey): SecretStatus | undefined =>
    settings.secrets.find((secret) => secret.key === key);

  const takesKey = PROVIDER_TAKES_KEY[currentInference.provider];
  const activeStatus = secretOf(activeSecret);
  const idleStatus = secretOf(idleSecret);
  const speechStatus = secretOf('asr_vendor_api_key');
  const captureStatus = secretOf('capture_vendor_api_key');

  const claudeReadiness: Readiness = !takesKey
    ? { tone: 'ok', text: 'Uses this host' }
    : activeStatus?.configured
      ? { tone: 'ok', text: 'Ready' }
      : { tone: 'warn', text: 'Needs a credential' };

  const speechReadiness: Readiness = speechStatus?.configured
    ? { tone: 'ok', text: 'Ready' }
    : { tone: 'warn', text: 'Needs a key' };

  const captureReadiness: Readiness = captureStatus?.configured
    ? { tone: 'ok', text: 'Ready' }
    : { tone: 'idle', text: 'Optional' };

  const dirty =
    inference !== null ||
    model !== null ||
    authMode !== null ||
    connectors !== null ||
    Object.values(secretDrafts).some((draft) => draft !== undefined && draft !== '');

  const onSave = async () => {
    const secrets = Object.entries(secretDrafts)
      .filter(([, value]) => value !== undefined && value !== '')
      .map(([key, value]) => ({ key: key as SecretKey, value: value as string }));

    const ok = await save({
      inference: {
        ...currentInference,
        model: currentModel,
        auth_mode: currentAuthMode,
      },
      connectors: currentConnectors,
      documents: currentDocuments,
      ...(secrets.length > 0 ? { secrets } : {}),
    });

    if (ok) {
      // The service answers a save with the settings it now holds, so the form
      // drops its local overrides and reads from that. Keeping them would show
      // the operator their own draft indefinitely, including any value the
      // service normalised on the way in.
      setSecretDrafts({});
      setModel(null);
      setInference(null);
      setAuthMode(null);
      setConnectors(null);
      setDocuments(null);
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

  const secretProps = (status: SecretStatus) => ({
    status,
    value: secretDrafts[status.key] ?? '',
    onChange: (next: string) =>
      setSecretDrafts((current) => ({ ...current, [status.key]: next })),
    onClear: () => void onClear(status.key),
    onTest: () => void onTest(status.key),
    result: testResults[status.key],
  });

  return (
    <section className="settings-panel" aria-labelledby="settings-heading">
      <ScreenEyebrow>Service</ScreenEyebrow>
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

      <Section
        id="claude"
        title="Claude"
        summary="Drafts the question bank before the meeting and writes the debrief after it. Nothing during the meeting waits on it."
        status={claudeReadiness}
      >
        <div className="settings-field">
          <label htmlFor="provider">Route Claude calls through</label>
          <p className="settings-help">{PROVIDER_NOTE[currentInference.provider]}</p>
          <select
            id="provider"
            value={currentInference.provider}
            onChange={(event) =>
              setInference({
                ...currentInference,
                provider: event.target.value as LlmProvider,
              })
            }
          >
            {(
              ['anthropic', 'bedrock', 'vertex', 'foundry', 'anthropic_compatible'] as const
            ).map((provider) => (
              <option key={provider} value={provider}>
                {PROVIDER_LABELS[provider]}
              </option>
            ))}
          </select>
        </div>

        {currentInference.provider === 'anthropic_compatible' ? (
          <div className="settings-field">
            <label htmlFor="provider-base-url">Endpoint</label>
            <p className="settings-help">Must speak the Anthropic Messages API.</p>
            <input
              id="provider-base-url"
              type="text"
              value={currentInference.base_url ?? ''}
              placeholder="https://llm.internal/v1"
              onChange={(event) =>
                setInference({
                  ...currentInference,
                  base_url: event.target.value || null,
                })
              }
            />
          </div>
        ) : null}

        {currentInference.provider === 'bedrock' || currentInference.provider === 'vertex' ? (
          <div className="settings-field">
            <label htmlFor="provider-region">AI provider region</label>
            <input
              id="provider-region"
              type="text"
              value={currentInference.region ?? ''}
              placeholder={currentInference.provider === 'vertex' ? 'global' : 'us-east-1'}
              onChange={(event) =>
                setInference({ ...currentInference, region: event.target.value || null })
              }
            />
          </div>
        ) : null}

        {currentInference.provider === 'vertex' ? (
          <div className="settings-field">
            <label htmlFor="provider-project">Google Cloud project</label>
            <input
              id="provider-project"
              type="text"
              value={currentInference.project_id ?? ''}
              onChange={(event) =>
                setInference({ ...currentInference, project_id: event.target.value || null })
              }
            />
          </div>
        ) : null}

        {currentInference.provider === 'foundry' ? (
          <div className="settings-field">
            <label htmlFor="provider-resource">Foundry resource</label>
            <input
              id="provider-resource"
              type="text"
              value={currentInference.resource ?? ''}
              onChange={(event) =>
                setInference({ ...currentInference, resource: event.target.value || null })
              }
            />
          </div>
        ) : null}

        {takesKey ? (
          <>
            <fieldset className="settings-field">
              <legend>Authenticate with</legend>
              <p className="settings-help">
                Whichever your organisation issues. Only the one selected here is
                sent, and only its field is shown.
              </p>
              {/* Two mutually exclusive options with short labels is what a
                  segmented control is for, so that is what this looks like. The
                  markup stays a radio group: the input is still there, still
                  focusable and still announced as a radio — the segment is
                  painted around it rather than replacing it. */}
              <div className="settings-segmented">
                {(['api_key', 'oauth_token'] as const).map((mode) => (
                  <label key={mode} className="settings-radio">
                    <input
                      type="radio"
                      name="auth-mode"
                      value={mode}
                      checked={currentAuthMode === mode}
                      onChange={() => setAuthMode(mode)}
                    />
                    <span>{mode === 'api_key' ? 'API key' : 'OAuth token'}</span>
                  </label>
                ))}
              </div>
            </fieldset>

            {activeStatus ? (
              <SecretField
                {...secretProps(activeStatus)}
                label={ANTHROPIC_SECRET_LABEL[currentAuthMode]}
                help={ANTHROPIC_SECRET_HELP[currentAuthMode]}
                // Measured against the *saved* mode, and only for a
                // credential that actually exists. A mode the operator has
                // just switched to is not in use until it is saved, and an
                // empty field is not in use at all — on first run the old
                // reading would have been "in use" over "No key is stored".
                inUse={
                  currentAuthMode === settings.inference.auth_mode && activeStatus.configured
                }
              />
            ) : null}
          </>
        ) : null}

        {idleStatus?.configured && takesKey ? (
          <StoredNotInUse
            status={idleStatus}
            label={
              ANTHROPIC_SECRET_LABEL[currentAuthMode === 'api_key' ? 'oauth_token' : 'api_key']
            }
            onClear={() => void onClear(idleStatus.key)}
          />
        ) : null}

        {!takesKey
          ? (['api_key', 'oauth_token'] as const)
              .map((mode) => ({ mode, status: secretOf(AUTH_MODE_SECRET[mode]) }))
              .filter((entry) => entry.status?.configured)
              .map(({ mode, status }) => (
                <StoredNotInUse
                  key={mode}
                  status={status as SecretStatus}
                  label={ANTHROPIC_SECRET_LABEL[mode]}
                  onClear={() => void onClear(AUTH_MODE_SECRET[mode])}
                />
              ))
          : null}

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
      </Section>

      <Section
        id="storage"
        title="Where the data is kept"
        summary="Engagements, their meetings, the documents you attach and the words you add. A single file on this machine unless you point it somewhere else."
        // SQLite is the default, so an unreported storage means a local file —
        // not "unknown". This badge said "External database" whenever the
        // service had not mentioned storage, which told every reader, and every
        // documentation screenshot, the opposite of what a default install does.
        status={
          storage.database === '' || storage.database.startsWith('sqlite')
            ? { tone: 'ok', text: 'On this machine' }
            : { tone: 'ok', text: 'External database' }
        }
      >
        <div className="settings-field">
          <span className="settings-pseudo-label">In use now</span>
          <p className="settings-help">
            Read from the service, with any password removed.
          </p>
          <p className="settings-state">
            {storage.database || 'A file on this machine'}
          </p>
        </div>

        {databaseStatus ? (
          <SecretField
            {...secretProps(databaseStatus)}
            label="Database connection URL"
            help={
              'Leave unset to keep everything in the file above, which needs no ' +
              'database server. A PostgreSQL URL carries a password, so it is ' +
              'stored write-only and never shown back. ' +
              (storage.applies_on_restart
                ? 'A change here takes effect when the service restarts, not straight away.'
                : '')
            }
          />
        ) : null}
      </Section>

      <Section
        id="documents"
        title="Reference documents"
        summary="Where a linked SharePoint, OneDrive or Teams document is read from. Dropping a file onto the preparation screen needs none of this — it is only links that have to be fetched."
        status={documentsReadiness}
      >
        <div className="settings-field">
          <label htmlFor="graph-tenant">Directory (tenant) id</label>
          <p className="settings-help">
            The Microsoft 365 tenant the documents live in.
          </p>
          <input
            id="graph-tenant"
            type="text"
            value={currentDocuments.tenant_id ?? ''}
            placeholder="00000000-0000-0000-0000-000000000000"
            onChange={(event) =>
              setDocuments({
                ...currentDocuments,
                tenant_id: event.target.value === '' ? null : event.target.value,
              })
            }
          />
        </div>

        <div className="settings-field">
          <label htmlFor="graph-client">Application (client) id</label>
          <p className="settings-help">
            An app registration Elicta reads as. It needs the Files.Read.All
            permission, and Sites.Read.All to reach a team site.
          </p>
          <input
            id="graph-client"
            type="text"
            value={currentDocuments.client_id ?? ''}
            placeholder="00000000-0000-0000-0000-000000000000"
            onChange={(event) =>
              setDocuments({
                ...currentDocuments,
                client_id: event.target.value === '' ? null : event.target.value,
              })
            }
          />
        </div>

        {graphStatus ? (
          <SecretField
            {...secretProps(graphStatus)}
            label="Client secret"
            help="The registration's own secret. Until all three are set, attaching a link is refused with a message saying so — rather than recording a document nothing can read."
          />
        ) : null}
      </Section>

      <Section
        id="speech"
        title="Speech to text"
        summary="Turns the meeting into the transcript everything else reads. This is the credential the meeting itself depends on."
        status={speechReadiness}
      >
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
            {(['assemblyai', 'deepgram', 'custom'] as const).map((vendor) => (
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

        {speechStatus ? (
          <SecretField
            {...secretProps(speechStatus)}
            label={speechKeyLabel(
              currentConnectors.live_vendor,
              currentConnectors.custom_vendor_name,
            )}
            help="Transcribes the meeting on both the live and the record paths. One key covers both."
          />
        ) : null}

        {currentConnectors.live_vendor === 'custom' ||
        currentConnectors.record_vendors.includes('custom') ? (
          <div className="settings-field">
            <label htmlFor="custom-stt">Custom speech service endpoint</label>
            <p className="settings-help">
              Where to reach it. Vocabulary prompting and retention opt-out must
              be confirmed against that vendor's own API.
            </p>
            <input
              id="custom-stt"
              type="text"
              value={currentConnectors.custom_base_url ?? ''}
              placeholder="https://stt.internal"
              onChange={(event) =>
                setConnectors({
                  ...currentConnectors,
                  custom_base_url: event.target.value || null,
                })
              }
            />
          </div>
        ) : null}

        <div className="settings-field">
          <label htmlFor="region">Speech region</label>
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
      </Section>

      {captureStatus ? (
        <Section
          id="capture"
          title="Meeting capture"
          summary="Only needed when Elicta joins the call itself to record each participant on their own track. Leave it empty if you capture audio on this machine."
          status={captureReadiness}
        >
          <SecretField
            {...secretProps(captureStatus)}
            label="Managed capture vendor key"
            help="Used to join the meeting and capture per-participant audio."
          />
        </Section>
      ) : null}

      <div className="settings-actions glass">
        {/* State first, action last: the operator reads what is pending, then
            the button that resolves it. */}
        {dirty && !saving ? (
          <span className="settings-dirty">Unsaved changes</span>
        ) : saved && !saving ? (
          <span className="settings-saved">Saved</span>
        ) : null}
        <button type="button" onClick={() => void onSave()} disabled={saving}>
          {saving ? 'Saving…' : 'Save'}
        </button>
      </div>
    </section>
  );
}
