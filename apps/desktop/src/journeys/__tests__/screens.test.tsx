import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { AboutScreen } from '../../features/about/route';
import { ArcScreen } from '../../features/arc/route';
import { CaptureScreen } from '../../features/capture/route';
import { ConsentScreen } from '../../features/consent/route';
import { DebriefScreen } from '../../features/debrief/route';
import { OperatorPanel } from '../../features/panel/route';
import { PrepScreen } from '../../features/prep/route';
import { RecordingScreen } from '../../features/recording/route';
import { ReplayScreen } from '../../features/replay/route';
import { DEGRADED } from '../scenes';
import {
  ABOUT_MANAGED,
  ABOUT_UNMANAGED,
  ARC,
  CAPTURING,
  CAPTURING_ACOUSTIC,
  PAUSED,
  CONSENT_CONFIRMED,
  CONSENT_PENDING,
  DEBRIEF,
  PREP,
  RECORDING,
  REPLAY,
  REPLAY_FAILING,
} from '../synthetic';

/**
 * The journey screens, asserted on what each one exists to make obvious.
 *
 * These are not render smoke tests. Each asserts the single thing the screen
 * would be useless without — a consent gate that can be bypassed, a debrief
 * that blurs stated and inferred, or a replay screen that treats an
 * embarrassing suggestion as merely unhelpful would all still render fine.
 */

describe('prep', () => {
  it('shows the question tree grouped by template section', () => {
    render(<PrepScreen {...PREP} />);

    expect(screen.getByText('Performance')).toBeInTheDocument();
    expect(screen.getByText('Integrations')).toBeInTheDocument();
    expect(
      screen.getByText(/what does that mean in seconds/),
    ).toBeInTheDocument();
  });

  it('distinguishes ground truth from hypothesis', () => {
    // The tag decides whether a contradiction can fire against a document, so
    // a reviewer has to be able to see it without opening anything.
    const { container } = render(<PrepScreen {...PREP} />);

    // Scoped to the tags themselves: the explanatory text below the list also
    // contains the words "ground truth". The tag is a select rather than a
    // pill now — journey 1 says the operator chooses it — and its value is
    // still the tag, visible without opening anything.
    const tags = [...container.querySelectorAll<HTMLSelectElement>('[id^="tag-"]')].map(
      (select) => select.value,
    );
    expect(tags.filter((tag) => tag === 'ground truth')).toHaveLength(2);
    expect(tags).toContain('hypothesis');
    expect(tags).toContain('superseded');
  });

  it('offers to compile when no bank exists yet', () => {
    render(<PrepScreen {...PREP} bank={null} />);

    expect(screen.getByRole('button', { name: 'Compile' })).toBeInTheDocument();
  });
});

describe('consent', () => {
  it('will not let capture start before consent is on record', () => {
    render(<ConsentScreen {...CONSENT_PENDING} />);

    expect(screen.getByRole('button', { name: 'Start' })).toBeDisabled();
    expect(screen.getByText('Required')).toBeInTheDocument();
  });

  it('enables capture once consent is confirmed, and says who confirmed it', () => {
    render(<ConsentScreen {...CONSENT_CONFIRMED} />);

    expect(screen.getByRole('button', { name: 'Start' })).toBeEnabled();
    expect(screen.getByText(/Priya Raman/)).toBeInTheDocument();
  });

  it('states what happens to the audio before any is captured', () => {
    render(<ConsentScreen {...CONSENT_CONFIRMED} />);

    expect(screen.getByText('Never saved as a file')).toBeInTheDocument();
    expect(screen.getByText('Destroyed after transcription')).toBeInTheDocument();
  });
});

describe('recording review', () => {
  it('shows both engines and only the spans they disagreed on', () => {
    render(<RecordingScreen {...RECORDING} />);

    expect(screen.getByText('Deepgram Nova-3')).toBeInTheDocument();
    expect(screen.getByText('AssemblyAI Universal-2')).toBeInTheDocument();
    expect(screen.getByText('3')).toBeInTheDocument();
  });

  it('puts the two readings side by side for comparison', () => {
    render(<RecordingScreen {...RECORDING} />);

    expect(screen.getByText(/we run about three fifty a day/)).toBeInTheDocument();
    expect(screen.getByText(/we run about 350 a day/)).toBeInTheDocument();
  });

  it('records that the audio was destroyed', () => {
    render(<RecordingScreen {...RECORDING} />);

    expect(screen.getByText('Destroyed')).toBeInTheDocument();
  });
});

