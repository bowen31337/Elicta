export type {
  CoverageSlot,
  CoverageSummary,
  SessionStopResult,
  SessionStreamEvent,
  SessionStreamNudge,
} from './types';

export { parseSessionStreamEvent } from './sessionStreamEvents';
export { countFilledSlots, formatTimeRemaining } from './coverageProgress';

export { CoverageIndicator } from './CoverageIndicator';
export type { CoverageIndicatorProps } from './CoverageIndicator';

export { useSessionStream } from './useSessionStream';
export type {
  SessionStreamSource,
  SessionStreamSourceFactory,
  UseSessionStreamOptions,
  UseSessionStreamResult,
} from './useSessionStream';

export { stopSession } from './stopSession';
export type { StopSessionFetch, StopSessionOptions } from './stopSession';

export { useStopSession } from './useStopSession';
export type { StopSessionStatus, UseStopSessionResult } from './useStopSession';
