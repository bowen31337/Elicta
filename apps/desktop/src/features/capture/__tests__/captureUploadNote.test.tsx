import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { CaptureScreen } from '../route';

/**
 * Telling the operator where this recording is going.
 *
 * A recording that is being uploaded and one that is not look identical on
 * this screen: the same word, the same clock, the same meter moving. The
 * difference only shows up afterwards, as a meeting with no transcript, which
 * reads as a broken product rather than as consent doing its job. So the
 * reason is carried onto the screen while the recording is still running and
 * something can still be done about it.
 */

const base = {
  state: 'capturing' as const,
  elapsed: '00:04:12',
  sources: [{ id: 'mic-1', label: 'Desk microphone', kind: 'acoustic' as const, active: true }],
  operatorEnrolled: false,
  enrolmentSeconds: 0,
};

describe('the capture screen', () => {
  it('shows what the recording is doing about the transcript', () => {
    render(
      <CaptureScreen
        {...base}
        uploadNote="Nobody has confirmed consent for this meeting, so the audio stays on this machine."
      />,
    );

    expect(screen.getByText(/stays on this machine/)).toBeInTheDocument();
  });

  it('says nothing when the recording is being uploaded as expected', () => {
    render(<CaptureScreen {...base} />);

    // No reassurance, deliberately: a line saying "this is being uploaded" on
    // every ordinary recording is one more thing to read past, and the state
    // it describes is the one an operator already assumes.
    expect(screen.queryByText(/will not be transcribed/i)).not.toBeInTheDocument();
  });
});
