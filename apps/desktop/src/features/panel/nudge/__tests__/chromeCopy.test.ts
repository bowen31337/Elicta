import { describe, expect, it } from 'vitest';
import { getNudgeChromeCopy } from '../chromeCopy';

describe('getNudgeChromeCopy', () => {
  it('defaults to English when no operator language is given', () => {
    expect(getNudgeChromeCopy()).toEqual({
      emptyState: 'No active nudge',
      historyLabel: 'Prior nudges',
    });
  });

  it('resolves Mandarin chrome copy for "zh"', () => {
    expect(getNudgeChromeCopy('zh')).toEqual({
      emptyState: '当前没有提示',
      historyLabel: '历史提示',
    });
  });

  it('matches on the BCP-47 primary subtag, ignoring region and case', () => {
    expect(getNudgeChromeCopy('zh-CN')).toEqual(getNudgeChromeCopy('zh'));
    expect(getNudgeChromeCopy('ZH')).toEqual(getNudgeChromeCopy('zh'));
  });

  it('falls back to English for an operator language with no translation yet', () => {
    expect(getNudgeChromeCopy('fr')).toEqual(getNudgeChromeCopy('en'));
  });
});
