import { describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';

import { TranscriptPanel, scriptState } from '../TranscriptPanel';

function said(seq: number, text: string, at: number | null, speaker: string | null = null) {
  return { seq, text, speaker, at, final: true };
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

  it('says nothing is being captured, and to start the recording', () => {
    // "Nothing heard yet" implies something is listening. Nothing is.
    //
    // It named the Capture screen for as long as this screen could not begin
    // a recording. The bar below it can now, so sending an operator away from
    // the client's face to press a button that is in front of them would be a
    // sentence that is simply wrong.
    render(<TranscriptPanel transcript={[]} transcribing receivingAudio={false} />);

    expect(screen.getByText('Not capturing')).toBeInTheDocument();
    expect(screen.getByText(/start the recording/i)).toBeInTheDocument();
    expect(screen.queryByText(/capture screen/i)).not.toBeInTheDocument();
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

  it('names every model the service can choose', () => {
    // The fallback prints the wire name, which is a reasonable last resort
    // and a poor label: `flux-general-en` shipped to a screen for two builds
    // because the models were added to the enum, the dropdown and the
    // service, and not to the one map that turns them into English.
    for (const [wire, shown] of [
      ['flux-general-en', 'Flux'],
      ['nova-3', 'Nova-3'],
      ['whisper-small', 'Whisper small · on this machine'],
      ['parakeet-tdt-0.6b-v2', 'Parakeet 0.6b · on this machine'],
    ] as const) {
      const { unmount } = render(<TranscriptPanel transcript={[]} model={wire} />);
      expect(screen.getByText(shown)).toBeInTheDocument();
      unmount();
    }
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

describe('why every line reads Unattributed', () => {
  /**
   * Verification is two-way — one window against one enrolled print,
   * answering the operator, not the operator, or cannot tell — and with
   * nothing enrolled every window is the third. That is the correct answer.
   * A column of rows all saying so with nothing to explain it is not a
   * correct screen: it reads as a transcript that is broken rather than one
   * being careful, and the remedy is something the operator can do.
   */
  const WITH_LINES = [said(0, 'So how are arrivals booked in today?', 0)];

  it('says once why, rather than leaving a column of Unattributed unexplained', () => {
    render(
      <TranscriptPanel
        transcript={WITH_LINES}
        transcribing
        receivingAudio
        unattributedBecause="no voiceprint is enrolled, so no line can be attributed to anyone"
      />,
    );

    expect(screen.getByText(/no voiceprint is enrolled/i)).toBeInTheDocument();
    // Once, under the header — not repeated on every row.
    expect(screen.getAllByText(/no voiceprint is enrolled/i)).toHaveLength(1);
  });

  it('says nothing on a transcript with nothing in it', () => {
    // A warning about nothing, and it would be the first thing on a screen
    // whose meeting has not started.
    const { container } = render(
      <TranscriptPanel
        transcript={[]}
        transcribing
        receivingAudio
        unattributedBecause="no voiceprint is enrolled, so no line can be attributed to anyone"
      />,
    );

    expect(container.querySelector('.script-note')).toBeNull();
  });

  it('says nothing once lines can be attributed', () => {
    const { container } = render(
      <TranscriptPanel transcript={WITH_LINES} transcribing receivingAudio />,
    );

    expect(container.querySelector('.script-note')).toBeNull();
  });
});

describe('an empty transcript that will stay empty', () => {
  /**
   * "Nothing heard yet." is a reassuring sentence. It asserts that listening
   * works and that nobody has spoken — and an operator reads it, believes the
   * room is simply quiet, and waits. When the capture store already knows the
   * audio is not reaching the service, that assertion is false on the one
   * region they are actually staring at.
   */
  it('gives the reason instead of saying nothing has been heard yet', () => {
    render(
      <TranscriptPanel
        transcript={[]}
        transcribing
        receivingAudio
        notHeardBecause="The microphone is open but no audio is being read from it, so nothing is being uploaded."
      />,
    );

    expect(screen.getByRole('alert')).toHaveTextContent(/no audio is being read/i);
    expect(screen.queryByText('Nothing heard yet.')).toBeNull();
  });

  it('still says nothing heard yet when the recording is fine', () => {
    // Most of a meeting is a quiet room, and a warning on every pause in the
    // conversation is a warning nobody reads.
    render(<TranscriptPanel transcript={[]} transcribing receivingAudio />);

    expect(screen.getByText('Nothing heard yet.')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('says nothing of the sort once there are lines to show', () => {
    // The empty state is gone; the recording bar carries the note from here,
    // which is what covers a recording that breaks mid-meeting.
    const { container } = render(
      <TranscriptPanel
        transcript={[said(0, 'Three fifty a day.', 0)]}
        transcribing
        receivingAudio
        notHeardBecause="The microphone is open but no audio is being read from it."
      />,
    );

    expect(container.querySelector('.script-idle--stuck')).toBeNull();
  });
});

describe('a line the speaker has not finished', () => {
  /**
   * A streaming recogniser sends the words so far while somebody is still
   * talking, and the same `seq` arrives again, longer, until they stop. That
   * is what lets the transcript keep up with the room instead of printing
   * each sentence whole a second after it ended.
   *
   * The distinction has to survive onto the screen. Shown as settled, an
   * interim line quotes somebody on words they have not said yet.
   */
  const saying = (seq: number, text: string, at: number) =>
    ({ seq, text, speaker: null, at, final: false }) as const;

  it('shows the words so far, marked as still being said', () => {
    const { container } = render(
      <TranscriptPanel transcript={[saying(0, 'So how are arrivals', 0)]} transcribing receivingAudio />,
    );

    expect(screen.getByText('So how are arrivals')).toBeInTheDocument();
    expect(container.querySelector('.script-line--saying')).not.toBeNull();
  });

  it('does not attribute it to anyone yet', () => {
    // Verification runs on the finished turn, against the audio the words
    // came from. Naming a speaker here and changing it a second later is
    // worse than waiting.
    render(
      <TranscriptPanel transcript={[saying(0, 'So how are arrivals', 0)]} transcribing receivingAudio />,
    );

    expect(screen.queryByText('Unattributed')).toBeNull();
  });

  it('settles into an ordinary line when the speaker stops', () => {
    const { container, rerender } = render(
      <TranscriptPanel transcript={[saying(0, 'So how are', 0)]} transcribing receivingAudio />,
    );
    expect(container.querySelector('.script-line--saying')).not.toBeNull();

    // The same `seq`, finished — one line settling, not a second line.
    rerender(
      <TranscriptPanel
        transcript={[said(0, 'So how are arrivals booked in today?', 0)]}
        transcribing
        receivingAudio
      />,
    );

    expect(container.querySelectorAll('.script-line')).toHaveLength(1);
    expect(container.querySelector('.script-line--saying')).toBeNull();
    expect(screen.getByText('So how are arrivals booked in today?')).toBeInTheDocument();
  });
});
