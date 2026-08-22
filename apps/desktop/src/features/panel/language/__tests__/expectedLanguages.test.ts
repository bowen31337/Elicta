import { describe, expect, it } from 'vitest';

import { createLanguagePanelState, expectLanguage, observeLanguage } from '../languagePanel';

/**
 * A language the room is expected to use, as distinct from one that has been
 * heard.
 *
 * The panel strip read "No language detected" for every meeting, because the
 * session stream had no language frame and the state started empty. The
 * service knew the answer the whole time — it derives the expected set when an
 * engagement is created — so the strip can say what it is listening for before
 * anything transcribes. What it must not do is call that a detection.
 */
describe('a language the room is expected to use', () => {
  it('appears on the strip', () => {
    const state = expectLanguage(createLanguagePanelState(), 'zh');

    expect(state.languages.map((l) => l.language)).toEqual(['zh']);
  });

  it('is marked expected rather than heard', () => {
    const state = expectLanguage(createLanguagePanelState(), 'zh');

    expect(state.languages[0].heard).toBe(false);
  });

  it('carries no tier, because nothing has been observed to assign one', () => {
    // Tier is computed per observation by the backend. Inventing one here
    // would put a support claim on screen that nothing measured.
    const state = expectLanguage(createLanguagePanelState(), 'zh');

    expect(state.languages[0].tier).toBeNull();
    expect(state.activeTier).toBeNull();
  });

  it('matches on the primary subtag, like every other language comparison here', () => {
    const state = expectLanguage(createLanguagePanelState(), 'zh-Hans-CN');

    expect(state.languages[0].language).toBe('zh');
  });

  it('is not added twice when the stream repeats it', () => {
    const once = expectLanguage(createLanguagePanelState(), 'en');
    const twice = expectLanguage(once, 'en');

    expect(twice.languages).toHaveLength(1);
  });

  it('is upgraded to heard when that language is actually observed', () => {
    const expected = expectLanguage(createLanguagePanelState(), 'zh');

    const heard = observeLanguage(expected, {
      language: 'zh-CN',
      tier: 'tier-2',
      confidence: 0.9,
    });

    expect(heard.languages).toHaveLength(1);
    expect(heard.languages[0].heard).toBe(true);
    expect(heard.languages[0].tier).toBe('tier-2');
    expect(heard.activeTier).toBe('tier-2');
  });

  it('does not un-hear a language by expecting it afterwards', () => {
    const heard = observeLanguage(createLanguagePanelState(), {
      language: 'en',
      tier: 'tier-1',
      confidence: 0.95,
    });

    const after = expectLanguage(heard, 'en');

    expect(after.languages[0].heard).toBe(true);
    expect(after.languages[0].tier).toBe('tier-1');
  });
});
