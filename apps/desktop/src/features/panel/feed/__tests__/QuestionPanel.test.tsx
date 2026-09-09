import { describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { QuestionPanel, recededOpacity } from '../QuestionPanel';
import type { Nudge } from '../../nudge/types';

/**
 * The invariants that have to survive every rearrangement of this screen.
 *
 * Each encodes a decision somebody made for a reason: FR-6.3's single
 * prominent question, FR-5.11's trigger reason surviving a question receding,
 * the opacity floor that keeps a receded entry above WCAG 1.4.3, and the fact
 * that a receded question stays reachable at all. They have now outlived a
 * separate nudge stack, a merged stream, and this pair of panels.
 */
function nudge(id: string, over: Partial<Nudge> = {}): Nudge {
  return {
    id,
    stub: `Stub ${id}`,
    question: `Question ${id}?`,
    triggerReason: 'unquantified adjective — "fast"',
    createdAt: 1_000,
    ...over,
  };
}

function said(seq: number, text: string, at: number | null) {
  return { seq, text, speaker: null, at, final: true };
}

describe('one question is prominent at a time', () => {
  it('renders it with stub, wording and reason', () => {
    render(<QuestionPanel active={nudge('a')} history={[]} transcript={[]} />);

    expect(screen.getByText('Stub a')).toBeInTheDocument();
    expect(screen.getByText('Question a?')).toBeInTheDocument();
    // FR-5.11: the reason is what lets an operator calibrate trust.
    expect(screen.getByText(/unquantified adjective/)).toBeInTheDocument();
  });

  it('shows only the live one in full', () => {
    render(<QuestionPanel active={nudge('b')} history={[nudge('a')]} transcript={[]} />);

    expect(screen.getByText('Question b?')).toBeInTheDocument();
    expect(screen.queryByText('Question a?')).not.toBeInTheDocument();
  });

  it('says the gate is watching when nothing is live', () => {
    render(<QuestionPanel active={null} history={[]} transcript={[]} />);
    expect(screen.getByText(/nothing worth asking/i)).toBeInTheDocument();
  });

  it('keeps the reason on a question that has receded', () => {
    render(
      <QuestionPanel active={null} history={[nudge('a')]} transcript={[]} onSelect={() => {}} />,
    );
    const row = screen.getByRole('button', { name: /bring back/i });
    expect(within(row).getByText(/unquantified adjective/)).toBeInTheDocument();
  });
});

describe('what the question is about', () => {
  it('quotes the line it reacted to', () => {
    // The panels are separate, so proximity cannot carry this. A question
    // about "a few" is worth asking because somebody just said "a few";
    // without the line it is a question from nowhere.
    render(
      <QuestionPanel
        active={nudge('a', { createdAt: 300 })}
        history={[]}
        transcript={[said(0, 'A few, usually.', 200), said(1, 'Later.', 900)]}
      />,
    );

    expect(screen.getByText('A few, usually.')).toBeInTheDocument();
  });

  it('quotes nothing when there is no line it could have reacted to', () => {
    // A question the operator typed, or one restored from an earlier session.
    // Naming a line it cannot have reacted to would be a fabrication.
    render(
      <QuestionPanel
        active={nudge('a', { createdAt: 50 })}
        history={[]}
        transcript={[said(0, 'Later.', 900)]}
      />,
    );

    expect(screen.queryByText('Later.')).not.toBeInTheDocument();
  });
});

describe('a question that has receded stays reachable', () => {
  it('is a button named by what pressing it does', () => {
    // Read out of context a stub says nothing about the consequence, and
    // several stubs on one trigger can be identical.
    render(
      <QuestionPanel active={null} history={[nudge('a')]} transcript={[]} onSelect={() => {}} />,
    );
    expect(screen.getByRole('button', { name: 'Bring back Stub a' })).toBeInTheDocument();
  });

  it('hands the question back when pressed', async () => {
    const onSelect = vi.fn();
    const earlier = nudge('a');
    render(
      <QuestionPanel active={null} history={[earlier]} transcript={[]} onSelect={onSelect} />,
    );

    await userEvent.click(screen.getByRole('button', { name: /bring back/i }));
    expect(onSelect).toHaveBeenCalledWith(earlier);
  });

  it('renders as plain text where there is nothing to press', () => {
    render(<QuestionPanel active={null} history={[nudge('a')]} transcript={[]} />);
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
    expect(screen.getByText('Stub a')).toBeInTheDocument();
  });

  it('never dims a question below the contrast floor', () => {
    // Element opacity multiplies ink that is already reduced, so a receded
    // entry composites toward the background twice. Below ~0.76 the text
    // stops clearing WCAG 1.4.3.
    expect(recededOpacity(0)).toBeGreaterThan(recededOpacity(10));
    expect(recededOpacity(50)).toBeGreaterThanOrEqual(0.76);
  });
});

describe('what the operator already did with a question', () => {
  it('is marked, so it is not asked twice', () => {
    render(
      <QuestionPanel
        active={null}
        history={[nudge('a', { disposition: 'parked' })]}
        transcript={[]}
        onSelect={() => {}}
      />,
    );
    expect(screen.getByText('Parked')).toBeInTheDocument();
  });

  it('is unmarked where they did nothing, so the marks stay visible', () => {
    render(
      <QuestionPanel active={null} history={[nudge('a')]} transcript={[]} onSelect={() => {}} />,
    );
    expect(screen.queryByText('Parked')).not.toBeInTheDocument();
    expect(screen.queryByText('Asked')).not.toBeInTheDocument();
  });

  it('counts what is still owed an answer, and is silent at zero', () => {
    const { rerender } = render(
      <QuestionPanel
        active={null}
        history={[nudge('a', { disposition: 'taken' })]}
        transcript={[]}
        onSelect={() => {}}
      />,
    );
    expect(screen.queryByText(/still waiting/i)).not.toBeInTheDocument();

    rerender(
      <QuestionPanel active={null} history={[nudge('a')]} transcript={[]} onSelect={() => {}} />,
    );
    expect(screen.getByText(/still waiting/i)).toBeInTheDocument();
  });
});
