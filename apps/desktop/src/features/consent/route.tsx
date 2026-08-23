import '../prep/screens.css';

import { useCallback, useState } from 'react';

import { ScreenEyebrow } from '../../ui/Mark';
import { ScreenState } from '../../ui/ScreenState';
import { useConsent } from './useConsent';

/**
 * Journey 2 — consent, then capture.
 *
 * This screen exists to make one thing unambiguous before anything records:
 * whether consent is on record, and what will happen to the audio. The capture
 * button is deliberately unavailable until it is — a gate the operator has to
 * pass, not a warning they can read past.
 *
 * **The gate is the gate's answer, not the record's.** This screen used to
 * decide whether capture could begin from `confirmedBy !== null` — that is,
 * from whether a *per-meeting confirmation record* existed. Consent agreed
 * once for the whole engagement writes no such record, so an engagement whose
 * consent was standing rendered "Required", told the operator capture could
 * not start, and disabled the button, while the service was answering
 * `capture_may_begin: true`. The two questions are separate and are kept
 * separate here: `gateStatus` says whether capture may begin, and
 * `confirmedBy` says on whose word — which only a per-meeting confirmation
 * has.
 */
export type ConsentGateStatus = 'not_required' | 'awaiting_confirmation' | 'confirmed';

/** The operator-facing warning the service composes, including the law it rests on. */
export interface ConsentPrompt {
  readonly title: string;
  readonly body: string;
  readonly legalBasis: string;
}

export interface ConsentActions {
  /** Puts consent on the record for this meeting, against a named person. */
  readonly confirm: (confirmedBy: string) => Promise<void>;
  /**
   * Goes to the recording screen, which is where the meeting actually begins.
   *
   * This used to be `start`, and it booked the meeting on the service from
   * here. It does not any more: the meeting starts when the recording starts,
   * and this screen can neither choose an input nor show that sound is
   * arriving on it.
   */
  readonly proceed: () => void;
}

export interface ConsentScreenProps {
  readonly meetingTitle: string;
  readonly consentModel: 'per meeting' | 'standing for the engagement';
  readonly gateStatus: ConsentGateStatus;
  /** Populated only while confirmation is outstanding — the service sends it then. */
  readonly prompt: ConsentPrompt | null;
  readonly confirmedBy: string | null;
  readonly confirmedAt: string | null;
  readonly actions: ConsentActions;
}

/**
 * Runs one write and keeps what happened.
 *
 * A refusal from the gate is the gate working, and the service's own sentence
 * is the only part the operator can act on, so it is shown rather than a
 * status code.
 */
function useWrite() {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const run = useCallback(async (write: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await write();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'That did not work.');
    } finally {
      setBusy(false);
    }
  }, []);

  return { error, busy, run };
}

/**
 * What the consent row says in each of the gate's three states.
 *
 * `not_required` carries a deliberately flat statement and an amber pill, not
 * a green one. It used to read "Consent was agreed once for the whole
 * engagement" beside "On record" — which was defensible while an engagement
 * reached that state only by being configured for standing consent, and is
 * not defensible now that it is the default an unconfigured engagement falls
 * into. Nothing was agreed and nothing was recorded, and the screen may not
 * imply otherwise; the gate being open is not the same as consent existing.
 */
function consentState(
  gateStatus: ConsentGateStatus,
  confirmedBy: string | null,
  confirmedAt: string | null,
): {
  readonly label: string;
  readonly footnote: string;
  readonly pill: string;
  readonly tone: 'ok' | 'warn' | 'alert';
} {
  if (gateStatus === 'not_required') {
    return {
      label: 'Not required for this meeting',
      footnote:
        'This engagement does not ask for consent at each meeting, so nothing is recorded here.',
      pill: 'Not asked',
      tone: 'warn',
    };
  }
  if (gateStatus === 'confirmed') {
    return {
      label: 'Confirmed',
      footnote:
        confirmedBy === null
          ? 'On the record for this meeting. The service did not return who confirmed it.'
          : `${confirmedBy} · ${confirmedAt}`,
      pill: 'On record',
      tone: 'ok',
    };
  }
  return {
    label: 'Not confirmed',
    footnote: 'Capture cannot start until someone confirms this on the record.',
    pill: 'Required',
    tone: 'alert',
  };
}

