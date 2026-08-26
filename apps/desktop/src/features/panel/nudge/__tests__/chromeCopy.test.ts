import { describe, expect, it } from 'vitest';
import { getNudgeChromeCopy } from '../chromeCopy';

describe('getNudgeChromeCopy', () => {
  it('defaults to English when no operator language is given', () => {
    expect(getNudgeChromeCopy()).toEqual({
      emptyState: 'Listening — nothing worth asking yet',
      historyLabel: 'Prior nudges',
      historyHint: 'Earlier — tap one to bring it back',
      historyWaiting: '{n} still waiting',
    });
  });

  it('resolves Mandarin chrome copy for "zh"', () => {
    expect(getNudgeChromeCopy('zh')).toEqual({
      emptyState: '正在聆听，暂无提示',
      historyLabel: '历史提示',
      historyHint: '之前的提示 — 点按可重新显示',
      historyWaiting: '{n} 条待处理',
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
