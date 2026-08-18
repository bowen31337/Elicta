import { describe, expect, it } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { useLanguagePanel } from '../useLanguagePanel';

describe('useLanguagePanel', () => {
  it('starts with no languages and no active tier', () => {
    const { result } = renderHook(() => useLanguagePanel());
    expect(result.current.languages).toEqual([]);
    expect(result.current.activeTier).toBeNull();
  });

  it('adds a confident observation and sets the active tier', () => {
    const { result } = renderHook(() => useLanguagePanel());
    act(() => result.current.observe({ language: 'en', tier: 'tier-1', confidence: 0.9 }));

    expect(result.current.languages.map((l) => l.language)).toEqual(['en']);
    expect(result.current.activeTier).toBe('tier-1');
  });

  it('accumulates every detected language while updating the active tier', () => {
    const { result } = renderHook(() => useLanguagePanel());
    act(() => result.current.observe({ language: 'en', tier: 'tier-1', confidence: 0.9 }));
    act(() => result.current.observe({ language: 'vi', tier: 'tier-2', confidence: 0.9 }));

    expect(result.current.languages.map((l) => l.language)).toEqual(['en', 'vi']);
    expect(result.current.activeTier).toBe('tier-2');
  });

  it('ignores a low-confidence observation', () => {
    const { result } = renderHook(() => useLanguagePanel());
    act(() => result.current.observe({ language: 'en', tier: 'tier-1', confidence: 0.2 }));

    expect(result.current.languages).toEqual([]);
    expect(result.current.activeTier).toBeNull();
  });

  it('honours a custom minimum confidence', () => {
    const { result } = renderHook(() => useLanguagePanel(0.95));
    act(() => result.current.observe({ language: 'en', tier: 'tier-1', confidence: 0.9 }));
    expect(result.current.languages).toEqual([]);

    act(() => result.current.observe({ language: 'en', tier: 'tier-1', confidence: 0.96 }));
    expect(result.current.languages).toHaveLength(1);
  });
});
