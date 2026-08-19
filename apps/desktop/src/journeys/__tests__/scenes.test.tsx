import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { OperatorPanel } from '../../features/panel/route';
import { SettingsPanel } from '../../features/settings/SettingsPanel';
import { BEFORE_MEETING, CODE_SWITCHED, NUDGE_SURFACED } from '../scenes';
import { STUB_SETTINGS_CONTROLLER } from '../settingsScenes';

/**
 * The journey scenes, asserted in CI.
 *
 * The screenshots in `docs/journeys/` need a browser, which CI does not run.
 * These assert the same scenes render what the journey documents claim, so a
 * component change breaks the build rather than silently making the
 * documentation wrong — a stale screenshot is worse than none, because it is
 * still believed.
 */

describe('journey scenes', () => {
  it('before the meeting: coverage is visible and no nudge is shown', () => {
    render(<OperatorPanel initial={BEFORE_MEETING} />);

    expect(screen.getByText('0 / 4')).toBeInTheDocument();
    expect(screen.queryByText(/How fast is fast/)).not.toBeInTheDocument();
  });

  it('a surfaced nudge shows stub, question and trigger reason', () => {
    render(<OperatorPanel initial={NUDGE_SURFACED} />);

    expect(screen.getByText('How fast is fast?')).toBeInTheDocument();
    expect(screen.getByText(/what does that mean in seconds/)).toBeInTheDocument();
    // FR-5.11: the operator must be able to tell at a glance whether the
    // system understood the room or misheard it.
    expect(screen.getByText(/unquantified adjective/)).toBeInTheDocument();
  });

  it('the operator has all three responses in reach', () => {
    render(<OperatorPanel initial={NUDGE_SURFACED} />);

    expect(screen.getByRole('button', { name: /Asked it/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Park it/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /What am I missing/ })).toBeInTheDocument();
  });

  it('tapping Asked it advances coverage in the same render pass', async () => {
    render(<OperatorPanel initial={NUDGE_SURFACED} />);
    expect(screen.getByText('1 / 4')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /Asked it/ }));

    await waitFor(() => expect(screen.getByText('2 / 4')).toBeInTheDocument());
  });

  it('a code-switched meeting tags both languages', () => {
    render(<OperatorPanel initial={CODE_SWITCHED} />);

    expect(screen.getByText('EN')).toBeInTheDocument();
    expect(screen.getByText('ZH')).toBeInTheDocument();
  });

  it('the code-switched nudge carries the grouped numeral', () => {
    // 三百五十万 must reach the operator as 3,500,000 — a quantify nudge whose
    // answer is captured at the wrong order of magnitude is worse than none.
    render(<OperatorPanel initial={CODE_SWITCHED} />);

    expect(screen.getByText(/3,500,000/)).toBeInTheDocument();
  });

  it('first run shows nothing configured', () => {
    render(<SettingsPanel controller={STUB_SETTINGS_CONTROLLER['settings-first-run']} />);

    expect(screen.getAllByText('No key is stored yet.').length).toBeGreaterThan(0);
    expect(screen.getByText(/will be lost when the service/)).toBeInTheDocument();
  });

  it('a configured screen shows hints and never a secret', () => {
    render(<SettingsPanel controller={STUB_SETTINGS_CONTROLLER['settings-configured']} />);

    expect(screen.getByLabelText('Anthropic API key')).toHaveAttribute(
      'placeholder',
      'Configured — ends x7q2',
    );
    expect(screen.getByText('in use')).toBeInTheDocument();
  });

  it('a compatible endpoint scene shows the endpoint field', () => {
    render(<SettingsPanel controller={STUB_SETTINGS_CONTROLLER['settings-compatible']} />);

    expect(screen.getByLabelText('Endpoint')).toHaveValue('https://llm.internal/v1');
  });

  it('the recording pair is two different vendors', () => {
    render(<SettingsPanel controller={STUB_SETTINGS_CONTROLLER['settings-configured']} />);

    expect(screen.getByText('Deepgram + AssemblyAI')).toBeInTheDocument();
  });

  it('no scene fixture contains anything shaped like a real credential', () => {
    // Screenshots of this screen are committed. A fixture that looked like a
    // live key would be indistinguishable from a leaked one at review time.
    const fixtures = JSON.stringify(
      Object.values(STUB_SETTINGS_CONTROLLER).map((controller) => controller.settings),
    );

    expect(fixtures).not.toMatch(/sk-ant-[A-Za-z0-9-]{10,}/);
    expect(fixtures).not.toMatch(/oat-[A-Za-z0-9-]{10,}/);
  });
});
