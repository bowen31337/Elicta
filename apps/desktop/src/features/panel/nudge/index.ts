export type { Nudge } from './types';
export { NudgeStack, historyOpacity } from './NudgeStack';
export type { NudgeStackProps } from './NudgeStack';
export { useNudgeStack } from './useNudgeStack';
export type { NudgeStackState, UseNudgeStackResult } from './useNudgeStack';

export { NUDGE_SURFACE_WINDOW_MS, canSurfaceNudge } from './nudgeRateGate';
export {
  createNudgeQueue,
  enqueueNudge,
  renderNudgeQueue,
} from './nudgeQueue';
export type { NudgeQueueState, NudgeRenderResult } from './nudgeQueue';
export { useNudgeQueue } from './useNudgeQueue';
export type { UseNudgeQueueOptions, UseNudgeQueueResult } from './useNudgeQueue';
