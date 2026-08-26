import { useState } from 'react';

import './route.css';
import {
  AskedItChip,
  EscapeHatchInput,
  GoDeeperChip,
  ParkItChip,
  WhatAmIMissingChip,
} from './chips';
import type { CoverageSlot, CoverageSummary } from './coverage';
import { CoverageIndicator, useSessionStream } from './coverage';
import type { DetectedLanguage } from './language';
import { LanguageChrome } from './language';
import type { Nudge } from './nudge';
import { NudgeStack } from './nudge';
import { recordNudgeDisposition } from '../../services/nudgeDisposition';
import { useCurrentEngagement, useCurrentMeeting } from '../../services/selection';

/**
 * The operator panel — the one screen this product shows during a meeting.
 *
 * Everything here is shaped by a single constraint: the operator is looking at
 * a client, not at this. So the panel is a floating material rather than a
 * page, the nudge is the only thing set at reading size, and every response is
 * one tap. The chrome (coverage, time, language, connection) is deliberately
 * quiet — it is state to glance at, not to read.
 *
 * On a touch screen that constraint gets stronger rather than different: the
 * panel stops being a card floating over something and becomes the screen,
 * with the chrome pinned at the top, the nudge in the middle at reading size,
 * and every control docked at the foot of the display where a thumb already
 * is. The layout adapts; what the screen *is* does not. `route.css` holds the
 * whole of that behind `(pointer: coarse)` — deliberately the pointer and not
 * a width, since a narrow desk window is still driven by a cursor.
 */
export interface PanelState {
  readonly active: Nudge | null;
  readonly history: readonly Nudge[];
  readonly coverage: CoverageSummary | null;
  readonly languages: readonly DetectedLanguage[];
  /** False when the slow lane cannot reach a model (architecture §10). */
  readonly modelReachable?: boolean;
  /**
   * Which of the four problems the lane met — an outage, a throttle, a
   * refused credential or a plan that does not cover the model. They do not
   * share a remedy, so the panel says which rather than collapsing them.
   */
  readonly degradedReason?: string | null;
  readonly meetingId?: string;
  readonly operatorLanguage?: string;
  readonly activeTier?: 'tier-1' | 'tier-2' | 'tier-3' | null;
}

const EMPTY: PanelState = {
  active: null,
  history: [],
  coverage: null,
  languages: [],
  modelReachable: true,
};

function SlotMeter({ summary }: { summary: CoverageSummary | null }) {
  // The segments are a graphic beside CoverageIndicator's own count, not a
  // replacement for it: the count is the accessible reading, the segments are
  // what an operator takes in without reading.
  if (!summary) return null;
  return (
    <div className="meter-track" aria-hidden="true">
      {summary.slots.map((slot) => (
        <span key={slot.id} className={slot.filled ? 'meter-seg is-filled' : 'meter-seg'} />
      ))}
    </div>
  );
}

