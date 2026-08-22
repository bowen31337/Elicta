import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { LanguageChrome } from '../LanguageChrome';
import type { DetectedLanguage } from '../types';

function lang(language: string, tier: DetectedLanguage['tier'] = 'tier-1'): DetectedLanguage {
  // These fixtures are all languages that were heard: the expected-but-unheard
  // case has its own file, because it is a different claim.
  return { language, tier, heard: true, confidence: 0.9 };
}

describe('LanguageChrome', () => {
  it('renders every detected language', () => {
    render(<LanguageChrome languages={[lang('en'), lang('zh')]} activeTier="tier-1" />);
    expect(screen.getByText('EN')).toBeInTheDocument();
    expect(screen.getByText('ZH')).toBeInTheDocument();
  });

  it('shows an empty state when no language has been detected', () => {
    render(<LanguageChrome languages={[]} activeTier={null} />);
    expect(screen.getByText(/no language detected/i)).toBeInTheDocument();
  });

  it('renders the active support tier badge', () => {
    render(<LanguageChrome languages={[lang('vi', 'tier-2')]} activeTier="tier-2" />);
    expect(screen.getByText('Tier 2')).toBeInTheDocument();
  });

  it('renders no tier badge when the active tier is unknown', () => {
    render(<LanguageChrome languages={[]} activeTier={null} />);
    expect(screen.queryByText(/^Tier /)).not.toBeInTheDocument();
  });

  it('exposes the capability summary as the tier badge tooltip', () => {
    render(<LanguageChrome languages={[lang('en')]} activeTier="tier-1" />);
    expect(screen.getByText('Tier 1').getAttribute('title')).toContain('Full support');
  });
});
