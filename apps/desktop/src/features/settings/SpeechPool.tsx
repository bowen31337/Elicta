import { useState } from 'react';

import {
  type SelectionPolicy,
  type SpeechCredential,
  type SpeechCredentialPool,
  type SpeechVendor,
} from './useSettings';

/**
 * The speech keys, as a list an operator adds to rather than a field they
 * overwrite.
 *
 * This replaced a single "speech vendor key" field, and the reason is worth
 * keeping: with one field, entering a second key silently replaced the first.
 * The hint beside it changed and nothing else did, so an operator who had
 * pasted a Deepgram key and then an AssemblyAI key believed they had two and
 * had one.
 *
 * Everything here applies immediately. The rest of this screen batches into
 * Save, and the difference is stated on the section rather than left for the
 * operator to discover: adding a key is its own request, because there is no
 * field on the settings body that could mean "one more" instead of "this one".
 */

/** Which providers this build has a live recogniser for. */
const LIVE_DRIVABLE: readonly SpeechVendor[] = ['deepgram'];

const VENDOR_LABELS: Record<SpeechVendor, string> = {
  assemblyai: 'AssemblyAI',
  deepgram: 'Deepgram',
  gemini: 'Google Gemini',
  custom: 'Other service',
};

const ADDABLE: readonly SpeechVendor[] = ['deepgram', 'assemblyai', 'gemini', 'custom'];

const POLICY_NOTE: Record<SelectionPolicy, string> = {
  single: 'One key serves every request until you change it. The others stay as spares.',
  rotate:
    'Each request takes the next enabled key in turn, which spreads a long meeting across several accounts instead of exhausting one.',
};

export interface SpeechPoolProps {
  readonly pool: SpeechCredentialPool;
  readonly onAdd: (
    vendor: SpeechVendor,
    label: string,
    value: string,
  ) => Promise<string | null>;
  readonly onSetEnabled: (id: string, enabled: boolean) => Promise<string | null>;
  readonly onRemove: (id: string) => Promise<string | null>;
  readonly onTest: (id: string) => Promise<string>;
  readonly onSetPolicy: (policy: SelectionPolicy) => Promise<string | null>;
}

