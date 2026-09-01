import { useEffect, useState } from 'react';

import { compileFraction } from './compileFraction';
import '../../ui/notices.css';
import './CompileProgress.css';

/**
 * What a compile is doing, while it does it.
 *
 * A compile takes minutes: it reads the documents, sorts what it found, sends
 * the drafting job to the provider and waits for a bank. All of that used to
 * be one word — "Compiling" — and then, minutes later, either a bank or a
 * sentence. An operator watching a screen that says the same thing at ten
 * seconds and at six minutes cannot tell working from stuck, and that is what
 * came back twice as "it takes for ever".
 *
 * Nothing here is invented. The service reports each stage as it finishes; the
 * meter is the run's own account, drawn.
 */
export type CompileState = 'idle' | 'running' | 'awaiting' | 'complete' | 'stopped';

/** Which way a notice reads: something to wait out, to look at, or to fix. */
export type NoticeTone = 'working' | 'warning' | 'error';

export interface CompileProgressProps {
  readonly state: CompileState;
  /** Stage names the service reports, in the order it finishes them. */
  readonly stagesCompleted: readonly string[];
  readonly notice?: string | null;
  /** Defaults from `state`; pass it only where the state cannot decide. */
  readonly tone?: NoticeTone;
  /**
   * When the compile was accepted, in epoch milliseconds.
   *
   * Without it the bar can only step at stage boundaries, which are twenty
   * seconds and then two hundred seconds apart — long enough that a working
   * compile is indistinguishable from a stopped one, which is the whole thing
   * this is here to show.
   */
  readonly startedAt?: number | null;
}

/**
 * How often the creep is recomputed.
 *
 * Four times a second: enough that the bar reads as moving rather than
 * ticking, and cheap — it is arithmetic and a style property, no network and
 * no layout. Only while something is running.
 */
const TICK_MS = 250;

/**
 * The four stages a compile passes through, in order, in the operator's words.
 *
 * The last one has two service names — the batch route and the direct one —
 * because which of them ran is a billing detail, not a difference in what the
 * operator is waiting for. Both mean "the questions are being drafted".
 */
const STEPS: readonly { readonly ids: readonly string[]; readonly doing: string }[] = [
  { ids: ['extraction'], doing: 'reading the documents' },
  { ids: ['structuring'], doing: 'sorting what it found in them' },
  { ids: ['batch-submission'], doing: 'sending off the drafting job' },
  { ids: ['batch-collection', 'analyst-pass-direct'], doing: 'drafting the questions' },
];

/**
 * The stages this compile actually has, which depends on the route it took.
 *
 * A compile somebody is waiting on drafts the pass directly and sends no
 * batch, so `batch-submission` never completes — and a meter with a fixed
 * four steps sat at three of four for ever on a compile that had finished.
 *
 * The test is whether a batch was *sent*, not whether the direct route ran:
 * a compile that sent one, waited, and drafted directly anyway did do four
 * things, and saying three would lose one of them. Read off the run rather
 * than configured, so nothing has to be told which route was taken.
 *
 * Before the batch is sent there is nothing to go on, so the fourth step
 * shows and disappears if it turns out not to apply. Guessing the shorter
 * shape would be worse: a meter that grew a step mid-compile.
 */
function stepsFor(stagesCompleted: readonly string[]): typeof STEPS {
  const sentABatch =
    stagesCompleted.includes('batch-submission')
    || !stagesCompleted.includes('analyst-pass-direct');
  return sentABatch ? STEPS : STEPS.filter((step) => !step.ids.includes('batch-submission'));
}

/**
 * How full the stage under way should be drawn.
 *
 * The whole bar is `along`; the segments before this one are full. What is
 * left over belongs to this stage, as a share of the width one stage gets.
 */
function stepFill(along: number, steps: number, done: number): number {
  const perStep = 1 / steps;
  return Math.max(0, Math.min(1, (along - done * perStep) / perStep));
}


function toneFor(state: CompileState, given?: NoticeTone): NoticeTone {
  if (given) return given;
  return state === 'stopped' ? 'error' : 'working';
}