export function OperatorPanel({
  initial = EMPTY,
  createSource,
}: {
  initial?: PanelState;
  /** Overridable so a test can drive the stream without a network. */
  createSource?: Parameters<typeof useSessionStream>[1] extends
    | { createSource?: infer F }
    | undefined
    ? F
    : never;
}) {
  const [state, setState] = useState<PanelState>(initial);

  // The live session drives the panel when there is one. Coverage arrives as
  // the current summary rather than a diff, and each nudge replaces the
  // active one — the previous nudge recedes into history rather than being
  // dropped, so the operator can still see what they just declined.
  const {
    coverage,
    languages: streamLanguages,
    modelReachable,
    degradedReason,
  } = useSessionStream(state.meetingId ?? null, {
    createSource,
    onNudge: (nudge) =>
      setState((current) => {
        // Already seen. The stream replays its whole backlog on every
        // connect — that is how a panel opened mid-meeting catches up — and
        // `EventSource` reconnects on its own schedule every few minutes.
        // Nothing deduped, so each reconnection appended the meeting's
        // entire history to itself: an operator who had seen three nudges
        // found six, then nine, all of them real and none of them new.
        if (current.active?.id === nudge.id) return current;
        if (current.history.some((held) => held.id === nudge.id)) return current;
        return {
          ...current,
          active: nudge,
          history: current.active ? [current.active, ...current.history] : current.history,
        };
      }),
  });

  const onAsked = (slot: CoverageSlot) => {
    setState((current) =>
      current.coverage === null
        ? current
        : {
            ...current,
            coverage: {
              ...current.coverage,
              slots: current.coverage.slots.map((existing) =>
                existing.id === slot.id ? { ...existing, filled: true } : existing,
              ),
            },
          },
    );

    // Fire-and-forget: the operator's confirmation is the local mutation above,
    // not this round trip (FR-6.6). A dropped sync costs an analytics row, and
    // must never hold up a panel mid-meeting.
    if (state.meetingId && state.active) {
      void recordNudgeDisposition({
        meetingId: state.meetingId,
        nudgeId: state.active.id,
        disposition: 'taken',
      });
    }
    retireActive();
  };

  /**
   * Put the active nudge down, into history.
   *
   * Both chips that deal with a question end here. Parking says "not now"
   * and asking says "done"; either way the operator has finished with it,
   * and the panel went on showing it — with the next nudge up to a minute
   * away, that left a card sitting there already dealt with and nothing to
   * press to move past it.
   *
   * Into history rather than gone. That was not safe until history became
   * reachable: putting a nudge down used to lose it for good. It is one
   * press away now, which is what makes retiring it the right behaviour
   * rather than a trade.
   */
  const retireActive = () => {
    setState((current) =>
      current.active === null
        ? current
        : { ...current, active: null, history: [current.active, ...current.history] },
    );
  };

  /**
   * Bring a nudge that has receded back to the front.
   *
   * A swap, not a reordering: the one being brought back leaves history and
   * the one it displaces takes the front of it, so nothing is lost and the
   * one just put down is a single press away. Exactly one stays prominent,
   * which is what FR-6.3 asks — it constrains prominence, not which nudge
   * the operator is allowed to be looking at.
   *
   * Without this every chip acted on whatever arrived last, and a nudge
   * became unactionable the moment the next one landed. With one arriving
   * as often as a minute apart, that is most of a meeting's worth.
   */
  const onSelectNudge = (nudge: Nudge) => {
    setState((current) => {
      if (current.active === null || current.active.id === nudge.id) return current;
      return {
        ...current,
        active: nudge,
        history: [current.active, ...current.history.filter((held) => held.id !== nudge.id)],
      };
    });
  };

  const onParked = () => {
    if (state.meetingId && state.active) {
      void recordNudgeDisposition({
        meetingId: state.meetingId,
        nudgeId: state.active.id,
        disposition: 'parked',
      });
    }
    retireActive();
  };

  /**
   * A question the operator typed rather than one the gate surfaced.
   *
   * It becomes the active nudge, because that is what they meant by typing
   * it: they intend to ask it, and every chip acts on the active nudge. So
   * the escape hatch produces a question the rest of the panel already knows
   * how to handle — parking files it into the next meeting's bank, asking it
   * ticks a section — rather than needing a second machinery of its own.
   *
   * It said nothing before. The handler was a no-op and the field cleared on
   * Enter, which is the gesture that means "sent" — so it signalled success
   * for work that never happened.
   *
   * Deliberately no model call: typing already costs an order of magnitude
   * more attention than a tap (FR-6.6's rationale), and a wait on top of
   * that is what the chips exist to avoid.
   */
  const onTypedQuestion = (query: { text: string; submittedAt: number }) => {
    setState((current) => ({
      ...current,
      active: {
        id: `typed-${query.submittedAt}`,
        stub: 'Your question',
        question: query.text,
        // The reason line says why this is on screen, and "you typed it" is
        // as true an answer as "somebody said several".
        triggerReason: 'typed by you',
        createdAt: query.submittedAt,
      },
      history: current.active ? [current.active, ...current.history] : current.history,
    }));
  };

  const liveCoverage = coverage ?? state.coverage;
  const firstUnfilled = liveCoverage?.slots.find((slot) => !slot.filled) ?? null;
  // The live stream wins over the initial prop once a meeting is running:
  // the prop is what the panel was handed at mount, the stream is what the
  // service knows now. Without a meeting there is no stream, so the prop is
  // all there is — which is also how the fixed journey scenes stay renderable.
  const degraded = state.meetingId ? !modelReachable : state.modelReachable === false;
  // Same rule as the languages above: the stream is what the service knows
  // now, the prop is what the panel was handed at mount and is all a fixed
  // scene has.
  const reason = (state.meetingId ? degradedReason : state.degradedReason) ?? null;

  return (
    <main className="panel" aria-label="Elicitation panel">
      <header className="panel-chrome glass">
        <div className="meter">
          <SlotMeter summary={liveCoverage} />
          <CoverageIndicator summary={liveCoverage} />
        </div>
        <div className="chrome-right">
          {/* The stream wins when it has said anything: `state.languages` is
              the fixed prop the screenshot harness renders from, and a live
              meeting should show what the service actually sent. */}
          <LanguageChrome
            languages={streamLanguages.length > 0 ? streamLanguages : state.languages}
            activeTier={state.activeTier ?? null}
          />
          {degraded ? (
            <span className="pill pill--warn" role="status">
              Deterministic only
            </span>
          ) : null}
        </div>
      </header>

      {degraded ? (
        <p className="degraded-note t-footnote" role="status">
          {reason ?? 'The model is unreachable.'} Wording and coverage
          triggers still fire; the slow lane is paused and will catch up.
        </p>
      ) : null}

      <section className="nudge materialize" aria-live="polite">
        <NudgeStack
          active={state.active}
          history={[...state.history]}
          operatorLanguage={state.operatorLanguage}
          onSelect={onSelectNudge}
        />
      </section>

      {/* Everything the operator can do, in one region. On a touch screen it
          docks to the foot of the display as a single material (route.css),
          which is the only part of this panel a thumb can reach without the
          hand leaving the device. Source order matters and is not arbitrary:
          the four chips are laid out two to a row in named grid cells, and
          read row by row that is exactly this order — so the reading order and
          the visual order never come apart. */}
      <footer className="panel-dock">
        <div className="panel-chips">
          {/* Gated on the nudge as well as the slot. Bound to the slot
              alone it rendered permanently, whether anything had been
              suggested or not — so it sat beside "No active nudge" saying
              "Asked it" about nothing, and stayed after the question it
              referred to had been dealt with. FR-6.7 settles which it is:
              it suppresses re-suggestion, and there is nothing to
              re-suggest without a question that was suggested. */}
          {state.active && firstUnfilled ? (
            <AskedItChip slot={firstUnfilled} onAsked={onAsked} />
          ) : null}
          {state.active ? (
            <ParkItChip
              thread={{
                id: state.active.id,
                question: state.active.question,
                operatorAskedAt: null,
              }}
              onParked={onParked}
            />
          ) : null}
          {liveCoverage ? <WhatAmIMissingChip summary={liveCoverage} /> : null}
          {state.active ? (
            <GoDeeperChip
              thread={{
                id: state.active.id,
                question: state.active.question,
                operatorAskedAt: null,
              }}
            />
          ) : null}
        </div>

        {/* FR-6.9: present, but deliberately the quietest thing here — it is an
            escape hatch, not the primary way to work. It stays last so the
            keyboard reaches it in source order after the chips, which are the
            primary input, and because the foot of the dock is where a thumb
            expects a field it has decided to type in. */}
        <EscapeHatchInput onSubmit={onTypedQuestion} />
      </footer>
    </main>
  );
}