export function SpeechPool({
  pool,
  onAdd,
  onSetEnabled,
  onRemove,
  onTest,
  onSetPolicy,
}: SpeechPoolProps) {
  const [vendor, setVendor] = useState<SpeechVendor>('deepgram');
  const [label, setLabel] = useState('');
  const [value, setValue] = useState('');
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  // Which key is a click away from being removed. Removal takes the value
  // with it and nothing here can undo that, so it asks — but inline, in the
  // row itself, rather than in a dialog that covers the list it is asking
  // about.
  const [confirming, setConfirming] = useState<string | null>(null);
  const [verdicts, setVerdicts] = useState<Record<string, string>>({});

  /**
   * `forgets` is the credential whose last verdict this action invalidates.
   *
   * A verdict answers "does this key work, in the state it was in?". Change
   * that state and the sentence is about a key that no longer exists in that
   * form — left on screen it reads as current, which is worse than showing
   * nothing.
   */
  const run = async (action: () => Promise<string | null>, forgets?: string) => {
    setBusy(true);
    if (forgets !== undefined) {
      setVerdicts((current) => {
        const { [forgets]: _gone, ...rest } = current;
        return rest;
      });
    }
    setFailure(await action());
    setBusy(false);
  };

  const onSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (value.trim() === '') return;
    setBusy(true);
    const problem = await onAdd(vendor, label.trim(), value.trim());
    setFailure(problem);
    if (problem === null) {
      // Only on success, and the value always: a key left in the box after it
      // has been stored invites a second paste of the same one.
      setLabel('');
      setValue('');
    }
    setBusy(false);
  };

  return (
    <>
      <div className="settings-field">
        <span className="settings-pseudo-label">Speech keys</span>
        <p className="settings-help">
          As many as you have, from as many providers. Changes here save
          themselves — the Save bar below is for the rest of this screen.
        </p>

        {pool.credentials.length === 0 ? (
          <p className="settings-state">
            No key yet. Without one a meeting still records, but nothing is
            transcribed while people are talking.
          </p>
        ) : (
          <ul className="speech-pool">
            {pool.credentials.map((credential) => (
              <li
                key={credential.id}
                className={credential.enabled ? 'speech-key' : 'speech-key is-off'}
              >
                <div className="speech-key-name">
                  <span className="speech-key-vendor">
                    {VENDOR_LABELS[credential.vendor]}
                  </span>
                  {credential.label ? (
                    <span className="speech-key-label">{credential.label}</span>
                  ) : null}
                  {pool.policy === 'single' && pool.active_id === credential.id ? (
                    <span className="speech-key-badge">Serving</span>
                  ) : null}
                </div>
                <p className="speech-key-note">{statusOf(credential, pool)}</p>
                {verdicts[credential.id] ? (
                  <p className="speech-key-verdict">{verdicts[credential.id]}</p>
                ) : null}
                <div className="speech-key-actions">
                  <button
                    type="button"
                    disabled={busy}
                    onClick={async () => {
                      setVerdicts((current) => ({ ...current, [credential.id]: 'Testing…' }));
                      const detail = await onTest(credential.id);
                      setVerdicts((current) => ({ ...current, [credential.id]: detail }));
                    }}
                  >
                    Test
                  </button>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => run(() => onSetEnabled(credential.id, !credential.enabled), credential.id)}
                  >
                    {credential.enabled ? 'Take out of service' : 'Put back in service'}
                  </button>
                  {confirming === credential.id ? (
                    <>
                      <button
                        type="button"
                        className="is-destructive"
                        disabled={busy}
                        onClick={() => {
                          setConfirming(null);
                          void run(() => onRemove(credential.id), credential.id);
                        }}
                      >
                        Remove for good
                      </button>
                      <button type="button" onClick={() => setConfirming(null)}>
                        Keep it
                      </button>
                    </>
                  ) : (
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => setConfirming(credential.id)}
                    >
                      Remove
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      <form className="settings-field" onSubmit={onSubmit}>
        <label htmlFor="speech-key-value">Add a speech key</label>
        <p className="settings-help">
          Paste it once. It is stored write-only — afterwards this screen can
          say a key is there and show its last four characters, and can never
          show you the key again.
        </p>
        <div className="speech-add">
          <select
            aria-label="Provider"
            value={vendor}
            onChange={(event) => setVendor(event.target.value as SpeechVendor)}
          >
            {ADDABLE.map((option) => (
              <option key={option} value={option}>
                {VENDOR_LABELS[option]}
              </option>
            ))}
          </select>
          <input
            aria-label="Name for this key"
            type="text"
            value={label}
            placeholder="Which account it is"
            onChange={(event) => setLabel(event.target.value)}
          />
          <input
            id="speech-key-value"
            type="password"
            value={value}
            placeholder="Key"
            autoComplete="off"
            onChange={(event) => setValue(event.target.value)}
          />
          <button type="submit" disabled={busy || value.trim() === ''}>
            Add
          </button>
        </div>
        {failure ? (
          <p className="settings-state is-warn" role="alert">
            {failure}
          </p>
        ) : null}
      </form>

      <div className="settings-field">
        <label htmlFor="speech-policy">When there is more than one</label>
        <p className="settings-help">{POLICY_NOTE[pool.policy]}</p>
        <select
          id="speech-policy"
          value={pool.policy}
          disabled={busy}
          onChange={(event) => run(() => onSetPolicy(event.target.value as SelectionPolicy))}
        >
          <option value="single">Use one key</option>
          <option value="rotate">Rotate through them</option>
        </select>
      </div>
    </>
  );
}

/**
 * What this key is actually doing, in the operator's terms.
 *
 * There are two lanes and they do not want the same providers, so a row that
 * said only "in service" would be true and useless. The case that made this
 * worth writing out: an AssemblyAI key transcribes every recording and
 * drives no nudge at all, and a note reporting only what it cannot do reads
 * as a broken key rather than a correctly configured one.
 */
function statusOf(credential: SpeechCredential, pool: SpeechCredentialPool): string {
  if (!credential.enabled) return 'Out of service. Its key is kept.';

  const live = LIVE_DRIVABLE.includes(credential.vendor);
  const turn =
    pool.policy === 'rotate' || pool.active_id === null || pool.active_id === credential.id;

  if (!live) {
    return 'Transcribes the recording after the meeting. This build has no live recogniser for this provider, so it does not drive the in-meeting nudges.';
  }
  if (!turn) return 'A spare. Another key is serving.';
  return pool.policy === 'rotate'
    ? 'In the rotation, for the nudges and the recording both.'
    : 'Serving the nudges and the recording both.';
}
