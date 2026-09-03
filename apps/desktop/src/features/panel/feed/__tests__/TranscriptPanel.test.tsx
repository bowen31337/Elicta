import { describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';

import { TranscriptPanel, scriptState } from '../TranscriptPanel';

function said(seq: number, text: string, at: number | null, speaker: string | null = null) {
  return { seq, text, speaker, at };
}

/**
 * Three states, because they have three remedies.
 *
 * The panel had two and the label claimed the strongest of them: with a speech
 * credential configured and no meeting started it showed a pulsing green
 * "Transcribing", asserting the room was being written down before Capture had
 * been pressed. A credential is not a microphone.
 */
describe('what the panel can honestly say it is doing', () => {
  it('is off when nothing could transcribe', () => {
    expect(scriptState({ transcribing: false, receivingAudio: false })).toBe('off');
  });

  it('is idle when it could but no audio is arriving', () => {
    // The state that was being mislabelled.
    expect(scriptState({ transcribing: true, receivingAudio: false })).toBe('idle');
  });

  it('is live only when audio is actually arriving', () => {
    expect(scriptState({ transcribing: true, receivingAudio: true })).toBe('live');
  });

  it('stays off even if audio somehow arrives with no recogniser', () => {
    // Belt and braces: the stronger claim must never win over the weaker one.
    expect(scriptState({ transcribing: false, receivingAudio: true })).toBe('off');
  });
});

describe('what it says before Capture is pressed', () => {
  it('does not claim to be transcribing', () => {
    render(<TranscriptPanel transcript={[]} transcribing receivingAudio={false} />);
    expect(screen.queryByText('Transcribing')).not.toBeInTheDocument();
  });

  it('says nothing is being captured, and where to start it', () => {
    // "Nothing heard yet" implies something is listening. Nothing is.
    render(<TranscriptPanel transcript={[]} transcribing receivingAudio={false} />);

    expect(screen.getByText('Not capturing')).toBeInTheDocument();
    expect(screen.getByText(/capture screen/i)).toBeInTheDocument();
  });

  it('says it is transcribing once audio arrives', () => {
    render(
      <TranscriptPanel transcript={[said(0, 'Yes.', 100)]} transcribing receivingAudio />,
    );
    expect(screen.getByText('Transcribing')).toBeInTheDocument();
  });

  it('still names the missing credential ahead of the missing microphone', () => {
    // They have different remedies and only one is reachable from Settings.
    render(<TranscriptPanel transcript={[]} transcribing={false} receivingAudio={false} />);

    expect(screen.getByText('Not transcribing')).toBeInTheDocument();
    expect(screen.getByText(/speech credential/i)).toBeInTheDocument();
  });
});

describe('the transcript itself', () => {
  it('shows every line with who said it', () => {
    render(
      <TranscriptPanel
        transcript={[said(0, 'How many a day?', 100, 'operator'), said(1, 'Three fifty.', 200, 'other')]}
        transcribing
        receivingAudio
      />,
    );

    expect(within(screen.getByText('How many a day?').closest('li')!).getByText('You')).toBeInTheDocument();
    expect(
      within(screen.getByText('Three fifty.').closest('li')!).getByText(/someone else/i),
    ).toBeInTheDocument();
  });

  it('says a line is unattributed rather than guessing', () => {
    render(<TranscriptPanel transcript={[said(0, 'It depends.', 100)]} transcribing receivingAudio />);
    const row = screen.getByText('It depends.').closest('li')!;
    expect(within(row).getByText(/unattributed/i)).toBeInTheDocument();
    expect(row.textContent).not.toMatch(/client/i);
  });

  it('stamps how far into the meeting each line was said', () => {
    render(
      <TranscriptPanel
        transcript={[said(0, 'First.', 1_700_000_000_000), said(1, 'Later.', 1_700_000_095_000)]}
        transcribing
        receivingAudio
      />,
    );

    expect(screen.getByText('0:00')).toBeInTheDocument();
    expect(screen.getByText('1:35')).toBeInTheDocument();
  });

  it('stamps nothing when the service did not say when', () => {
    render(<TranscriptPanel transcript={[said(0, 'Whenever.', null)]} transcribing receivingAudio />);
    expect(screen.queryByText('0:00')).not.toBeInTheDocument();
    expect(screen.getByText('Whenever.')).toBeInTheDocument();
  });

  it('is a log, so a line arriving is announced without stealing focus', () => {
    render(<TranscriptPanel transcript={[said(0, 'Yes.', 100)]} transcribing receivingAudio />);
    expect(screen.getByRole('log')).toHaveAttribute('aria-live', 'polite');
  });
});

describe('reaching the transcript without a mouse', () => {
  it('is focusable, because it scrolls and holds nothing that can take focus', () => {
    // A keyboard user could otherwise reach every control on the panel and
    // not the one region that runs to hundreds of lines. Caught by the
    // accessibility audit as `scrollable-region-focusable`.
    render(<TranscriptPanel transcript={[said(0, 'Yes.', 100)]} transcribing receivingAudio />);
    expect(screen.getByRole('log')).toHaveAttribute('tabindex', '0');
  });
});

describe('which recogniser is listening', () => {
  /**
   * On screen because the model is read per window and changes take effect
   * mid-meeting. An operator changes it *because* the transcript is poor,
   * and without this there is no evidence anywhere that the change took.
   */
  it('names the model in the header', () => {
    render(<TranscriptPanel transcript={[]} model="nova-3" />);

    expect(screen.getByText('Nova-3')).toBeInTheDocument();
  });

  it('says when the model is running on this machine', () => {
    // The difference between a meeting whose audio left the building and one
    // whose did not, and it should not require knowing which product names
    // are which.
    render(<TranscriptPanel transcript={[]} model="whisper-small" />);

    expect(screen.getByText(/whisper small · on this machine/i)).toBeInTheDocument();
  });

  it('prints a model it has never heard of rather than nothing', () => {
    // A build that predates a model is still transcribing with it, and the
    // name is more use than a blank.
    render(<TranscriptPanel transcript={[]} model="canary-1" />);

    expect(screen.getByText('canary-1')).toBeInTheDocument();
  });

  it('says nothing where the service does not know', () => {
    const { container } = render(<TranscriptPanel transcript={[]} model={null} />);

    expect(container.querySelector('.script-model')).toBeNull();
  });
});

describe('why nothing is being written down', () => {
  /**
   * The panel had one hardcoded sentence for a state with two opposite
   * remedies, and it named the wrong one for every deployment running a local
   * model: an operator transcribing on their own machine was told no speech
   * credential was configured. True, irrelevant, and pointing at the single
   * action that would cost them money and change nothing.
   */
  it('gives the service reason for a local model with nowhere to send audio', () => {
    render(
      <TranscriptPanel
        transcript={[]}
        transcribing={false}
        model="parakeet-tdt-0.6b-v2"
        blockedBecause="no local transcription server address is configured, and this model runs on your machine rather than at a vendor"
      />,
    );

    expect(screen.getByText(/no local transcription server address/i)).toBeInTheDocument();
    expect(screen.queryByText(/no speech credential/i)).not.toBeInTheDocument();
  });

  it('still says credential where a credential is what is missing', () => {
    render(
      <TranscriptPanel
        transcript={[]}
        transcribing={false}
        model="nova-3"
        blockedBecause="no speech credential is configured"
      />,
    );

    expect(screen.getByText(/no speech credential is configured/i)).toBeInTheDocument();
  });

  it('falls back to the old sentence against a service that predates the field', () => {
    // Something is better than nothing, and the old sentence was right for
    // the only case that existed when it was written.
    render(<TranscriptPanel transcript={[]} transcribing={false} />);

    expect(screen.getByText(/no speech credential is configured/i)).toBeInTheDocument();
  });

  it('says nothing at all once the lane is ready', () => {
    const { container } = render(
      <TranscriptPanel transcript={[]} transcribing model="nova-3" blockedBecause={null} />,
    );

    expect(container.querySelector('.script-notice')).toBeNull();
  });
});
