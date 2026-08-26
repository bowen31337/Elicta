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
    expect(screen.getByText(/listening/i)).toBeInTheDocument();
  });

  describe('interface chrome in the operator language (PRD FR-2.25)', () => {
    it('renders chrome copy in English by default', () => {
      render(
        <NudgeStack active={null} history={[makeNudge('a'), makeNudge('b')]} />,
      );
      expect(screen.getByText(/Listening/)).toBeInTheDocument();
      expect(screen.getByLabelText('Prior nudges')).toBeInTheDocument();
    });

    it('renders the empty state and history label in the operator language', () => {
      render(
        <NudgeStack
          active={null}
          history={[makeNudge('a'), makeNudge('b')]}
          operatorLanguage="zh"
        />,
      );
      expect(screen.getByText('正在聆听，暂无提示')).toBeInTheDocument();
      expect(screen.getByLabelText('历史提示')).toBeInTheDocument();
    });

    it('leaves stub, question, and trigger reason untouched by operator language, since they arrive pre-phrased', () => {
      render(<NudgeStack active={makeNudge('a')} history={[]} operatorLanguage="zh" />);
      expect(screen.getByText('stub-a')).toBeInTheDocument();
      expect(screen.getByText('question a?')).toBeInTheDocument();
      expect(screen.getByText('reason-a')).toBeInTheDocument();
    });

    it('falls back to English chrome for an operator language with no translation', () => {
      render(
        <NudgeStack
          active={null}
          history={[makeNudge('a')]}
          operatorLanguage="fr"
        />,
      );
      expect(screen.getByText(/Listening/)).toBeInTheDocument();
      expect(screen.getByLabelText('Prior nudges')).toBeInTheDocument();
    });
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

describe('reaching a nudge that has receded', () => {
  /**
   * Reported with eight on screen: "there is no way to navigate to any of
   * it". Every chip acts on the active nudge, and a history entry was two
   * spans in a list item — not focusable, not pressable. So the moment a
   * second nudge arrived the first became unactionable for good, and in a
   * meeting where one can arrive every minute that is most of them.
   *
   * FR-6.3 constrains *prominence* — one shown prominently at a time — not
   * reachability. Bringing one forward keeps exactly one prominent; it just
   * lets the operator choose which.
   */
  const HISTORY: Nudge[] = [
    { id: 'n-2', stub: 'Second', question: 'The second question?', triggerReason: 'r2', createdAt: 2 },
    { id: 'n-1', stub: 'First', question: 'The first question?', triggerReason: 'r1', createdAt: 1 },
  ];
  const ACTIVE: Nudge = {
    id: 'n-3',
    stub: 'Third',
    question: 'The third question?',
    triggerReason: 'r3',
    createdAt: 3,
  };

  it('says the list is there and what pressing it does', async () => {
    /* Reported as "when one nudge is parked, there is no way to view other
       nudges" — and mechanically there was: every entry is a button. What
       there was not was any sign of it. The list carried an accessible name
       and nothing visible, so a sighted operator saw a dim column of
       near-identical stubs under an empty state, with no heading and no
       affordance. A way that cannot be found is not a way. */
    render(<NudgeStack active={ACTIVE} history={HISTORY} onSelect={() => {}} />);

    expect(screen.getByText(/earlier/i)).toBeInTheDocument();
    expect(screen.getByText(/bring (one )?back|tap/i)).toBeInTheDocument();
  });

  it('offers each past nudge as something that can be pressed', () => {
    render(<NudgeStack active={ACTIVE} history={HISTORY} onSelect={() => {}} />);

    expect(screen.getAllByRole('button', { name: /Second|First/ })).toHaveLength(2);
  });

  it('says which nudge pressing one would bring forward', () => {
    render(<NudgeStack active={ACTIVE} history={HISTORY} onSelect={() => {}} />);

    expect(
      screen.getByRole('button', { name: /Bring back Second/i }),
    ).toBeInTheDocument();
  });

  it('hands the whole nudge back, not just its id', () => {
    /* The caller has to put the displaced one somewhere, and it needs the
       nudge to do it — an id would make it look the demoted one up in a list
       it is in the middle of rewriting. */
    const onSelect = vi.fn();
    render(<NudgeStack active={ACTIVE} history={HISTORY} onSelect={onSelect} />);

    screen.getByRole('button', { name: /Bring back First/i }).click();

    expect(onSelect).toHaveBeenCalledWith(HISTORY[1]);
  });

  it('leaves the active nudge unpressable, since it is already here', () => {
    render(<NudgeStack active={ACTIVE} history={HISTORY} onSelect={() => {}} />);

    expect(screen.queryByRole('button', { name: /Bring back Third/i })).toBeNull();
  });

  it('still renders without a handler, for a screenshot that cannot press anything', () => {
    render(<NudgeStack active={ACTIVE} history={HISTORY} />);

    expect(screen.getByText('Second')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Bring back/i })).toBeNull();
  });
});
