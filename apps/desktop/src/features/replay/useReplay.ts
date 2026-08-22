import { useState } from 'react';

import { combineStatus, useResource, type ResourceStatus } from '../../services/useResource';
import type { ReplayScreenProps } from './route';

/**
 * What the replay screen shows, read from the service (PRD §5, T13).
 *
 * The two gates are read as the service publishes them — per language, never
 * blended (T13). This screen shows one run at a time, so it reports the
 * language the run was conducted in; a Portuguese run scored under `en` is not
 * a figure that is slightly wrong, it is filed under the wrong gate entirely.
 *
 * **M2 is not defaulted.** `embarrassmentCount` comes from the service or the
 * screen does not render: showing zero because nothing answered would report a
 * passing release gate for a build that may well fail it, and M2 is a gate,
 * not a target — there is no "low enough".
 */
interface WireRun {
  readonly run_id: string;
  readonly recording_id: string;
  readonly language: string;
  readonly status: string;
  readonly suggestion_count: number;
}

interface WireRunList {
  readonly runs: readonly WireRun[];
}

interface WireLanguageFigure {
  readonly language: string;
  readonly surfaced_count: number;
  readonly useful_count: number;
  readonly precision_at_surfaced: number;
  readonly embarrassing_count: number;
  readonly clears_m2_gate: boolean;
}

interface WireMetrics {
  readonly run_id: string;
  readonly languages: readonly WireLanguageFigure[];
}

/** M1's release threshold (PRD §5): 70% of surfaced suggestions rated useful. */
export const M1_THRESHOLD_PERCENT = 70;

export interface ReplayData extends ReplayScreenProps {
  /**
   * Never `missing`. Every 404 this screen can meet is a contradiction rather
   * than an absence — the run list is a 200 with an empty list when there is
   * nothing, and a run it named must be measurable — so there is no state
   * here that means "not yet".
   */
  readonly status: Exclude<ResourceStatus, 'missing'>;
  readonly error: string | null;
  readonly runs: readonly WireRun[];
  readonly select: (runId: string) => void;
}

export function useReplay(): ReplayData {
  const list = useResource<WireRunList>('/api/replay/runs');
  const [chosen, setChosen] = useState<string | null>(null);

  const runs = list.data?.runs ?? [];
  // The most recent run, not the first: a replay screen is nearly always about
  // the run somebody just started.
  const run = runs.find((candidate) => candidate.run_id === chosen) ?? runs[runs.length - 1] ?? null;

  const metrics = useResource<WireMetrics>(
    run === null ? null : `/api/replay/runs/${encodeURIComponent(run.run_id)}/metrics`,
  );

  const figure =
    metrics.data?.languages.find((candidate) => candidate.language === run?.language) ?? null;

  return {
    runLabel:
      run === null
        ? 'No replay run yet'
        : `${run.recording_id} · ${run.language} · ${run.status}`,
    precisionPercent: Math.round((figure?.precision_at_surfaced ?? 0) * 100),
    precisionThreshold: M1_THRESHOLD_PERCENT,
    embarrassmentCount: figure?.embarrassing_count ?? 0,
    // How much evidence the two gates rest on. A live run photographed
    // "Useful when surfaced 100%" in green against "M1 needs 70%", measured
    // over a single rating, with nothing on screen to say so. Both numbers can
    // hold a release, and neither can be read without its denominator — which
    // the CI gate has always printed and this screen never did.
    ratedCount: figure?.surfaced_count ?? 0,
    usefulCount: figure?.useful_count ?? 0,
    // No endpoint lists a run's individual suggestions, so there is nothing to
    // rate here yet. An empty list is the honest rendering of that; inventing
    // rows to fill the section would be the `ack: {message}` mistake again.
    suggestions: [],
    runs,
    // A run the list just named whose metrics 404 is not "nothing yet" — it
    // is the service contradicting itself, and the screen must not paper over
    // it with zeroes.
    status:
      run === null
        ? list.status === 'ready'
          ? 'idle'
          : (list.status as Exclude<ResourceStatus, 'missing'>)
        : (combineStatus(
            list.status,
            metrics.status === 'missing' ? 'error' : metrics.status,
          ) as Exclude<ResourceStatus, 'missing'>),
    error:
      list.error ??
      metrics.error ??
      (run !== null && metrics.status === 'missing'
        ? `The service listed run ${run.run_id} and then could not measure it.`
        : null),
    select: setChosen,
  };
}
