import '../prep/screens.css';

import { ScreenEyebrow } from '../../ui/Mark';

/**
 * Journey 6 — reconcile the recording.
 *
 * Two engines transcribed the same audio. This screen is only about where they
 * disagreed, because agreement needs no review. The two readings sit side by
 * side rather than one above the other: the reviewer is comparing them, and a
 * vertical stack makes that a memory exercise.
 */
export interface Divergence {
  readonly id: string;
  readonly startSeconds: number;
  readonly endSeconds: number;
  readonly speaker: string;
  readonly readings: readonly { engine: string; text: string }[];
}

export interface RecordingScreenProps {
  readonly meetingTitle: string;
  readonly engines: readonly { name: string; status: 'complete' | 'failed' }[];
  readonly agreementPercent: number;
  readonly divergences: readonly Divergence[];
  readonly audioDestroyedAt: string | null;
}

function timestamp(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const rest = Math.floor(seconds % 60);
  return `${minutes}:${String(rest).padStart(2, '0')}`;
}

export function RecordingScreen({
  meetingTitle,
  engines,
  agreementPercent,
  divergences,
  audioDestroyedAt,
}: RecordingScreenProps) {
  return (
    <main className="screen" aria-labelledby="rec-title">
      <header className="screen-head">
        <ScreenEyebrow>Recording</ScreenEyebrow>
        <h1 className="t-large-title" id="rec-title">
          {meetingTitle}
        </h1>
      </header>

      <div className="stat-row">
        <div className="stat">
          <span className="t-caption">Engines agreed</span>
          <span className="stat-value">{agreementPercent}%</span>
        </div>
        <div className="stat">
          <span className="t-caption">Needs a look</span>
          <span className="stat-value">{divergences.length}</span>
        </div>
      </div>

      <section aria-labelledby="engines-title">
        <h2 className="t-section" id="engines-title">
          Engines
        </h2>
        <div className="group">
          {engines.map((engine) => (
            <div className="row" key={engine.name}>
              <div className="row-main">
                <span className="t-body">{engine.name}</span>
                <span className="t-footnote">
                  {engine.status === 'complete'
                    ? 'Transcribed the full session'
                    : 'Failed — the other engine still produced a transcript'}
                </span>
              </div>
              <span className={engine.status === 'complete' ? 'pill pill--ok' : 'pill pill--alert'}>
                {engine.status}
              </span>
            </div>
          ))}
        </div>
        <p className="t-footnote hint">
          Two engines are only worth running if they fail differently. Where
          they agree, nothing is flagged; where they diverge, it is never
          resolved silently.
        </p>
      </section>

      <section aria-labelledby="diverge-title">
        <h2 className="t-section" id="diverge-title">
          Where they disagreed
        </h2>
        {divergences.map((divergence) => (
          <div className="group" key={divergence.id}>
            <div className="row row--header">
              <span className="t-footnote tabular">
                {timestamp(divergence.startSeconds)}–{timestamp(divergence.endSeconds)}
              </span>
              <span className="t-footnote">{divergence.speaker}</span>
            </div>
            <div className="row">
              <div className="diverge">
                {divergence.readings.map((reading) => (
                  <div className="diverge-side" key={reading.engine}>
                    <span className="t-caption">{reading.engine}</span>
                    <span className="t-body">“{reading.text}”</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        ))}
      </section>

      {audioDestroyedAt ? (
        <section aria-labelledby="audio-title">
          <h2 className="t-section" id="audio-title">
            Audio
          </h2>
          <div className="group">
            <div className="row">
              <div className="row-main">
                <span className="t-body">Destroyed</span>
                <span className="t-footnote">
                  {audioDestroyedAt} — both transcription and diarization had
                  finished, so nothing still needed it.
                </span>
              </div>
              <span className="pill pill--ok">Done</span>
            </div>
          </div>
        </section>
      ) : null}
    </main>
  );
}

export default function RecordingRoute() {
  return (
    <RecordingScreen
      meetingTitle="—"
      engines={[]}
      agreementPercent={0}
      divergences={[]}
      audioDestroyedAt={null}
    />
  );
}