/**
 * What the compile is doing right now, said in the present tense.
 *
 * `awaiting` is deliberately not a stage. The drafting job is with the
 * provider and this machine is doing nothing — naming a stage there would
 * claim work that is not happening, which is the same overstatement that had
 * a batch already refused reporting itself as on its way.
 */
function currentlyDoing(state: CompileState, done: number, steps = STEPS): string | null {
  if (state === 'complete') return null;
  if (state === 'awaiting') return 'The drafting job is with the provider';
  if (state !== 'running') return null;
  // The stage alone. The row above already says "Compiling", and repeating it
  // here read as two labels for one thing.
  const step = steps[Math.min(done, steps.length - 1)];
  const doing = step.doing;
  return doing.charAt(0).toUpperCase() + doing.slice(1);
}

export function CompileProgress({
  state,
  stagesCompleted,
  notice = null,
  tone,
  startedAt = null,
}: CompileProgressProps) {
  const running = state === 'running';
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!running || startedAt === null) return undefined;
    const timer = window.setInterval(() => setNow(Date.now()), TICK_MS);
    return () => window.clearInterval(timer);
  }, [running, startedAt]);

  if (state === 'idle' && notice === null) return null;

  const steps = stepsFor(stagesCompleted);
  const done = steps.filter((step) =>
    step.ids.some((id) => stagesCompleted.includes(id)),
  ).length;
  const heading = currentlyDoing(state, done, steps);
  const showsPercent = state === 'running' || state === 'awaiting' || state === 'complete';
  /* Weighted by how long each stage takes and crept within the current one,
     rather than counted. Stage counting made the bar appear to start at
     thirteen per cent and then stand still: the stages are twenty, twenty and
     two hundred seconds, so a quarter of the *count* is a fiftieth of the
     work. See `compileFraction` for what keeps the creep honest. */
  const along = compileFraction({
    stagesCompleted,
    elapsedMs: startedAt === null ? null : Math.max(0, now - startedAt),
    complete: state === 'complete',
    awaiting: state === 'awaiting',
  });

  return (
    <div
      className="compile-progress"
      /* A number rather than a class per bucket: the fill walks from the
         working blue to the finished green as it climbs, and buckets would
         put steps back into the one thing being made continuous. */
      style={{ '--compile-along': along } as React.CSSProperties}
    >
      {heading === null && !showsPercent ? null : (
        <p className="compile-progress__doing t-footnote">
          <span>{heading}</span>
          {/* The bar carries the shape; the number carries the amount, and
              the amount is what gets asked for. Withheld once a compile has
              stopped: a figure frozen at twenty-five per cent invites the
              reading that it is still climbing, and what matters then is the
              reason directly underneath. */}
          {showsPercent ? (
            <span className="compile-progress__percent">
              {Math.round(along * 100)}%
            </span>
          ) : null}
        </p>
      )}

      {/* One segment per stage rather than a continuous bar: the stages are
          discrete and named, and a bar sliding to 62% would imply a precision
          nothing here has. The count is the accessible reading; the segments
          are what is taken in without reading. */}
      <div
        className="compile-progress__track"
        role="progressbar"
        aria-valuenow={done}
        aria-valuemin={0}
        aria-valuemax={steps.length}
        aria-label="Compile progress"
      >
        {steps.map((step, index) => (
          <span
            key={step.doing}
            className={
              index < done
                ? 'compile-progress__step compile-progress__step--done'
                : index === done && state === 'running'
                  ? 'compile-progress__step compile-progress__step--active'
                  : 'compile-progress__step'
            }
            /* Each segment fills by the share of *this* stage that is done,
               so the picture and the figure are the one number rather than
               two that have to be kept in step. They were not, once. */
            style={
              index === done && state === 'running'
                ? ({ '--step-fill': stepFill(along, steps.length, done) } as React.CSSProperties)
                : undefined
            }
          />
        ))}
      </div>

      {notice === null ? null : (
        <p
          className={`notice notice--${toneFor(state, tone)} t-footnote`}
          /* A stopped compile is not progress news. The polite live region
             waits for a convenient moment and reads as body text; this is the
             only account of why a bank is empty. */
          role={toneFor(state, tone) === 'error' ? 'alert' : 'status'}
        >
          {notice}
        </p>
      )}
    </div>
  );
}