describe('debrief', () => {
  it('marks every claim as stated or inferred', () => {
    // Telling those two apart is the reviewer's core need; a screen that
    // blurred them would be worse than no screen.
    render(<DebriefScreen {...DEBRIEF} />);

    expect(screen.getAllByText('stated').length).toBe(4);
    expect(screen.getAllByText('inferred').length).toBe(2);
  });

  it('shows the utterance each claim rests on', () => {
    render(<DebriefScreen {...DEBRIEF} />);

    expect(
      screen.getByText(/The dashboard just has to be fast/),
    ).toBeInTheDocument();
    expect(screen.getAllByText(/Client — Ops, 08:15/).length).toBeGreaterThan(0);
  });
});

describe('engagement arc', () => {
  it('leads with what is still open rather than what is done', () => {
    render(<ArcScreen {...ARC} />);

    expect(screen.getByText('Carried into the next meeting')).toBeInTheDocument();
    expect(screen.getByText(/What does “fast” mean/)).toBeInTheDocument();
  });

  it('flags a question that has survived more than one meeting', () => {
    render(<ArcScreen {...ARC} />);

    expect(screen.getByText('3 meetings')).toBeInTheDocument();
  });

  it('shows the meetings it came from', () => {
    render(<ArcScreen {...ARC} />);

    expect(screen.getByText('Discovery 1 — current state')).toBeInTheDocument();
    expect(screen.getByText(/6 of 8 sections covered/)).toBeInTheDocument();
  });
});

describe('replay', () => {
  it('shows both gates and their thresholds', () => {
    render(<ReplayScreen {...REPLAY} />);

    expect(screen.getByText('82%')).toBeInTheDocument();
    expect(screen.getByText(/36 of 44 rated · M1 needs 70%/)).toBeInTheDocument();
    expect(screen.getByText(/of 44 rated · M2 needs zero/)).toBeInTheDocument();
  });

  it('marks a failing run as failing', () => {
    const { container } = render(<ReplayScreen {...REPLAY_FAILING} />);

    // Both gates fail on this run: 64% is under M1, and one embarrassing
    // suggestion is one too many for M2.
    expect(container.querySelectorAll('.stat--fail')).toHaveLength(2);
  });

  it('keeps "not useful" and "embarrassing" as separate judgements', () => {
    render(<ReplayScreen {...REPLAY} />);

    expect(screen.getAllByRole('button', { name: 'Useful' }).length).toBe(4);
    expect(screen.getAllByRole('button', { name: 'Embarrassing' }).length).toBe(4);
  });
});

describe('degraded mode', () => {
  it('says the model is unreachable rather than going quiet', () => {
    render(<OperatorPanel initial={DEGRADED} />);

    expect(screen.getByText('Deterministic only')).toBeInTheDocument();
    expect(screen.getByText(/slow lane is paused/)).toBeInTheDocument();
  });

  it('still surfaces the deterministic nudge', () => {
    // The whole point of the two-lane split: an outage makes the product
    // quieter, not absent.
    render(<OperatorPanel initial={DEGRADED} />);

    expect(screen.getByText('How fast is fast?')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Asked it/ })).toBeInTheDocument();
  });
});

