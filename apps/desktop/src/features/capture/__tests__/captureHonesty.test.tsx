import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { CaptureScreen } from '../route';

/**
 * What the recording screen may claim is happening.
 *
 * The status line said "Audio is being captured and transcribed" for the
 * length of every meeting, and half of that was not true: nothing transcribes
 * during a meeting here. Speech becomes text on the record path afterwards,
 * from the audio this screen uploads — so an operator watching the words go by
 * was being told a live transcript existed, and would find out otherwise only
 * when they went looking for one.
 *
 * The screen is the only place an operator learns what the product is doing
 * with their meeting. A claim it cannot keep costs more than a quiet screen.
 */
describe('what the capture screen says is happening', () => {
  it('does not claim speech is being transcribed while the meeting runs', () => {
    render(<CaptureScreen state="capturing" sources={[]} elapsed="00:05" operatorEnrolled enrolmentSeconds={60} />);

    const status = screen.getByText(/audio is being/i);

    expect(status.textContent).not.toMatch(/transcrib/i);
  });

  it('says where the audio is going instead', () => {
    render(<CaptureScreen state="capturing" sources={[]} elapsed="00:05" operatorEnrolled enrolmentSeconds={60} />);

    expect(screen.getByText(/after the meeting/i)).toBeInTheDocument();
  });

  it('does not tell a paused operator that a transcriber exists to stop reaching', () => {
    render(<CaptureScreen state="paused" sources={[]} elapsed="00:05" operatorEnrolled enrolmentSeconds={60} />);

    expect(screen.queryByText(/transcriber/i)).not.toBeInTheDocument();
    // The half that was true has to survive: pausing is only worth doing if
    // what is said now is genuinely not kept.
    expect(screen.getByText(/nothing said now/i)).toBeInTheDocument();
  });
});
