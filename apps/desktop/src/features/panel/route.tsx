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

export function OperatorPanel({ initial = EMPTY }: { initial?: PanelState }) {
  const [state, setState] = useState<PanelState>(initial);

  // The live session drives the panel when there is one. Coverage arrives as
  // the current summary rather than a diff, and each nudge replaces the
  // active one — the previous nudge recedes into history rather than being
  // dropped, so the operator can still see what they just declined.
  const { coverage, modelReachable, degradedReason } = useSessionStream(state.meetingId ?? null, {
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

  return (
    <main className="panel" aria-label="Elicitation panel">
      <header className="panel-chrome glass">
        <div className="meter">
          <SlotMeter summary={liveCoverage} />
          <CoverageIndicator summary={liveCoverage} />
        </div>
        <div className="chrome-right">
          <LanguageChrome languages={state.languages} activeTier={state.activeTier ?? null} />
          {degraded ? (
            <span className="pill pill--warn" role="status">
              Deterministic only
            </span>
          ) : null}
        </div>
      </header>

      {degraded ? (
        <p className="degraded-note t-footnote" role="status">
          {degradedReason ?? 'The model is unreachable.'} Wording and coverage
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

export default function PanelRoute() {
  return <OperatorPanel />;
}
