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
      setState((current) => ({
        ...current,
        active: nudge,
        history: current.active ? [current.active, ...current.history] : current.history,
      })),
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
  };

  const onParked = () => {
    if (state.meetingId && state.active) {
      void recordNudgeDisposition({
        meetingId: state.meetingId,
        nudgeId: state.active.id,
        disposition: 'parked',
      });
    }
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
        />
      </section>

      <footer className="panel-chips">
        {firstUnfilled ? <AskedItChip slot={firstUnfilled} onAsked={onAsked} /> : null}
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
      </footer>

      {/* FR-6.9: present, but deliberately the quietest thing here — it is an
          escape hatch, not the primary way to work. */}
      <EscapeHatchInput onSubmit={() => undefined} />

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