describe('capture control', () => {
  it('says which state capture is in, in words as well as colour', () => {
    // Believing you are paused while still recording is the worst failure this
    // product has, so the state is never carried by colour alone (WCAG 1.4.1).
    render(<CaptureScreen {...PAUSED} />);

    expect(screen.getByRole('heading', { name: 'Paused' })).toBeInTheDocument();
    expect(screen.getByText(/Nothing said now is captured/)).toBeInTheDocument();
  });

  it('offers resume when paused and pause when recording', () => {
    const { rerender } = render(<CaptureScreen {...CAPTURING} />);
    expect(screen.getByRole('button', { name: 'Pause recording' })).toBeInTheDocument();

    rerender(<CaptureScreen {...PAUSED} />);
    expect(screen.getByRole('button', { name: 'Resume recording' })).toBeInTheDocument();
  });

  it('warns when the operator is on a room microphone', () => {
    // FR-1.2 requires the product to argue for wired capture, not merely allow it.
    render(<CaptureScreen {...CAPTURING_ACOUSTIC} />);

    expect(screen.getByText(/single largest source of transcription error/)).toBeInTheDocument();
  });

  it('stays quiet about the input when it is already the good one', () => {
    render(<CaptureScreen {...CAPTURING} />);

    expect(screen.queryByText(/single largest source/)).not.toBeInTheDocument();
  });

  it('shows whether the operator’s voice is enrolled', () => {
    render(<CaptureScreen {...CAPTURING} />);
    expect(screen.getByText('Enrolled')).toBeInTheDocument();

    render(<CaptureScreen {...CAPTURING_ACOUSTIC} />);
    expect(screen.getByText('Not enrolled')).toBeInTheDocument();
  });
});

describe('install and roll out', () => {
  it('says whether the build is signed', () => {
    render(<AboutScreen {...ABOUT_MANAGED} />);

    expect(screen.getByText('Signed and notarised')).toBeInTheDocument();
    expect(screen.getByText('Verified')).toBeInTheDocument();
  });

  it('explains that a managed install granted permissions by profile', () => {
    render(<AboutScreen {...ABOUT_MANAGED} />);

    expect(screen.getByText(/granted by profile, so nobody had to answer a prompt/)).toBeInTheDocument();
  });

  it('names a missing permission and what it blocks', () => {
    render(<AboutScreen {...ABOUT_UNMANAGED} />);

    expect(screen.getByText('Needed')).toBeInTheDocument();
    expect(screen.getByText(/Capture will not start without Screen Recording/)).toBeInTheDocument();
  });

  it('says nothing about missing permissions when all are granted', () => {
    render(<AboutScreen {...ABOUT_MANAGED} />);

    expect(screen.queryByText(/Capture will not start/)).not.toBeInTheDocument();
  });
});

describe('provenance the OS could not establish', () => {
  it('renders "unknown" distinctly from "unsigned"', () => {
    // The whole point of reading signing status from the OS rather than being
    // told it: an IT reviewer shown "unsigned" makes a different decision from
    // one shown "we could not check". Collapsing them produces the wrong
    // decision in whichever direction the collapse goes.
    render(<AboutScreen {...ABOUT_MANAGED} signed={null} signedBy={null} />);

    expect(screen.getByText('Signature not checked')).toBeInTheDocument();
    expect(screen.getByText('Unknown')).toBeInTheDocument();
    expect(screen.queryByText('Unsigned')).not.toBeInTheDocument();
    expect(screen.queryByText('Unverified')).not.toBeInTheDocument();
  });

  it('does not claim an install method it could not read', () => {
    render(<AboutScreen {...ABOUT_MANAGED} installedVia="Unknown" />);

    expect(screen.getByText('Install method unknown')).toBeInTheDocument();
    expect(
      screen.getByText(/management state of this machine could not be read/),
    ).toBeInTheDocument();
  });
});

describe('the About screen with nothing to report about permissions', () => {
  /**
   * A live run rendered the Permissions heading with nothing under it, and the
   * check "the OS permissions this build holds are listed" failed on zero rows.
   * The list is passed in empty and always has been: nothing asks the operating
   * system what this build was granted, and outside the installed application
   * there is no operating system to ask.
   *
   * A bare heading reads as "no permissions are needed", which is the opposite
   * of true — capture needs the microphone. Saying nothing is the one answer
   * that misleads.
   */
  it('explains an empty permission list rather than showing a bare heading', () => {
    render(<AboutScreen {...ABOUT_MANAGED} permissions={[]} />);

    expect(screen.getByText(/cannot be read here/i)).toBeInTheDocument();
  });

  it('says nothing extra once there is something to list', () => {
    render(
      <AboutScreen
        {...ABOUT_MANAGED}
        permissions={[{ name: 'Microphone', why: 'Recording the meeting', granted: true }]}
      />,
    );

    expect(screen.queryByText(/cannot be read here/i)).not.toBeInTheDocument();
    expect(screen.getByText('Microphone')).toBeInTheDocument();
  });
});
