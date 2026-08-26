/**
 * Static interface-chrome strings for the nudge stack — everything in
 * {@link NudgeStack} that isn't part of a `Nudge` itself (the empty-state
 * message, the history list's accessible label). These render in the
 * operator's language, independently of whichever language the meeting is
 * in (PRD FR-2.25/2.26), which is why they're keyed here rather than
 * hardcoded in the component.
 *
 * `stub` and `triggerReason` on `Nudge` are not covered by this file: per
 * PRD FR-2.25 they too belong in the operator's language, but that
 * phrasing is chosen upstream (PRD §8.2b) and arrives on the `Nudge`
 * already in the right language, same as `question` arrives already in
 * the meeting language (FR-2.24). This file only owns the chrome that the
 * component itself renders.
 */
export interface NudgeChromeCopy {
  /** Shown in place of the active nudge when there is none. */
  readonly emptyState: string;
  /** Accessible label for the receded-nudge history list. */
  readonly historyLabel: string;
  /**
   * The same list, said out loud on the screen, when the entries can be
   * pressed. The label alone was accessible-only, so nothing visible marked
   * a column of dimmed stubs as anything an operator could act on.
   */
  readonly historyHint: string;
}

const EN: NudgeChromeCopy = {
  /* "No active nudge" is accurate and reads as a fault — it describes what
     is absent rather than what is happening, and an operator who has just
     parked a question cannot tell a working panel from a broken one. This
     is the resting state for most of a meeting, so it should say the system
     is doing its job. */
  emptyState: 'Listening — nothing worth asking yet',
  historyLabel: 'Prior nudges',
  historyHint: 'Earlier — tap one to bring it back',
};

/**
 * Chrome copy by operator language, keyed on the BCP-47 primary subtag.
 * English is both the fallback and the default — an operator language this
 * table has no entry for renders in English rather than a blank chrome.
 */
const NUDGE_CHROME_COPY: Record<string, NudgeChromeCopy> = {
  en: EN,
  zh: {
    emptyState: '正在聆听，暂无提示',
    historyLabel: '历史提示',
    historyHint: '之前的提示 — 点按可重新显示',
  },
};

/**
 * Mirrors the BCP-47 primary-subtag matching used for detected languages
 * (`primarySubtag` in `../language/languagePanel.ts`): "en-US" and "en"
 * resolve to the same chrome copy.
 */
function primarySubtag(operatorLanguage: string): string {
  return operatorLanguage.split(/[-_]/)[0]?.toLowerCase() || operatorLanguage;
}

/**
 * Resolves interface-chrome copy for an operator language, falling back to
 * English for an unset or unrecognised tag rather than throwing — a chrome
 * with no translation yet should still be legible, not broken.
 */
export function getNudgeChromeCopy(operatorLanguage?: string): NudgeChromeCopy {
  if (!operatorLanguage) {
    return EN;
  }

  return NUDGE_CHROME_COPY[primarySubtag(operatorLanguage)] ?? EN;
}
