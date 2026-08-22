import '../prep/screens.css';

import { ScreenEyebrow } from '../../ui/Mark';
import { ScreenState } from '../../ui/ScreenState';
import { useReplay } from './useReplay';

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
  /** How many suggestions the two figures were measured over. */
  readonly ratedCount?: number;
  readonly usefulCount?: number;
  readonly embarrassmentCount: number;
  readonly suggestions: readonly Suggestion[];
}

export function ReplayScreen({
  runLabel,
  precisionPercent,
  precisionThreshold,
  ratedCount = 0,
  usefulCount = 0,
  embarrassmentCount,
  suggestions,
}: ReplayScreenProps) {
  // Nothing rated is not a failing gate and it is certainly not a passing one.
  // Either verdict over an empty set is a claim no evidence supports.
  const measured = ratedCount > 0;
  const m1Pass = measured && precisionPercent >= precisionThreshold;
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
        <div className={measured ? (m1Pass ? 'stat stat--pass' : 'stat stat--fail') : 'stat'}>
          <span className="t-caption">Useful when surfaced</span>
          <span className="stat-value">{measured ? `${precisionPercent}%` : '—'}</span>
          <span className="t-caption">
            {measured
              ? `${usefulCount} of ${ratedCount} rated · M1 needs ${precisionThreshold}%`
              : 'Nothing rated yet · M1 needs ' + precisionThreshold + '%'}
          </span>
        </div>
        <div className={measured ? (m2Pass ? 'stat stat--pass' : 'stat stat--fail') : 'stat'}>
          <span className="t-caption">Embarrassing</span>
          <span className="stat-value">{measured ? embarrassmentCount : '—'}</span>
          <span className="t-caption">
            {measured ? `of ${ratedCount} rated · M2 needs zero` : 'Nothing rated yet · M2 needs zero'}
          </span>
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

/**
 * The mounted screen, over the service.
 *
 * The placeholder rendered `precisionPercent={0}` and `embarrassmentCount={0}`
 * — a failing M1 and a passing M2, both invented. M2 is the dangerous one:
 * zero *is* the passing value, so a screen with nothing to show reported a
 * clean release gate for a build nobody had measured.
 */
export default function ReplayRoute() {
  const replay = useReplay();

  if (replay.status !== 'ready') {
    return (
      <ScreenState
        eyebrow="Replay"
        status={replay.status}
        error={replay.error}
        idleHint="No replay run has been started yet. Metrics appear once one has."
      />
    );
  }

  return (
    <ReplayScreen
      runLabel={replay.runLabel}
      precisionPercent={replay.precisionPercent}
      precisionThreshold={replay.precisionThreshold}
      embarrassmentCount={replay.embarrassmentCount}
      ratedCount={replay.ratedCount}
      usefulCount={replay.usefulCount}
      suggestions={replay.suggestions}
    />
  );
}
