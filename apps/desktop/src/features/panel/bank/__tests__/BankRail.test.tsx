import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { BankRail, upcoming } from '../BankRail';
import type { BankQuestion } from '../types';

function question(
  id: string,
  phrasing: string,
  priority: number,
  stub = '',
  section = 'Volumes',
): BankQuestion {
  return { id, phrasing, priority, stub, templateSection: section, inherited: false };
}

describe('which questions the rail offers', () => {
  it('puts the highest priority first, because that is the bank\'s own ranking', () => {
    const bank = [question('c-2', 'Second.', 2), question('c-1', 'First.', 1)];
    expect(upcoming(bank, { asked: new Set() }).map((q) => q.id)).toEqual(['c-1', 'c-2']);
  });

  it('drops a question the operator has already asked', () => {
    // The rail is what to ask *next*. A question still sitting there after it
    // was asked is one the operator has to remember not to repeat, which is
    // the job the panel is supposed to be doing for them.
    const bank = [question('c-1', 'First.', 1), question('c-2', 'Second.', 2)];
    expect(upcoming(bank, { asked: new Set(['c-1']) }).map((q) => q.id)).toEqual(['c-2']);
  });

  it('shows only as many as can be glanced at', () => {
    // A compiled bank runs to 300 questions. All of them is a document, and
    // reading a document is the thing this panel exists to avoid.
    const bank = Array.from({ length: 300 }, (_, index) =>
      question(`c-${index}`, `Question ${index}.`, index + 1),
    );
    expect(upcoming(bank, { asked: new Set() }).length).toBeLessThanOrEqual(12);
  });
});

describe('the bank rail', () => {
  it('labels each question with its keywords, not its full wording', () => {
    // The whole point. A 112-character phrasing cannot be read without
    // breaking eye contact; three keywords can be taken in at a glance.
    render(
      <BankRail
        questions={[
          question(
            'c-1',
            'How many arrivals do you handle in a month, across all three sites?',
            1,
            'Monthly arrivals',
          ),
        ]}
        onAsk={() => {}}
      />,
    );

    expect(screen.getByRole('button', { name: /monthly arrivals/i })).toBeInTheDocument();
    expect(screen.queryByText(/across all three sites/)).not.toBeInTheDocument();
  });

  it('derives keywords for a bank compiled before stubs reached it', () => {
    // 554 candidates on a real state file carry no stub at all. They are the
    // banks operators have today and none of them are worth a recompile.
    render(
      <BankRail
        questions={[question('c-1', 'What is the current process for booking a slot?', 1)]}
        onAsk={() => {}}
      />,
    );

    const button = screen.getByRole('button', { name: /booking/i });
    expect(button.textContent?.split(/\s+/).length).toBeLessThanOrEqual(5);
  });

  it('carries the full wording for a screen reader, which is what gets read aloud', () => {
    // The stub is the glance; the phrasing is the question. Someone using the
    // rail without seeing it needs the half that is actually asked.
    render(
      <BankRail
        questions={[question('c-1', 'How many arrivals a month?', 1, 'Monthly arrivals')]}
        onAsk={() => {}}
      />,
    );

    expect(screen.getByRole('button', { name: /monthly arrivals/i })).toHaveAttribute(
      'title',
      'How many arrivals a month?',
    );
  });

  it('hands the whole question back when one is tapped', () => {
    const onAsk = vi.fn();
    const asked = question('c-1', 'How many arrivals a month?', 1, 'Monthly arrivals');
    render(<BankRail questions={[asked]} onAsk={onAsk} />);

    return userEvent.click(screen.getByRole('button', { name: /monthly arrivals/i })).then(() => {
      expect(onAsk).toHaveBeenCalledWith(asked);
    });
  });

  it('says the bank is empty rather than rendering an empty rail', () => {
    // An empty rail and a bank that never compiled look identical, and one of
    // those is something the operator can fix before the meeting.
    render(<BankRail questions={[]} onAsk={() => {}} />);
    expect(screen.getByText(/no questions/i)).toBeInTheDocument();
  });

  it('names itself, so it is not read as more chips', () => {
    render(<BankRail questions={[question('c-1', 'Anything?', 1)]} onAsk={() => {}} />);
    expect(screen.getByRole('group', { name: /bank/i })).toBeInTheDocument();
  });
});

describe('a question carried forward from the last meeting', () => {
  function inherited(): BankQuestion {
    return {
      id: 'c-2',
      phrasing: 'What happens to a booking when a vessel is late?',
      stub: 'Late vessel, booking',
      priority: 1,
      templateSection: 'Exceptions',
      inherited: true,
    };
  }

  it('says so in words, not only in a colour beside it', () => {
    // Its standing is different — the client already left this unanswered
    // once — and that is worth a sentence to anyone who stops to read.
    render(<BankRail questions={[inherited()]} onAsk={() => {}} />);

    expect(screen.getByRole('button', { name: /late vessel/i })).toHaveAttribute(
      'title',
      'Carried forward from your last meeting — What happens to a booking when a vessel is late?',
    );
  });

  it('is still just a question to tap', () => {
    const onAsk = vi.fn();
    render(<BankRail questions={[inherited()]} onAsk={onAsk} />);

    return userEvent.click(screen.getByRole('button', { name: /late vessel/i })).then(() => {
      expect(onAsk).toHaveBeenCalledWith(inherited());
    });
  });
});