export function ConsentScreen({
  meetingTitle,
  consentModel,
  gateStatus,
  prompt,
  confirmedBy,
  confirmedAt,
  actions,
}: ConsentScreenProps) {
  const write = useWrite();
  const [confirmedByInput, setConfirmedByInput] = useState('');

  // The service's own rule (`ConsentGate.capture_may_begin`): everything but
  // an outstanding confirmation lets capture begin.
  const captureMayBegin = gateStatus !== 'awaiting_confirmation';
  const state = consentState(gateStatus, confirmedBy, confirmedAt);

  const confirm = () =>
    void write.run(async () => {
      await actions.confirm(confirmedByInput);
      setConfirmedByInput('');
    });

  return (
    <main className="screen" aria-labelledby="consent-title">
      <header className="screen-head">
        <ScreenEyebrow>Before recording</ScreenEyebrow>
        <h1 className="t-large-title" id="consent-title">
          {meetingTitle}
        </h1>
      </header>

      <section aria-labelledby="consent-state">
        <h2 className="t-section" id="consent-state">
          Consent
        </h2>
        <div className="group">
          <div className="row">
            <div className="row-main">
              <span className="t-body">Consent model</span>
              <span className="t-footnote">{consentModel}</span>
            </div>
          </div>
          <div className="row">
            <div className="row-main">
              <span className="t-body">{state.label}</span>
              <span className="t-footnote">{state.footnote}</span>
            </div>
            <span className={`pill pill--${state.tone}`}>{state.pill}</span>
          </div>
        </div>
      </section>

      {gateStatus !== 'awaiting_confirmation' ? null : (
        <section aria-labelledby="consent-confirm">
          <h2 className="t-section" id="consent-confirm">
            {prompt?.title ?? 'Confirm consent'}
          </h2>
          <div className="group">
            {prompt === null ? null : (
              <div className="row">
                <div className="row-main">
                  <span className="t-body">{prompt.body}</span>
                  <span className="t-footnote">{prompt.legalBasis}</span>
                </div>
              </div>
            )}
            <div className="row row--form">
              <div className="row-main">
                <label className="t-footnote" htmlFor="confirmed-by">
                  Who is confirming consent
                </label>
                <input
                  id="confirmed-by"
                  type="text"
                  className="field"
                  placeholder="Name and role"
                  value={confirmedByInput}
                  onChange={(event) => setConfirmedByInput(event.target.value)}
                />
              </div>
              <button type="button" className="btn" disabled={write.busy} onClick={confirm}>
                Confirm consent
              </button>
            </div>
          </div>
          {write.error === null ? null : (
            <p className="t-footnote prep-error" role="alert">
              {write.error}
            </p>
          )}
          <p className="t-footnote hint">
            This records who is accountable for having disclosed the recording —
            not the participants. It is kept for the life of the engagement.
          </p>
        </section>
      )}

      <section aria-labelledby="audio-state">
        <h2 className="t-section" id="audio-state">
          What happens to the audio
        </h2>
        <div className="group">
          <div className="row">
            <div className="row-main">
              <span className="t-body">Never saved as a file</span>
              <span className="t-footnote">
                Elicta writes no copy of the audio anywhere. It is held only for
                as long as it takes to turn it into text.
              </span>
            </div>
          </div>
          <div className="row">
            <div className="row-main">
              <span className="t-body">Destroyed after transcription</span>
              <span className="t-footnote">
                The moment the recording has been transcribed and diarized, the
                audio is deleted and the deletion is recorded.
              </span>
            </div>
          </div>
          <div className="row">
            <div className="row-main">
              <span className="t-body">Vendors told not to retain</span>
              <span className="t-footnote">
                Sent as a parameter on every request, not only in the contract.
              </span>
            </div>
            <span className="pill pill--ok">On</span>
          </div>
        </div>
      </section>

      <section aria-labelledby="next-step">
        <h2 className="t-section" id="next-step">
          Next
        </h2>
        <div className="group">
          <div className="row">
            <div className="row-main">
              <span className="t-body">Set up the recording</span>
              <span className="t-footnote">
                {captureMayBegin
                  ? 'Choose your microphone and check that sound is arriving, then start recording. The meeting begins when the recording does.'
                  : 'Confirm consent above, and this opens.'}
              </span>
            </div>
            <button
              type="button"
              className="btn btn--filled"
              disabled={!captureMayBegin}
              onClick={actions.proceed}
            >
              Continue to recording
            </button>
          </div>
        </div>
      </section>
    </main>
  );
}

/**
 * The mounted screen, over the service.
 *
 * The placeholder it replaces was worse here than anywhere else: it hardcoded
 * `confirmedBy={null}`, so a meeting with consent properly on record still
 * rendered "Capture cannot start until someone confirms this on the record."
 * A gate that lies in the safe direction still trains the operator to ignore
 * it.
 */
export default function ConsentRoute({
  navigate,
}: { navigate?: (to: string) => void } = {}) {
  const consent = useConsent(navigate);

  if (consent.status !== 'ready' && consent.status !== 'missing') {
    return (
      <ScreenState
        eyebrow="Before recording"
        status={consent.status}
        error={consent.error}
        idleHint={consent.idleHint}
      />
    );
  }

  return (
    <ConsentScreen
      meetingTitle={consent.meetingTitle}
      consentModel={consent.consentModel}
      gateStatus={consent.gateStatus}
      prompt={consent.prompt}
      confirmedBy={consent.confirmedBy}
      confirmedAt={consent.confirmedAt}
      actions={consent.actions}
    />
  );
}
