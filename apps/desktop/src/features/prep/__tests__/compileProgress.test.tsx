import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { CompileProgress } from '../CompileProgress';

/**
 * What a compile is doing, while it does it.
 *
 * A compile takes minutes: it reads the documents, sorts what it found, sends
 * the drafting job to the provider and waits for a bank. All of that used to
 * be one word — "Compiling" — and then, minutes later, either a bank or a
 * sentence. An operator watching a screen that says the same thing at ten
 * seconds and at six minutes cannot tell working from stuck, and the reports
 * that came back said exactly that: "it takes for ever".
 *
 * The stages are already known — the service reports each one as it finishes.
 * Nothing here is invented; it is the run's own account, drawn.
 */
const STAGES = ['extraction', 'structuring', 'batch-submission'] as const;

describe('the compile meter', () => {
  it('says which stage is running, in words the operator uses', () => {
    render(<CompileProgress state="running" stagesCompleted={['extraction']} />);

    expect(screen.getByText(/sorting what it found/i)).toBeInTheDocument();
  });

  it('reports its progress to assistive technology as a real meter', () => {
    render(<CompileProgress state="running" stagesCompleted={[...STAGES]} />);

    const meter = screen.getByRole('progressbar');
    expect(meter).toHaveAttribute('aria-valuenow', '3');
    expect(meter).toHaveAttribute('aria-valuemax', '4');
  });

  it('fills one segment per finished stage and no more', () => {
    const { container } = render(
      <CompileProgress state="running" stagesCompleted={['extraction', 'structuring']} />,
    );

    expect(container.querySelectorAll('.compile-progress__step--done')).toHaveLength(2);
    expect(container.querySelectorAll('.compile-progress__step')).toHaveLength(4);
  });

  it('says the job is with the provider while it waits', () => {
    // Not a stage the service is working through: the drafting job is away and
    // nothing here is running. Saying "drafting the questions" would claim work
    // this machine is not doing.
    render(<CompileProgress state="awaiting" stagesCompleted={[...STAGES]} />);

    expect(screen.getByText(/with the provider/i)).toBeInTheDocument();
  });

  it('shows a full meter when the bank is drafted', () => {
    render(
      <CompileProgress
        state="complete"
        stagesCompleted={[...STAGES, 'analyst-pass-direct']}
      />,
    );

    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '4');
  });
});

describe('what the meter says when something is wrong', () => {
  it('raises a stopped compile as an alert, not a polite status', () => {
    render(
      <CompileProgress
        state="stopped"
        stagesCompleted={['extraction']}
        notice="The last compile stopped while sorting what it found in them."
      />,
    );

    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent(/stopped while sorting/i);
    expect(alert).toHaveClass('notice--error');
  });

  it('keeps progress a status, because nothing is wrong', () => {
    render(
      <CompileProgress
        state="awaiting"
        stagesCompleted={[...STAGES]}
        notice="The drafting job is with the provider."
      />,
    );

    expect(screen.getByRole('status')).toHaveClass('notice--working');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('marks a compile that finished with nothing as a warning, not a failure', () => {
    // Nothing broke. The pass ran and the bank it produced was not usable,
    // which is a different thing to act on from a stage that could not run.
    render(
      <CompileProgress
        state="complete"
        stagesCompleted={[...STAGES, 'analyst-pass-direct']}
        notice="The compile finished and drafted no candidates."
        tone="warning"
      />,
    );

    expect(screen.getByRole('status')).toHaveClass('notice--warning');
  });

  it('says nothing at all when there is nothing to say', () => {
    const { container } = render(<CompileProgress state="idle" stagesCompleted={[]} />);

    expect(container).toBeEmptyDOMElement();
  });
});
