import { describe, expect, it } from 'vitest';
import { createLanguagePanelState, observeLanguage } from '../languagePanel';
import type { LanguageObservation } from '../types';

function observation(overrides: Partial<LanguageObservation> = {}): LanguageObservation {
  return { language: 'en', tier: 'tier-1', confidence: 0.9, ...overrides };
}

describe('observeLanguage', () => {
  it('adds a confident observation to the panel', () => {
    const state = observeLanguage(createLanguagePanelState(), observation());
    expect(state.languages).toEqual([{ language: 'en', tier: 'tier-1', confidence: 0.9 }]);
    expect(state.activeTier).toBe('tier-1');
  });

  it('keeps every distinct language visible at once', () => {
    let state = createLanguagePanelState();
    state = observeLanguage(state, observation({ language: 'en', tier: 'tier-1' }));
    state = observeLanguage(state, observation({ language: 'zh', tier: 'tier-1' }));

    expect(state.languages.map((l) => l.language)).toEqual(['en', 'zh']);
  });

  it('lists languages in first-detected order and does not reorder on re-observation', () => {
    let state = createLanguagePanelState();
    state = observeLanguage(state, observation({ language: 'vi', tier: 'tier-2' }));
    state = observeLanguage(state, observation({ language: 'en', tier: 'tier-1' }));
    state = observeLanguage(state, observation({ language: 'zh', tier: 'tier-1' }));
    state = observeLanguage(state, observation({ language: 'vi', tier: 'tier-2', confidence: 0.95 }));

    expect(state.languages.map((l) => l.language)).toEqual(['vi', 'en', 'zh']);
  });

  it('drops a low-confidence observation and leaves the panel untouched', () => {
    const before = createLanguagePanelState();
    const after = observeLanguage(before, observation({ confidence: 0.2 }));

    expect(after).toEqual(before);
  });

  it('does not let a low-confidence observation remove an already-detected language', () => {
    let state = createLanguagePanelState();
    state = observeLanguage(state, observation({ language: 'en', confidence: 0.9 }));
    state = observeLanguage(state, observation({ language: 'en', confidence: 0.1, tier: 'tier-3' }));

    expect(state.languages).toEqual([{ language: 'en', tier: 'tier-1', confidence: 0.9 }]);
  });

  it('observing one language never removes another', () => {
    let state = createLanguagePanelState();
    state = observeLanguage(state, observation({ language: 'en' }));
    state = observeLanguage(state, observation({ language: 'zh' }));

    expect(state.languages.map((l) => l.language)).toEqual(['en', 'zh']);
  });

  it('refreshes confidence and tier in place on a later confident observation', () => {
    let state = createLanguagePanelState();
    state = observeLanguage(state, observation({ language: 'vi', tier: 'tier-2', confidence: 0.7 }));
    state = observeLanguage(state, observation({ language: 'vi', tier: 'tier-3', confidence: 0.95 }));

    expect(state.languages).toEqual([{ language: 'vi', tier: 'tier-3', confidence: 0.95 }]);
  });

  it('collapses BCP-47 region and script subtags and case to one entry', () => {
    let state = createLanguagePanelState();
    state = observeLanguage(state, observation({ language: 'en-US' }));
    state = observeLanguage(state, observation({ language: 'EN' }));

    expect(state.languages).toHaveLength(1);
    expect(state.languages[0].language).toBe('en');
  });

  it('advances the active tier to whichever language was most recently observed confidently', () => {
    let state = createLanguagePanelState();
    state = observeLanguage(state, observation({ language: 'en', tier: 'tier-1' }));
    expect(state.activeTier).toBe('tier-1');

    state = observeLanguage(state, observation({ language: 'vi', tier: 'tier-2' }));
    expect(state.activeTier).toBe('tier-2');
  });

  it('respects a custom confidence threshold', () => {
    const strict = createLanguagePanelState();
    expect(observeLanguage(strict, observation({ confidence: 0.9 }), 0.95)).toEqual(strict);
    expect(observeLanguage(strict, observation({ confidence: 0.96 }), 0.95).languages).toHaveLength(1);
  });

  it('starts with no languages and no active tier', () => {
    const state = createLanguagePanelState();
    expect(state.languages).toEqual([]);
    expect(state.activeTier).toBeNull();
  });
});