/**
 * The mounted panel, over the service.
 *
 * This was the last of the six screens that shipped bound to nothing. It
 * rendered `<OperatorPanel />` with no props at all, so `meetingId` was
 * `undefined`, `useSessionStream` took its `meetingId === null` early return,
 * and the panel never opened a stream for any meeting. Everything downstream
 * followed from that one omission: coverage stayed at its "— / —" placeholder,
 * no nudge ever arrived, all four one-tap responses stayed unrendered because
 * each is gated on coverage or an active nudge, and `recordNudgeDisposition`
 * never fired because it is guarded on `state.meetingId`. A live run recorded
 * the result on a meeting whose session was running.
 *
 * The meeting comes from the same selection the toolbar picker writes, which
 * is where every other screen reads it.
 */
export default function PanelRoute() {
  const engagement = useCurrentEngagement();
  const meeting = useCurrentMeeting(engagement.engagementId);
  const meetingId = meeting.meetingId ?? undefined;

  // Keyed on the meeting for two reasons. `initial` is read once by
  // `useState`, so a meeting id that resolves after the first render would
  // otherwise never reach the stream. And the active nudge and its history
  // belong to the meeting they were raised in — carrying them across a
  // change of meeting would put one client's question on another's panel.
  return <OperatorPanel key={meetingId ?? 'no-meeting'} initial={{ ...EMPTY, meetingId }} />;
}
