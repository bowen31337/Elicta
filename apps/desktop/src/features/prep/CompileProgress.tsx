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
}

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
function currentlyDoing(state: CompileState, done: number): string | null {
  if (state === 'complete') return null;
  if (state === 'awaiting') return 'The drafting job is with the provider';
  if (state !== 'running') return null;
  // The stage alone. The row above already says "Compiling", and repeating it
  // here read as two labels for one thing.
  const step = STEPS[Math.min(done, STEPS.length - 1)];
  const doing = step.doing;
  return doing.charAt(0).toUpperCase() + doing.slice(1);
}

export function CompileProgress({
  state,
  stagesCompleted,
  notice = null,
  tone,
}: CompileProgressProps) {
  if (state === 'idle' && notice === null) return null;

  const done = STEPS.filter((step) =>
    step.ids.some((id) => stagesCompleted.includes(id)),
  ).length;
  const heading = currentlyDoing(state, done);

  return (
    <div className="compile-progress">
      {heading === null ? null : (
        <p className="compile-progress__doing t-footnote">{heading}</p>
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
        aria-valuemax={STEPS.length}
        aria-label="Compile progress"
      >
        {STEPS.map((step, index) => (
          <span
            key={step.doing}
            className={
              index < done
                ? 'compile-progress__step compile-progress__step--done'
                : index === done && state === 'running'
                  ? 'compile-progress__step compile-progress__step--active'
                  : 'compile-progress__step'
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
