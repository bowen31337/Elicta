import '../prep/screens.css';

import { ScreenEyebrow } from '../../ui/Mark';
import { ScreenState } from '../../ui/ScreenState';
import { useArc } from './useArc';

/**
 * Journey 8 — what carries into the next meeting.
 *
 * The value of an engagement-scoped product over a per-meeting one lives
 * entirely here, so the screen is built around the through-line: a timeline of
 * meetings, and above it the state that survived them. Questions that went
 * unanswered are shown first, because those are what the next meeting is for.
 */
export interface Meeting {
  readonly id: string;
  readonly title: string;
  readonly date: string;
  readonly sectionsCovered: number;
  readonly sectionsTotal: number;
}

export interface StandingQuestion {
  readonly id: string;
  readonly text: string;
  readonly raisedIn: string;
  readonly meetingsOpen: number;
}

export interface ArcScreenProps {
  readonly engagement: string;
  readonly meetings: readonly Meeting[];
  readonly standingQuestions: readonly StandingQuestion[];
  readonly confirmedRequirements: number;
}

export function ArcScreen({
  engagement,
  meetings,
  standingQuestions,
  confirmedRequirements,
}: ArcScreenProps) {
  return (
    <main className="screen" aria-labelledby="arc-title">
      <header className="screen-head">
        <ScreenEyebrow>Engagement</ScreenEyebrow>
        <h1 className="t-large-title" id="arc-title">
          {engagement}
        </h1>
      </header>

      <div className="stat-row">
        <div className="stat">
          <span className="t-caption">Meetings</span>
          <span className="stat-value">{meetings.length}</span>
        </div>
        <div className="stat">
          <span className="t-caption">Requirements confirmed</span>
          <span className="stat-value">{confirmedRequirements}</span>
        </div>
        <div className="stat">
          <span className="t-caption">Still open</span>
          <span className="stat-value">{standingQuestions.length}</span>
        </div>
      </div>

      <section aria-labelledby="standing-title">
        <h2 className="t-section" id="standing-title">
          Carried into the next meeting
        </h2>
        <div className="group">
          {standingQuestions.map((question) => (
            <div className="row" key={question.id}>
              <div className="row-main">
                <span className="t-body">{question.text}</span>
                <span className="t-footnote">First raised in {question.raisedIn}</span>
              </div>
              <span
                className={question.meetingsOpen > 1 ? 'pill pill--warn' : 'pill'}
                title="Meetings this has stayed open"
              >
                {question.meetingsOpen} {question.meetingsOpen === 1 ? 'meeting' : 'meetings'}
              </span>
            </div>
          ))}
        </div>
        <p className="t-footnote hint">
          The bank for the next meeting is weighted toward these. A question
          that has survived two meetings is the one most worth asking in the
          third.
        </p>
      </section>

      <section aria-labelledby="timeline-title">
        <h2 className="t-section" id="timeline-title">
          Meetings so far
        </h2>
        <div className="timeline">
          {meetings.map((meeting, index) => (
            <div className="timeline-item" key={meeting.id}>
              <div className="timeline-rail" aria-hidden="true">
                <span className="timeline-dot" />
                {index < meetings.length - 1 ? <span className="timeline-line" /> : null}
              </div>
              <div className="timeline-body">
                <span className="t-headline">{meeting.title}</span>
                <span className="t-footnote">
                  {meeting.date} · {meeting.sectionsCovered} of {meeting.sectionsTotal}{' '}
                  sections covered
                </span>
              </div>
            </div>
          ))}
        </div>
      </section>
    </main>
  );
}

/**
 * The mounted screen, over the service.
 *
 * The through-line this screen exists to show — what survived the meetings —
 * is the engagement's own carried-forward state, so it is read rather than
 * recomputed from the meetings here. An engagement with one meeting and no
 * debrief yet legitimately has nothing to carry, and renders that way.
 */
export default function ArcRoute() {
  const arc = useArc();

  if (arc.status !== 'ready' && arc.status !== 'missing') {
    return (
      <ScreenState
        eyebrow="Engagement"
        status={arc.status}
        error={arc.error}
        idleHint="No engagement exists yet. The arc appears once one has meetings behind it."
      />
    );
  }

  return (
    <ArcScreen
      engagement={arc.engagement}
      meetings={arc.meetings}
      standingQuestions={arc.standingQuestions}
      confirmedRequirements={arc.confirmedRequirements}
    />
  );
}
