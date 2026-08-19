import type {
  CoverageSlot,
  CoverageSummary,
  SessionStreamEvent,
  SessionStreamLane,
  SessionStreamNudge,
} from './types';

interface WireCoverageSlot {
  id: string;
  label: string;
  filled: boolean;
}

interface WireCoverageSummary {
  slots: WireCoverageSlot[];
  time_remaining_ms: number | null;
}

interface WireSessionStreamNudge {
  id: string;
  stub: string;
  question: string;
  trigger_reason: string;
  created_at: number;
}

/**
 * Parses one SSE event off `GET /api/meetings/{id}/session/stream` into a
 * typed domain event. Returns `null` for an event name this panel does not
 * yet know about, so a wire event type added later doesn't throw here -- it
 * is silently ignored until some feature claims it.
 */
export function parseSessionStreamEvent(eventName: string, rawData: string): SessionStreamEvent | null {
  switch (eventName) {
    case 'coverage':
      return { type: 'coverage', coverage: parseCoverageSummary(rawData) };
    case 'nudge':
      return { type: 'nudge', nudge: parseSessionStreamNudge(rawData) };
    case 'lane':
      return { type: 'lane', lane: parseSessionStreamLane(rawData) };
    default:
      return null;
  }
}

function parseCoverageSummary(rawData: string): CoverageSummary {
  const payload = JSON.parse(rawData) as WireCoverageSummary;
  return {
    slots: payload.slots.map(
      (slot): CoverageSlot => ({ id: slot.id, label: slot.label, filled: slot.filled }),
    ),
    timeRemainingMs: payload.time_remaining_ms,
  };
}

function parseSessionStreamNudge(rawData: string): SessionStreamNudge {
  const payload = JSON.parse(rawData) as WireSessionStreamNudge;
  return {
    id: payload.id,
    stub: payload.stub,
    question: payload.question,
    triggerReason: payload.trigger_reason,
    createdAt: payload.created_at,
  };
}

interface WireSessionStreamLane {
  model_reachable: boolean;
  reason: string | null;
}

function parseSessionStreamLane(rawData: string): SessionStreamLane {
  const payload = JSON.parse(rawData) as WireSessionStreamLane;
  return { modelReachable: payload.model_reachable, reason: payload.reason ?? null };
}
