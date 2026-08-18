import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { NudgeStack, historyOpacity } from '../NudgeStack';
import type { Nudge } from '../types';

function makeNudge(id: string): Nudge {
  return {
    id,
    stub: `stub-${id}`,
    question: `question ${id}?`,
    triggerReason: `reason-${id}`,
    createdAt: 0,
  };
}

describe('NudgeStack', () => {
  it('renders the active nudge prominently', () => {
    render(<NudgeStack active={makeNudge('a')} history={[]} />);
    expect(screen.getByText('stub-a')).toBeInTheDocument();
    expect(screen.getByText('question a?')).toBeInTheDocument();
  });

  describe('glanceable stub above the full question, at smaller weight (PRD FR-6.2)', () => {
    it('positions the stub before the full question in document order', () => {
      render(<NudgeStack active={makeNudge('a')} history={[]} />);
      const stub = screen.getByText('stub-a');
      const question = screen.getByText('question a?');
      expect(
        stub.compareDocumentPosition(question) & Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();
    });

    it('renders the stub and question with distinct weight classes so the question reads at smaller weight', () => {
      render(<NudgeStack active={makeNudge('a')} history={[]} />);
      const stub = screen.getByText('stub-a');
      const question = screen.getByText('question a?');
      expect(stub).toHaveClass('nudge-stack__stub');
      expect(question).toHaveClass('nudge-stack__question');
      expect(stub.className).not.toBe(question.className);
    });
  });

  it('shows the trigger reason alongside the active nudge', () => {
    render(<NudgeStack active={makeNudge('a')} history={[]} />);
    expect(screen.getByText('reason-a')).toBeInTheDocument();
  });

  it('shows the trigger reason alongside every history entry', () => {
    render(
      <NudgeStack
        active={makeNudge('c')}
        history={[makeNudge('b'), makeNudge('a')]}
      />
    );
    expect(screen.getByText('reason-b')).toBeInTheDocument();
    expect(screen.getByText('reason-a')).toBeInTheDocument();
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

  describe('single-paint rendering (PRD FR-6.4)', () => {
    beforeEach(() => {
      vi.useFakeTimers();
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    it('renders the nudge complete on first paint, with nothing left to reveal later', () => {
      render(<NudgeStack active={makeNudge('a')} history={[]} />);

      // The stub, question, and trigger reason are all present immediately —
      // no typing animation or streaming is at play (design system: "no
      // typing animation, no streaming" for nudge entry).
      expect(screen.getByText('stub-a')).toBeInTheDocument();
      expect(screen.getByText('question a?')).toBeInTheDocument();
      expect(screen.getByText('reason-a')).toBeInTheDocument();

      vi.advanceTimersByTime(10_000);

      // Nothing streams in afterward: the same complete content is still
      // there, unchanged, because the component has no timers or effects
      // that could reveal it incrementally.
      expect(screen.getByText('stub-a')).toBeInTheDocument();
      expect(screen.getByText('question a?')).toBeInTheDocument();
      expect(screen.getByText('reason-a')).toBeInTheDocument();
    });

    it('replaces the active nudge with the new one whole, in one render, never a mix of old and new fields', () => {
      const { rerender } = render(<NudgeStack active={makeNudge('a')} history={[]} />);
      expect(screen.getByText('question a?')).toBeInTheDocument();

      rerender(<NudgeStack active={makeNudge('b')} history={[makeNudge('a')]} />);

      // The new nudge's fields are all present together; none of the old
      // active nudge's fields linger in the prominent slot.
      expect(screen.getByText('stub-b')).toBeInTheDocument();
      expect(screen.getByText('question b?')).toBeInTheDocument();
      expect(screen.getByText('reason-b')).toBeInTheDocument();
      expect(screen.queryByText('question a?')).not.toBeInTheDocument();
    });
  });
});
