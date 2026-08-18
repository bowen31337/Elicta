import { afterEach, describe, expect, it } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { useOperatorLanguage } from '../useOperatorLanguage';
import { loadOperatorLanguage } from '../operatorLanguageStore';

afterEach(() => {
  window.localStorage.clear();
});

describe('useOperatorLanguage', () => {
  it('defaults to English when nothing is persisted for the user', () => {
    const { result } = renderHook(() => useOperatorLanguage('user-1'));
    expect(result.current.operatorLanguage).toBe('en');
  });

  it('loads a previously persisted operator language on mount', () => {
    window.localStorage.setItem('elicta.nudge.operatorLanguage.user-1', 'zh');
    const { result } = renderHook(() => useOperatorLanguage('user-1'));
    expect(result.current.operatorLanguage).toBe('zh');
  });

  it('persists the operator language across a remount for the same user (PRD FR-2.26)', () => {
    const { result, unmount } = renderHook(() => useOperatorLanguage('user-1'));
    act(() => result.current.setOperatorLanguage('zh'));
    expect(result.current.operatorLanguage).toBe('zh');
    unmount();

    const remounted = renderHook(() => useOperatorLanguage('user-1'));
    expect(remounted.result.current.operatorLanguage).toBe('zh');
  });

  it('writes through to storage immediately so the choice survives a reload', () => {
    const { result } = renderHook(() => useOperatorLanguage('user-1'));
    act(() => result.current.setOperatorLanguage('fr'));
    expect(loadOperatorLanguage('user-1')).toBe('fr');
  });

  it('keeps each user\'s setting independent', () => {
    const first = renderHook(() => useOperatorLanguage('user-1'));
    act(() => first.result.current.setOperatorLanguage('zh'));

    const second = renderHook(() => useOperatorLanguage('user-2'));
    expect(second.result.current.operatorLanguage).toBe('en');
  });

  it('switches to the new user\'s persisted setting when userId changes', () => {
    window.localStorage.setItem('elicta.nudge.operatorLanguage.user-2', 'fr');
    const { result, rerender } = renderHook(({ userId }) => useOperatorLanguage(userId), {
      initialProps: { userId: 'user-1' },
    });
    expect(result.current.operatorLanguage).toBe('en');

    rerender({ userId: 'user-2' });
    expect(result.current.operatorLanguage).toBe('fr');
  });

  it('honors a custom default language when nothing is persisted', () => {
    const { result } = renderHook(() => useOperatorLanguage('user-1', 'zh'));
    expect(result.current.operatorLanguage).toBe('zh');
  });
});
