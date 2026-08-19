import '../prep/screens.css';

import { ScreenEyebrow } from '../../ui/Mark';

/**
 * Journey 9 — rate a replayed meeting, and see the release gates.
 *
 * Two ratings, and they are deliberately not opposites: a suggestion can be
 * useless without being embarrassing, and the gates treat them differently.
 * M2 allows zero embarrassing suggestions, so that rating is destructive to a
 * release in a way "not useful" is not — the screen says so rather than
 * presenting them as a single quality score.
 */
export interface Suggestion {
  readonly id: string;
  readonly at: string;
  readonly text: string;
  readonly language: string;
  readonly rating: 'useful' | 'not useful' | 'embarrassing' | null;
}

export interface ReplayScreenProps {
  readonly runLabel: string;
  readonly precisionPercent: number;
  readonly precisionThreshold: number;
  readonly embarrassmentCount: number;
  readonly suggestions: readonly Suggestion[];
}

export function ReplayScreen({
  runLabel,
  precisionPercent,
  precisionThreshold,
  embarrassmentCount,
  suggestions,
}: ReplayScreenProps) {
  const m1Pass = precisionPercent >= precisionThreshold;
  const m2Pass = embarrassmentCount === 0;

  return (
    <main className="screen" aria-labelledby="replay-title">
      <header className="screen-head">
        <ScreenEyebrow>Replay</ScreenEyebrow>
        <h1 className="t-large-title" id="replay-title">
          {runLabel}
        </h1>
      </header>

      <div className="stat-row">
        <div className={m1Pass ? 'stat stat--pass' : 'stat stat--fail'}>
          <span className="t-caption">Useful when surfaced</span>
          <span className="stat-value">{precisionPercent}%</span>
          <span className="t-caption">M1 needs {precisionThreshold}%</span>
        </div>
        <div className={m2Pass ? 'stat stat--pass' : 'stat stat--fail'}>
          <span className="t-caption">Embarrassing</span>
          <span className="stat-value">{embarrassmentCount}</span>
          <span className="t-caption">M2 needs zero</span>
        </div>
      </div>

      <section aria-labelledby="rate-title">
        <h2 className="t-section" id="rate-title">
          Suggestions
        </h2>
        <div className="group">
          {suggestions.map((suggestion) => (
            <div className="row" key={suggestion.id}>
              <div className="row-main">
                <span className="t-body">{suggestion.text}</span>
                <span className="t-footnote tabular">
                  {suggestion.at} · {suggestion.language.toUpperCase()}
                </span>
              </div>
              <div className="chips-row">
                <button
                  type="button"
                  className={suggestion.rating === 'useful' ? 'btn btn--on' : 'btn'}
                >
                  Useful
                </button>
                <button
                  type="button"
                  className={
                    suggestion.rating === 'embarrassing' ? 'btn btn--danger btn--on' : 'btn btn--danger'
                  }
                >
                  Embarrassing
                </button>
              </div>
            </div>
          ))}
        </div>
        <p className="t-footnote hint">
          Rate embarrassing only for a suggestion you would not want a client to
          have seen. One is enough to hold a release.
        </p>
      </section>
    </main>
  );
}

export default function ReplayRoute() {
  return (
    <ReplayScreen
      runLabel="—"
      precisionPercent={0}
      precisionThreshold={70}
      embarrassmentCount={0}
      suggestions={[]}
    />
  );
}
