import { describe, expect, it, vi } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { useEscapeHatchInput } from '../useEscapeHatchInput';

describe('useEscapeHatchInput', () => {
  it('tracks typed value', () => {
    const { result } = renderHook(() => useEscapeHatchInput({ onSubmit: vi.fn() }));
    act(() => result.current.setValue('why did you say that'));
    expect(result.current.value).toBe('why did you say that');
  });

  it('submits the trimmed text with a timestamp and clears the field', () => {
    const onSubmit = vi.fn();
    const now = () => 1234;
    const { result } = renderHook(() => useEscapeHatchInput({ onSubmit, now }));

    act(() => result.current.setValue('  another angle?  '));
    act(() => result.current.submit());

    expect(onSubmit).toHaveBeenCalledWith({ text: 'another angle?', submittedAt: 1234 });
    expect(result.current.value).toBe('');
  });

  it('does not submit blank or whitespace-only text', () => {
    const onSubmit = vi.fn();
    const { result } = renderHook(() => useEscapeHatchInput({ onSubmit }));

    act(() => result.current.setValue('   '));
    act(() => result.current.submit());

    expect(onSubmit).not.toHaveBeenCalled();
    expect(result.current.value).toBe('   ');
  });

  it('does nothing when submitted with an empty field', () => {
    const onSubmit = vi.fn();
    const { result } = renderHook(() => useEscapeHatchInput({ onSubmit }));

    act(() => result.current.submit());

    expect(onSubmit).not.toHaveBeenCalled();
  });
});
