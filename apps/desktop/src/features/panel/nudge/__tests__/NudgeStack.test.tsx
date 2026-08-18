import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { NudgeStack, historyOpacity } from '../NudgeStack';
import type { Nudge } from '../types';

function makeNudge(id: string): Nudge {
  return { id, stub: `stub-${id}`, question: `question ${id}?`, createdAt: 0 };
}

describe('NudgeStack', () => {
  it('renders the active nudge prominently', () => {
    render(<NudgeStack active={makeNudge('a')} history={[]} />);
    expect(screen.getByText('stub-a')).toBeInTheDocument();
    expect(screen.getByText('question a?')).toBeInTheDocument();
  });

  it('renders exactly one prominent nudge even with a long history', () => {
    render(
      <NudgeStack
        active={makeNudge('c')}
        history={[makeNudge('b'), makeNudge('a')]}
      />
    );
    expect(screen.getAllByRole('article')).toHaveLength(1);
  });

  it('dims prior nudges, most recent first, and never fully fades them', () => {
    render(
      <NudgeStack
        active={makeNudge('c')}
        history={[makeNudge('b'), makeNudge('a')]}
      />
    );
    const items = screen.getAllByRole('listitem');
    const opacities = items.map((el) => Number(el.style.opacity));
    expect(opacities[0]).toBeGreaterThan(opacities[1]);
    opacities.forEach((opacity) => {
      expect(opacity).toBeLessThan(1);
      expect(opacity).toBeGreaterThan(0);
    });
  });

  it('shows an empty state when there is no active nudge', () => {
    render(<NudgeStack active={null} history={[]} />);
    expect(screen.getByText(/no active nudge/i)).toBeInTheDocument();
  });

  it('floors history opacity instead of letting it reach zero', () => {
    expect(historyOpacity(0)).toBeGreaterThan(historyOpacity(10));
    expect(historyOpacity(10)).toBeGreaterThan(0);
  });
});
