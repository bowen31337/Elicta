import { afterEach, describe, expect, it } from 'vitest';
import { loadOperatorLanguage, saveOperatorLanguage } from '../operatorLanguageStore';

afterEach(() => {
  window.localStorage.clear();
});

describe('operatorLanguageStore', () => {
  it('returns null for a user with nothing persisted yet', () => {
    expect(loadOperatorLanguage('user-1')).toBeNull();
  });

  it('round-trips a saved operator language for a user', () => {
    saveOperatorLanguage('user-1', 'zh');
    expect(loadOperatorLanguage('user-1')).toBe('zh');
  });

  it('overwrites a previously saved value for the same user', () => {
    saveOperatorLanguage('user-1', 'zh');
    saveOperatorLanguage('user-1', 'fr');
    expect(loadOperatorLanguage('user-1')).toBe('fr');
  });

  it('scopes persistence per user so one user cannot read another user\'s setting', () => {
    saveOperatorLanguage('user-1', 'zh');
    expect(loadOperatorLanguage('user-2')).toBeNull();
  });
});
