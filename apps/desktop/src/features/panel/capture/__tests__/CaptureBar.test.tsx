import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { CaptureBar } from '../CaptureBar';

const START = 1_700_000_000_000;

describe('what the bar says the microphone is doing', () => {
  it('says it is recording, and for how long', () => {
    render(<CaptureBar capturing since={START} now={() => START + 508_000} />);

    // "Listening", not "Recording": the microphone being open is what an
    // operator is checking for, and it is the claim this bar can stand behind
    // from where it sits.
    expect(screen.getByText('Listening…')).toBeInTheDocument();
    expect(screen.getByText('08:28')).toBeInTheDocument();
  });

  it('says it is not, and shows no clock at all', () => {
    // A clock with no start is not shown at zero: `00:00` on a meeting nobody
    // has begun reads as a recording that has just started.
    render(<CaptureBar capturing={false} since={null} />);

    expect(screen.getByText('Not recording')).toBeInTheDocument();
    expect(screen.queryByLabelText('Recording time')).not.toBeInTheDocument();
  });

  it('keeps counting past the hour rather than wrapping to zero', () => {
    // A requirements meeting runs over an hour often enough, and a clock
    // reading 00:01 after sixty-one minutes tells its worst lie at the moment
    // the operator is most likely checking capture is alive.
    render(<CaptureBar capturing since={START} now={() => START + 3_661_000} />);
    expect(screen.getByText('1:01:01')).toBeInTheDocument();
  });
});

describe('recording without transcription', () => {
  it('says which of the two is missing', () => {
    // Audio is still captured with no speech credential — only the live
    // transcript and the questions that react to it are lost. Saying so keeps
    // an operator from stopping a recording that is working perfectly.
    render(<CaptureBar capturing since={START} transcribing={false} now={() => START} />);

    expect(screen.getByText('Listening…')).toBeInTheDocument();
    expect(screen.getByText(/not transcribing/i)).toBeInTheDocument();
  });

  it('says nothing of the sort when both are working', () => {
    render(<CaptureBar capturing since={START} transcribing now={() => START} />);
    expect(screen.queryByText(/not transcribing/i)).not.toBeInTheDocument();
  });
});

describe('ending the meeting', () => {
  it('offers Stop while something is running', async () => {
    const onStop = vi.fn();
    render(<CaptureBar capturing since={START} onStop={onStop} now={() => START} />);

    await userEvent.click(screen.getByRole('button', { name: 'Stop' }));
    expect(onStop).toHaveBeenCalledOnce();
  });

  it('offers no Stop for what is not running', () => {
    // Absent rather than disabled, now that Start takes its place: a greyed
    // Stop beside a Start is two controls saying the same thing, on a bar
    // read at a glance by somebody looking at a client.
    render(<CaptureBar capturing={false} since={null} onStop={() => {}} />);
    expect(screen.queryByRole('button', { name: 'Stop' })).toBeNull();
  });

  it('says the request is in flight, and cannot be sent twice', () => {
    // Stopping a meeting is not undoable, and a button that looks unpressed
    // while its request is in flight is a button that gets pressed again.
    render(<CaptureBar capturing since={START} onStop={() => {}} stopping now={() => START} />);
    expect(screen.getByRole('button', { name: /stopping/i })).toBeDisabled();
  });

  it('offers nothing to press where there is nothing to end', () => {
    // A fixed scene has no session. A dead Stop button is worse than none.
    render(<CaptureBar capturing since={START} now={() => START} />);
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });
});

