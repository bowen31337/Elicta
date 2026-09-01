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

describe('the meter on the route the button actually takes', () => {
  it('fills completely when a direct compile is done', () => {
    // The direct route never sends a batch, so `batch-submission` never
    // completes — and a meter with a fixed four steps sat at three of four
    // for ever on a compile that had finished.
    render(
      <CompileProgress
        state="complete"
        stagesCompleted={['extraction', 'structuring', 'analyst-pass-direct']}
      />,
    );

    const meter = screen.getByRole('progressbar');
    expect(meter).toHaveAttribute('aria-valuenow', '3');
    expect(meter).toHaveAttribute('aria-valuemax', '3');
  });

  it('still counts four when a batch was sent', () => {
    render(
      <CompileProgress
        state="awaiting"
        stagesCompleted={['extraction', 'structuring', 'batch-submission']}
      />,
    );

    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuemax', '4');
  });

  it('names the drafting stage while a direct compile is running', () => {
    render(
      <CompileProgress state="running" stagesCompleted={['extraction', 'structuring']} />,
    );

    // Two of three done on the direct route, so the stage under way is the
    // drafting itself rather than sending anything off.
    expect(screen.getByText(/sending off/i)).toBeInTheDocument();
  });
});

describe('the percentage on the meter', () => {
  it('shows how far through the stages a compile is', () => {
    render(<CompileProgress state="running" stagesCompleted={['extraction']} />);

    // Weighted by how long the stages take rather than by counting them: the
    // drafting pass is ten times either of the two before it, so finishing
    // the first is nowhere near a quarter of the work. The bar carries the
    // shape and the number carries the amount, and both read the one value.
    expect(screen.getByText('14%')).toBeInTheDocument();
  });

  it('reads 100% only when the compile is done', () => {
    render(
      <CompileProgress
        state="complete"
        stagesCompleted={['extraction', 'structuring', 'analyst-pass-direct']}
      />,
    );

    expect(screen.getByText('100%')).toBeInTheDocument();
  });

  it('counts the stages of the route actually taken', () => {
    // Two of the direct route's three, not two of a batch route's four.
    render(
      <CompileProgress
        state="running"
        stagesCompleted={['extraction', 'structuring', 'analyst-pass-direct']}
      />,
    );

    expect(screen.getByText('100%')).toBeInTheDocument();
  });

  it('says nothing about a percentage once a compile has stopped', () => {
    // A number frozen at 25% invites the reading that it is still climbing.
    // What matters then is the reason, which is directly underneath.
    render(
      <CompileProgress
        state="stopped"
        stagesCompleted={['extraction']}
        notice="The last compile stopped while sorting what it found in them."
      />,
    );

    expect(screen.queryByText(/%$/)).not.toBeInTheDocument();
  });
});

describe('the percentage and the bar agree', () => {
  it('never reads 0% while a stage is running', () => {
    // Reported from a screenshot: the first segment part-filled and moving,
    // the number saying 0%. This is the case with no start time to creep
    // from, so the stage under way still counts as half — it cannot move, but
    // it must not read as nothing while something is running.
    render(<CompileProgress state="running" stagesCompleted={[]} />);

    expect(screen.queryByText('0%')).not.toBeInTheDocument();
    expect(screen.getByText('5%')).toBeInTheDocument();
  });

  it('counts the stage under way as half, which is what the bar draws', () => {
    render(<CompileProgress state="running" stagesCompleted={['extraction']} />);

    // Twenty-five seconds done and ten of the next twenty, out of the two
    // hundred and fifty-seven a compile costs.
    expect(screen.getByText('14%')).toBeInTheDocument();
  });

  it('counts only finished stages while the provider has the job', () => {
    // Nothing is running here, so nothing is part done — and the drafting
    // pass, which is all that is left, is most of the work.
    render(
      <CompileProgress
        state="awaiting"
        stagesCompleted={['extraction', 'structuring', 'batch-submission']}
      />,
    );

    expect(screen.getByText('18%')).toBeInTheDocument();
  });

  it('still reaches exactly 100% when it is done', () => {
    render(
      <CompileProgress
        state="complete"
        stagesCompleted={['extraction', 'structuring', 'analyst-pass-direct']}
      />,
    );

    expect(screen.getByText('100%')).toBeInTheDocument();
  });
});

describe('the bar creeps, and colours toward done', () => {
  it('is nearly empty a second into a compile, not a stage-sized jump', () => {
    const started = Date.now() - 1_000;
    render(
      <CompileProgress state="running" stagesCompleted={[]} startedAt={started} />,
    );

    const shown = Number(screen.getByText(/%$/).textContent?.replace('%', ''));
    expect(shown).toBeLessThan(5);
  });

  it('carries how far along it is as a number the styling can read', () => {
    const started = Date.now() - 30_000;
    const { container } = render(
      <CompileProgress
        state="running"
        stagesCompleted={['extraction']}
        startedAt={started}
      />,
    );

    // The colour walks from the working blue to the finished green as this
    // climbs, so it has to reach the stylesheet as a value rather than as a
    // class per bucket — a handful of buckets is a bar that changes colour in
    // steps, which is the stepping this whole change is removing.
    const track = container.querySelector('.compile-progress') as HTMLElement;
    const along = Number(track.style.getPropertyValue('--compile-along'));
    expect(along).toBeGreaterThan(0);
    expect(along).toBeLessThan(1);
  });

  it('is fully along when the compile is done', () => {
    const { container } = render(
      <CompileProgress
        state="complete"
        stagesCompleted={['extraction', 'structuring', 'analyst-pass-direct']}
        startedAt={Date.now() - 300_000}
      />,
    );

    const track = container.querySelector('.compile-progress') as HTMLElement;
    expect(Number(track.style.getPropertyValue('--compile-along'))).toBe(1);
  });

  it('still works when the service did not say when it began', () => {
    // An older service, or a compile restored from storage. The bar steps at
    // the boundaries as it used to rather than showing nothing.
    render(<CompileProgress state="running" stagesCompleted={['extraction']} />);

    expect(screen.getByText(/%$/)).toBeInTheDocument();
  });
});
