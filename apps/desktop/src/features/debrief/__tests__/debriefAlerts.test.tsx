import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { DebriefScreen } from '../route';

/**
 * When the write-up does not happen, the screen has to say so like it means it.
 *
 * A stopped run rendered as an unstyled footnote with `role="status"` — the
 * polite live region, which announces at the next convenient moment and looks
 * like body text. `.degraded-note` gives it its background, and it is defined
 * in the panel's stylesheet, which this screen does not import. So the one
 * sentence explaining why a meeting has no documents was a grey line above two
 * empty headings.
 *
 * A failure is not a status. It is an alert, and it should read as one.
 */
const NOTHING = { openQuestions: [], decisions: [], brief: null, meetingTitle: 'Day 2' };

describe('the debrief screen when something went wrong', () => {
  it('raises a stopped run as an alert, not a polite status', () => {
    render(
      <DebriefScreen
        {...NOTHING}
        incomplete="The write-up stopped while telling the voices apart."
      />,
    );

    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent(/stopped while telling the voices apart/i);
    expect(alert).toHaveClass('notice--error');
  });

  it('says a write-up is under way while it is', () => {
    // Pressing the button used to change nothing an operator could see: the
    // request hung for the length of the pipeline and the screen kept saying
    // no write-up had been produced.
    render(<DebriefScreen {...NOTHING} running />);

    expect(screen.getByRole('status')).toHaveTextContent(/being written up now/i);
    expect(screen.queryByRole('button', { name: /write it up now/i })).not.toBeInTheDocument();
  });

  it('does not offer the button while a run is under way', () => {
    // Pressing it again is what an operator does when nothing appears to
    // happen, and it should not be the only way to find out that it is.
    render(<DebriefScreen {...NOTHING} running empty="Nothing yet." onProduce={async () => {}} />);

    expect(screen.queryByRole('button', { name: /write it up now/i })).not.toBeInTheDocument();
  });

  it('keeps the ordinary "not yet" case quiet', () => {
    // Nothing has gone wrong on a meeting whose write-up is simply still to
    // come, and an alert on every visit is how a warning becomes wallpaper.
    render(<DebriefScreen {...NOTHING} empty="No write-up has been produced yet." />);

    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByText(/No write-up has been produced yet/)).toBeInTheDocument();
  });
});
