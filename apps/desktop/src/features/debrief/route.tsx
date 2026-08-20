import '../prep/screens.css';

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
 * A meeting that has not been debriefed 404s on all three artifacts, and that
 * is content rather than failure — the screen renders with nothing in it. What
 * it must never do is render a claim without saying which kind it is, so the
 * provenance mapping fails toward `inferred`: an operator wrongly told "the
 * client said this" cannot un-hear it.
 */
export default function DebriefRoute() {
  const debrief = useDebrief();

  if (debrief.status !== 'ready' && debrief.status !== 'missing') {
    return (
      <ScreenState
        eyebrow="Debrief"
        status={debrief.status}
        error={debrief.error}
        idleHint="No meeting exists yet. Artifacts appear after one has been debriefed."
      />
    );
  }

  return (
    <DebriefScreen
      meetingTitle={debrief.meetingTitle}
      openQuestions={debrief.openQuestions}
      decisions={debrief.decisions}
      brief={debrief.brief}
    />
  );
}