describe('naming itself', () => {
  it('is a region a screen reader can find', () => {
    render(<CaptureBar capturing since={START} now={() => START} />);
    expect(screen.getByRole('region', { name: /recording/i })).toBeInTheDocument();
  });

  it('says so when the stop did not go through', () => {
    // The failure this bar could not report. Stopping 404'd on every press
    // for as long as the route was missing from the service, and the only
    // signal was the button reverting to enabled with the clock still
    // running — indistinguishable from a stop that worked and a meeting that
    // was still receiving audio.
    render(
      <CaptureBar capturing since={START} onStop={() => {}} stopFailed now={() => START + 12_000} />,
    );

    expect(screen.getByRole('alert')).toHaveTextContent(/stop failed/i);
  });

  it('says nothing about a stop that has not failed', () => {
    render(<CaptureBar capturing since={START} onStop={() => {}} now={() => START + 12_000} />);

    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('draws the wave it was given', () => {
    const { container } = render(
      <CaptureBar capturing since={START} waveform={[0.1, 0.9, 0.4]} now={() => START} />,
    );

    expect(container.querySelectorAll('.capture-bar__bar')).toHaveLength(3);
  });

  it('draws no wave at all rather than a flat one when there is nothing to draw', () => {
    // Absence is not silence. A row of flat bars is a claim that the room is
    // quiet; an empty array means this window is not the one holding the
    // device and has no reading to report.
    const { container } = render(
      <CaptureBar capturing since={START} waveform={[]} now={() => START} />,
    );

    expect(container.querySelector('.capture-bar__wave')).toBeNull();
  });
});

describe('holding the recording', () => {
  it('offers Pause while it is running and Resume once it is held', async () => {
    const pause = vi.fn();
    const resume = vi.fn();
    const { rerender } = render(
      <CaptureBar capturing since={START} onPause={pause} onResume={resume} now={() => START} />,
    );

    await userEvent.click(screen.getByRole('button', { name: /pause/i }));
    expect(pause).toHaveBeenCalledTimes(1);

    rerender(
      <CaptureBar
        capturing
        paused
        since={START}
        onPause={pause}
        onResume={resume}
        now={() => START}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: /resume/i }));
    expect(resume).toHaveBeenCalledTimes(1);
  });

  it('says Paused rather than Listening while it is held', () => {
    render(<CaptureBar capturing paused since={START} onPause={() => {}} now={() => START} />);

    expect(screen.getByText('Paused')).toBeInTheDocument();
    expect(screen.queryByText('Listening…')).not.toBeInTheDocument();
  });

  it('shows no hold control where nothing local can be held', () => {
    // A second screen watching somebody else's recording. A Pause button that
    // cannot reach the microphone is the Stop button's bug written again.
    render(<CaptureBar capturing since={START} now={() => START} />);

    expect(screen.queryByRole('button', { name: /pause/i })).toBeNull();
  });

  it('prefers the local clock, which does not count paused time', () => {
    // Wall clock says ten minutes; the session was held for nine of them.
    // Reporting ten would tell the operator they have a ten-minute recording.
    render(
      <CaptureBar
        capturing
        since={START}
        elapsedSeconds={61}
        now={() => START + 600_000}
      />,
    );

    expect(screen.getByText('01:01')).toBeInTheDocument();
    expect(screen.queryByText('10:00')).toBeNull();
  });
});

describe('beginning the meeting from the panel', () => {
  /**
   * The bar could report a recording and end one, and not begin one — the
   * panel's own empty state sent the operator to the Capture screen, which is
   * a navigation away from a client's face to press a button that could be
   * here. It is the same journey Stop already makes in the other direction.
   */
  it('offers Start where nothing is running', async () => {
    const start = vi.fn();
    render(<CaptureBar capturing={false} since={null} onStart={start} />);

    await userEvent.click(screen.getByRole('button', { name: /start recording/i }));

    expect(start).toHaveBeenCalledTimes(1);
  });

  it('offers Pause and Stop instead once something is', () => {
    render(
      <CaptureBar
        capturing
        since={START}
        onStart={() => {}}
        onPause={() => {}}
        onStop={() => {}}
        now={() => START}
      />,
    );

    expect(screen.queryByRole('button', { name: /start recording/i })).toBeNull();
    expect(screen.getByRole('button', { name: /pause/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Stop' })).toBeInTheDocument();
  });

  it('says the request is in flight, and cannot be sent twice', () => {
    // Opening a microphone and booking a meeting is not instant, and a button
    // that looks unpressed while its request is in flight gets pressed again
    // — which on this path books a second session.
    render(<CaptureBar capturing={false} since={null} onStart={() => {}} starting />);

    expect(screen.getByRole('button', { name: /starting/i })).toBeDisabled();
  });

  it('replaces the button with the reason it cannot start', () => {
    // A control that takes the press and then explains is worse than one that
    // is not offered, and this is the press an operator makes while somebody
    // is waiting to start talking.
    render(
      <CaptureBar
        capturing={false}
        since={null}
        onStart={() => {}}
        startBlocked="Consent has not been confirmed for this meeting."
      />,
    );

    expect(screen.getByRole('alert')).toHaveTextContent(/consent has not been confirmed/i);
  });

  it('offers nothing to press where there is no meeting to record', () => {
    render(<CaptureBar capturing={false} since={null} />);

    expect(screen.queryByRole('button', { name: /start recording/i })).toBeNull();
  });
});

describe('a recording that is uploading nothing', () => {
  /**
   * The store diagnoses three of these — the event channel refused, no way to
   * read the samples, and the device open but delivering silence — and says
   * each in a sentence with the remedy in it. The Capture screen has shown
   * them from the start; this bar showed none, which was survivable while the
   * panel could only report somebody else's recording and is not now that it
   * starts them. A meeting can otherwise run its full hour here uploading
   * nothing, with "Listening…" above a moving clock and no other sign — and
   * the transcript's emptiness is not a sign, because a quiet room looks
   * exactly the same.
   */
  it('shows the store note, and announces it', () => {
    render(
      <CaptureBar
        capturing
        since={START}
        now={() => START}
        note="The microphone is open but no audio is being read from it, so nothing is being uploaded and this meeting will not be transcribed."
      />,
    );

    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent(/no audio is being read/i);
    // The remedy travels with it, or the operator is told only that they have
    // a problem.
    expect(alert).toHaveTextContent(/will not be transcribed/i);
  });

  it('says nothing when the recording is going where it should', () => {
    const { container } = render(
      <CaptureBar capturing since={START} now={() => START} note={null} />,
    );

    expect(container.querySelector('.capture-bar-note')).toBeNull();
  });
});
