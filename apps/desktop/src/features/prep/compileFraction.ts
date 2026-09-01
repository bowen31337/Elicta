/**
 * How far along a compile is, in a number that can move every frame.
 *
 * The service reports stage boundaries and nothing between them, and those
 * boundaries are about twenty seconds, twenty seconds, and two hundred
 * seconds apart. A bar that can only step at them stands still for minutes at
 * a time — which is the state it exists to tell apart from being stuck, so a
 * bar that does it is worse than no bar.
 *
 * So the stages are weighted by how long they actually take and the figure
 * creeps within the current one against elapsed time. That is an estimate and
 * is meant as one; two properties are what keep it honest.
 *
 * It never completes a stage the service has not reported. The creep is
 * asymptotic — it approaches the next boundary and never arrives — so a stage
 * running long slows down rather than overtaking the truth.
 *
 * And it never goes backwards. A meter that retreats reads as a fault in
 * itself, whatever it is describing.
 */

/**
 * How long each stage takes, measured against the provider rather than
 * guessed: extraction and structuring around twenty seconds each on a real
 * document set, the submission a couple, and the drafting pass the two to
 * four minutes that make up nearly all of a compile.
 *
 * These are weights, not promises. Their ratio is what shapes the bar, and it
 * is the ratio — one stage being ten times another — that stage-counting got
 * wrong.
 */
export const STAGE_SECONDS: readonly number[] = [25, 20, 2, 210];

/** The same, for the route that sends no batch. */
const DIRECT_STAGE_SECONDS: readonly number[] = [25, 20, 210];

export interface CompileFractionInput {
  readonly stagesCompleted: readonly string[];
  /** Since the compile was accepted. `null` when the service did not say. */
  readonly elapsedMs: number | null;
  readonly complete?: boolean;
  /** The drafting job is with the provider and nothing here is running. */
  readonly awaiting?: boolean;
}

const STAGE_IDS: readonly (readonly string[])[] = [
  ['extraction'],
  ['structuring'],
  ['batch-submission'],
  ['batch-collection', 'analyst-pass-direct'],
];

function weightsFor(stagesCompleted: readonly string[]): readonly number[] {
  const sentABatch =
    stagesCompleted.includes('batch-submission')
    || !stagesCompleted.includes('analyst-pass-direct');
  return sentABatch ? STAGE_SECONDS : DIRECT_STAGE_SECONDS;
}

function stagesFor(stagesCompleted: readonly string[]): readonly (readonly string[])[] {
  const sentABatch =
    stagesCompleted.includes('batch-submission')
    || !stagesCompleted.includes('analyst-pass-direct');
  return sentABatch ? STAGE_IDS : STAGE_IDS.filter((ids) => !ids.includes('batch-submission'));
}

export function compileFraction({
  stagesCompleted,
  elapsedMs,
  complete = false,
  awaiting = false,
}: CompileFractionInput): number {
  if (complete) return 1;

  const weights = weightsFor(stagesCompleted);
  const stages = stagesFor(stagesCompleted);
  const total = weights.reduce((sum, weight) => sum + weight, 0);

  const done = stages.filter((ids) => ids.some((id) => stagesCompleted.includes(id))).length;
  const behind = weights.slice(0, done).reduce((sum, weight) => sum + weight, 0);

  // Nothing is running while the provider has the job, so nothing creeps: a
  // bar advancing through a wait would be inventing work.
  if (awaiting || done >= weights.length) {
    return Math.min(1, behind / total);
  }

  if (elapsedMs === null) {
    // Nothing said when it began — an older service, or a compile restored
    // from storage. The stage under way counts as half, which is what the bar
    // draws it as: it cannot creep, but it must not read as nothing while
    // something is running.
    return Math.min(1, (behind + weights[done] / 2) / total);
  }

  const current = weights[done];
  // How long this stage has been going, taken as the elapsed time less what
  // the finished ones usually cost. Rough — the service does not report stage
  // starts — and rough is enough for a bar that is explicitly an estimate.
  const inStage = Math.max(0, elapsedMs / 1000 - behind);
  // Asymptotic: at one stage-length it is about two-thirds through, at two
  // about seven-eighths, and it never arrives. That is the property that
  // stops it claiming a stage the service has not reported.
  const crept = current * (1 - Math.exp(-inStage / current));

  return Math.min(1, (behind + crept) / total);
}
