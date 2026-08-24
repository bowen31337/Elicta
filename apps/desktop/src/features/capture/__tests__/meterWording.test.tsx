import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { CaptureScreen } from '../route';

/**
 * What the screen may say when the meter has no reading.
 *
 * It said "This browser cannot measure the input level" — in a desktop app,
 * to an operator who never opened a browser. The word is not quite wrong,
 * since the shell draws its screens in a webview, and it is entirely useless:
 * it names an implementation detail as the cause of something the reader can
 * see for themselves.
 *
 * Worse, it was a guess. The screen was told only that there was no reading,
 * and no reading has two very different causes. Nothing here can measure the
 * level — a webview without Web Audio, and the meter is gone for the session.
 * Or nothing has arrived yet — the device is opening, or the backend is
 * producing nothing, and it may appear a moment later or never.
 *
 * An operator acts differently on those. One is "carry on, you have no
 * meter"; the other is "your microphone may not be working", which during a
 * client meeting is the more expensive to get wrong.
 */
const BASE = {
  state: 'checking' as const,
  elapsed: '00:03',
  sources: [],
  operatorEnrolled: true,
  enrolmentSeconds: 60,
  device: 'Desk microphone',
};

describe('the meter with no reading', () => {
  it('does not blame a browser, in an application that is not one', () => {
    render(<CaptureScreen {...BASE} metering={{ level: null, waveform: [] }} />);

    expect(screen.queryByText(/browser/i)).not.toBeInTheDocument();
  });

  it('says a reading has not arrived, rather than that none can', () => {
    render(<CaptureScreen {...BASE} metering={{ level: null, waveform: [] }} />);

    expect(screen.getByText(/no input level/i)).toBeInTheDocument();
    expect(screen.getByText(/recording is unaffected/i)).toBeInTheDocument();
  });

  it('says the level cannot be measured when that is actually known', () => {
    render(
      <CaptureScreen
        {...BASE}
        metering={{ level: null, waveform: [], unmeasurable: true }}
      />,
    );

    expect(screen.getByText(/cannot measure the input level/i)).toBeInTheDocument();
    expect(screen.queryByText(/browser/i)).not.toBeInTheDocument();
  });
});
