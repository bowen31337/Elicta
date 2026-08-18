export type { CoverageSlot, CoverageSummary, SessionStreamEvent, SessionStreamNudge } from './types';

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
