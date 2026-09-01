import '../prep/screens.css';
import '../../ui/notices.css';

import { ScreenEyebrow } from '../../ui/Mark';
import { ScreenState } from '../../ui/ScreenState';
import { useDebrief } from './useDebrief';

/**
 * Journey 7 — the debrief artifacts.
 *
 * A reviewer's core need is telling what the client *said* from what the system
 * *concluded*. So provenance is not a footnote here: every claim carries a
 * badge, and an inferred claim shows the utterance it was inferred from. A
 * screen that blurred those two would be worse than no screen.
 */
export interface Claim {
  readonly id: string;
  readonly text: string;
  readonly provenance: 'stated' | 'inferred';
  readonly citation: { readonly speaker: string; readonly at: string; readonly quote: string } | null;
}

export interface DebriefScreenProps {
  readonly meetingTitle: string;
  readonly openQuestions: readonly Claim[];
  readonly decisions: readonly Claim[];
  readonly brief: Claim | null;
  /** Why the write-up is short, when it is. See `incompleteNotice`. */
  readonly incomplete?: string | null;
  /** Whether the pipeline is working on it right now. */
  readonly running?: boolean;
  /** Why there is nothing here at all, when there is nothing. See `emptyNotice`. */
  readonly empty?: string | null;
  /** Produce the write-up for a meeting that is owed one. */
  readonly onProduce?: () => Promise<void>;
  readonly producing?: boolean;
}

function ClaimRow({ claim }: { claim: Claim }) {
  return (
    <div className="row">
      <div className="row-main">
        <span className="t-body">{claim.text}</span>
        {claim.citation ? (
          <blockquote className="quote t-footnote">
            “{claim.citation.quote}” — {claim.citation.speaker}, {claim.citation.at}
          </blockquote>
        ) : null}
      </div>
      <span className={claim.provenance === 'stated' ? 'pill pill--ok' : 'pill'}>
        {claim.provenance}
      </span>
    </div>
  );
}

export function DebriefScreen({
  meetingTitle,
  openQuestions,
  decisions,
  brief,
  incomplete = null,
  empty = null,
  running = false,
  onProduce,
  producing = false,
}: DebriefScreenProps) {
  return (
    <main className="screen" aria-labelledby="debrief-title">
      <header className="screen-head">
        <ScreenEyebrow>Debrief</ScreenEyebrow>
        <h1 className="t-large-title" id="debrief-title">
          {meetingTitle}
        </h1>
        <p className="t-footnote">
          Every claim below links to the moment it came from. Nothing is written
          without one.
        </p>
      </header>

      {/* `alert`, not `status`. A run that stopped is not progress news: the
          polite live region waits for a convenient moment and reads as body
          text, and this sentence is the only account of why a meeting that
          was recorded and transcribed has no documents. It also used to carry
          `.degraded-note`, which is defined in the panel's stylesheet and not
          in this screen's — so it had no styling at all. */}
      {incomplete ? (
        <p className="notice notice--error t-footnote" role="alert">
          {incomplete}
        </p>
      ) : null}

      {/* Progress, which genuinely is a status. Rendered above the empty
          notice and in place of the button, so pressing it visibly changes
          the screen — the request is answered immediately now and the work
          goes on behind it, which is only an improvement if the screen says
          so. */}
      {running ? (
        <p className="notice notice--working t-footnote" role="status">
          This meeting is being written up now. It takes a few minutes; the
          documents appear here as they are produced.
        </p>
      ) : null}

      {/* Not a `status`: nothing has gone wrong, and a meeting whose write-up
          is simply still to come would otherwise raise an alert on every
          visit. The headings below stay, so it reads as "these are not filled
          in yet" rather than "these came back empty". */}
      {/* The account of why there is nothing, and the thing to do about it.
          They used to be one block, gated on `empty` — and `emptyNotice`
          returns null the moment there is a failure notice to show, so a
          stopped run replaced the only control that could rerun it. The
          operator was left with a red alert and nothing to press.

          The same shape as the `Asked it` chip that removed itself once
          every section was marked: an affordance gated on the state it
          exists to change. A failed run is not a reason to hide the retry;
          it is the reason to show it. */}
      {(empty || incomplete) && !running ? (
        <div className="debrief-empty">
          {empty ? <p className="t-footnote hint">{empty}</p> : null}
          {onProduce ? (
            <button
              type="button"
              className="btn"
              disabled={producing}
              onClick={() => void onProduce()}
            >
              {producing
                ? 'Writing it up…'
                : /* Named for what pressing it does *now*. "Write it up now"
                     over a notice saying the write-up already stopped reads
                     as an offer to do something that has plainly been tried. */
                  incomplete
                  ? 'Try again'
                  : 'Write it up now'}
            </button>
          ) : null}
        </div>
      ) : null}

      {brief ? (
        <section aria-labelledby="brief-title">
          <h2 className="t-section" id="brief-title">
            Project brief
          </h2>
          <div className="group">
            <ClaimRow claim={brief} />
          </div>
        </section>
      ) : null}

      <section aria-labelledby="oq-title">
        <h2 className="t-section" id="oq-title">
          Open questions
        </h2>
        <div className="group">
          {openQuestions.map((claim) => (
            <ClaimRow claim={claim} key={claim.id} />
          ))}
        </div>
      </section>

      <section aria-labelledby="dec-title">
        <h2 className="t-section" id="dec-title">
          Decisions
        </h2>
        <div className="group">
          {decisions.map((claim) => (
            <ClaimRow claim={claim} key={claim.id} />
          ))}
        </div>
      </section>
    </main>
  );
}

/**
 * The mounted screen, over the service.
 *
 * A meeting that has not been debriefed 404s on all four routes behind this
 * screen, and that is content rather than failure. It is not, however,
 * self-explanatory: the screen used to render two bare headings, which reads
 * as a meeting where nothing was decided. `emptyNotice` says which of the two
 * it is. What the screen must never do is render a claim without saying which
 * kind it is, so the provenance mapping fails toward `inferred`: an operator
 * wrongly told "the client said this" cannot un-hear it.
 */
export default function DebriefRoute() {
  const debrief = useDebrief();

  if (debrief.status !== 'ready' && debrief.status !== 'missing') {
    return (
      <ScreenState
        eyebrow="Debrief"
        status={debrief.status}
        error={debrief.error}
        idleHint={debrief.idleHint}
      />
    );
  }

  return (
    <DebriefScreen
      meetingTitle={debrief.meetingTitle}
      openQuestions={debrief.openQuestions}
      decisions={debrief.decisions}
      brief={debrief.brief}
      incomplete={debrief.incomplete}
      empty={debrief.empty}
      running={debrief.running}
      onProduce={debrief.onProduce}
      producing={debrief.producing}
    />
  );
}
