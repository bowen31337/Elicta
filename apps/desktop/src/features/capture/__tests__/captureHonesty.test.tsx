import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { CaptureScreen } from '../route';

/**
 * What the recording screen may claim is happening.
 *
 * This line has now been wrong in both directions, which is the argument for
 * it making no claim about transcription at all.
 *
 * It said "Audio is being captured and transcribed" when nothing transcribed
 * during a meeting, so an operator was told a live transcript existed. That
 * was corrected to "it becomes a transcript after the meeting, not during
 * it" — and then the live path was built, which made the correction false in
 * the other direction. Whether speech becomes words during the meeting now
 * depends on a provider configured in Settings, which this screen does not
 * know about.
 *
 * So it says where the audio goes, which is true in every configuration, and
 * leaves what happens next to the screens that actually know. The screen is
 * the only place an operator learns what is being done with their meeting,
 * and a claim it cannot keep costs more than a quiet one.
 */
describe('what the capture screen says is happening', () => {
  it('makes no claim about when a transcript appears', () => {
    // Neither "and transcribed" nor "not during it": both were true once and
    // false later, and the screen cannot know which applies — live
    // transcription depends on a provider configured elsewhere.
    render(<CaptureScreen state="capturing" sources={[]} elapsed="00:05" operatorEnrolled enrolmentSeconds={60} />);

    const status = screen.getByText(/audio is being/i);

    expect(status.textContent).not.toMatch(/transcrib/i);
    expect(status.textContent).not.toMatch(/after the meeting/i);
  });

  it('says where the audio is going, which does not change', () => {
    render(<CaptureScreen state="capturing" sources={[]} elapsed="00:05" operatorEnrolled enrolmentSeconds={60} />);

    expect(screen.getByText(/sent to the service/i)).toBeInTheDocument();
  });

  it('does not tell a paused operator that a transcriber exists to stop reaching', () => {
    render(<CaptureScreen state="paused" sources={[]} elapsed="00:05" operatorEnrolled enrolmentSeconds={60} />);

    expect(screen.queryByText(/transcriber/i)).not.toBeInTheDocument();
    // The half that was true has to survive: pausing is only worth doing if
    // what is said now is genuinely not kept.
    expect(screen.getByText(/nothing said now/i)).toBeInTheDocument();
  });
});
