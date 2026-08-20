import '../prep/screens.css';

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
 */
export interface ConsentScreenProps {
  readonly meetingTitle: string;
  readonly consentModel: 'per meeting' | 'standing for the engagement';
  readonly confirmedBy: string | null;
  readonly confirmedAt: string | null;
  readonly captureMode: string;
}

export function ConsentScreen({
  meetingTitle,
  consentModel,
  confirmedBy,
  confirmedAt,
  captureMode,
}: ConsentScreenProps) {
  const confirmed = confirmedBy !== null;

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
              <span className="t-body">
                {confirmed ? 'Confirmed' : 'Not confirmed'}
              </span>
              <span className="t-footnote">
                {confirmed
                  ? `${confirmedBy} · ${confirmedAt}`
                  : 'Capture cannot start until someone confirms this on the record.'}
              </span>
            </div>
            <span className={confirmed ? 'pill pill--ok' : 'pill pill--alert'}>
              {confirmed ? 'On record' : 'Required'}
            </span>
          </div>
        </div>
      </section>

      <section aria-labelledby="audio-state">
        <h2 className="t-section" id="audio-state">
          What happens to the audio
        </h2>
        <div className="group">
          <div className="row">
            <div className="row-main">
              <span className="t-body">Never written to disk</span>
              <span className="t-footnote">
                Audio stays in memory for the duration of transcription.
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

      <section aria-labelledby="capture-state">
        <h2 className="t-section" id="capture-state">
          Capture
        </h2>
        <div className="group">
          <div className="row">
            <div className="row-main">
              <span className="t-body">{captureMode}</span>
              <span className="t-footnote">
                Platform voice processing is off — it is tuned for a listener,
                and removes detail the transcriber uses.
              </span>
            </div>
            <button type="button" className="btn btn--filled" disabled={!confirmed}>
              Start
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
export default function ConsentRoute() {
  const consent = useConsent();

  if (consent.status !== 'ready' && consent.status !== 'missing') {
    return (
      <ScreenState
        eyebrow="Before recording"
        status={consent.status}
        error={consent.error}
        idleHint="No meeting exists yet. Create one before recording anything."
      />
    );
  }

  return (
    <ConsentScreen
      meetingTitle={consent.meetingTitle}
      consentModel={consent.consentModel}
      confirmedBy={consent.confirmedBy}
      confirmedAt={consent.confirmedAt}
      captureMode={consent.captureMode}
    />
  );
}
