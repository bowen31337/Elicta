import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { CaptureScreen, type CaptureSource } from '../route';

/**
 * Choosing which input records the meeting.
 *
 * The packaged app could not do this. It listed two *kinds* — one of them
 * called "Audio interface (line in)" — and opened whatever CoreAudio called
 * the default input, which on a laptop with nothing plugged in is the built-in
 * microphone. So an operator with an interface connected had no way to say
 * which of the two was recording, and the screen told them they were on an
 * interface while the room was being mixed into a single stream. The browser
 * build had been enumerating and offering real devices the whole time.
 */

const INPUTS: CaptureSource = {
  id: 'line-in',
  label: 'Microphone or audio interface',
  kind: 'wired',
  active: false,
  devices: [
    { id: '51', name: 'MacBook Pro Microphone', isDefault: true, degraded: true },
    { id: '77', name: 'Scarlett 2i2 USB', isDefault: false, degraded: false },
  ],
};

const LOOPBACK: CaptureSource = {
  id: 'loopback',
  label: 'Meeting audio (silent join)',
  kind: 'loopback',
  active: false,
};

function renderScreen(props: Partial<Parameters<typeof CaptureScreen>[0]> = {}) {
  return render(
    <CaptureScreen
      state="stopped"
      sources={[INPUTS]}
      elapsed="00:00"
      operatorEnrolled
      enrolmentSeconds={60}
      {...props}
    />,
  );
}

describe('choosing which input records', () => {
  it('offers the devices the path can be pointed at', async () => {
    renderScreen();

    const picker = screen.getByLabelText(/which device to record from/i);

    expect(picker).toBeTruthy();
    expect(screen.getByRole('option', { name: 'Scarlett 2i2 USB' })).toBeTruthy();
  });

  it('names the system default rather than offering a blank first row', async () => {
    // Following the system default is a real choice — it is what every
    // recording did before this picker existed — so it says which device that
    // currently is instead of leaving an empty row to guess at.
    renderScreen();

    expect(
      screen.getByRole('option', { name: /system default \(MacBook Pro Microphone\)/i }),
    ).toBeTruthy();
  });

  it('records from the device that was picked', async () => {
    const onStart = vi.fn();
    renderScreen({ onStart });

    await userEvent.selectOptions(screen.getByLabelText(/which device to record from/i), '77');
    await userEvent.click(screen.getByRole('button', { name: /start recording/i }));

    expect(onStart).toHaveBeenCalledWith('line-in', '77');
  });

  it('asks for no device when the system default is left selected', async () => {
    // Not the id of whichever device happens to be default: the operator
    // asked to follow the system setting, so changing it in System Settings
    // has to change what records.
    const onStart = vi.fn();
    renderScreen({ onStart });

    await userEvent.click(screen.getByRole('button', { name: /start recording/i }));

    expect(onStart).toHaveBeenCalledWith('line-in', undefined);
  });

  it('checks the device that was picked, so the check and the recording agree', async () => {
    const onCheck = vi.fn();
    renderScreen({ onCheck });

    await userEvent.selectOptions(screen.getByLabelText(/which device to record from/i), '77');
    await userEvent.click(screen.getByRole('button', { name: /check/i }));

    expect(onCheck).toHaveBeenCalledWith('line-in', '77');
  });

  it('offers no device picker for a path that takes no device', () => {
    // The loopback tap is what the machine is playing, which is one thing. A
    // list there would be a control that changes nothing.
    renderScreen({ sources: [LOOPBACK] });

    expect(screen.queryByLabelText(/which device to record from/i)).toBeNull();
  });

  it('drops the chosen device when the path changes', async () => {
    // A device id belongs to one path. Carried across it either matches
    // nothing, or matches something else and records from a device the
    // operator did not pick while the screen shows the one they did.
    const onStart = vi.fn();
    renderScreen({ sources: [INPUTS, LOOPBACK], onStart });

    await userEvent.selectOptions(screen.getByLabelText(/which device to record from/i), '77');
    await userEvent.selectOptions(
      screen.getByLabelText(/which input to record from/i),
      'loopback',
    );
    await userEvent.click(screen.getByRole('button', { name: /start recording/i }));

    expect(onStart).toHaveBeenCalledWith('loopback', undefined);
  });

  it('warns when the picked device is the room microphone', async () => {
    // The FR-1.2 warning used to key off the *kind*, which said "line in"
    // whatever device was behind it — so the one case it exists for, a laptop
    // recording the room through its own microphone, never raised it.
    renderScreen();

    await userEvent.selectOptions(screen.getByLabelText(/which device to record from/i), '51');

    expect(screen.getByText(/you are on a room microphone/i)).toBeTruthy();
  });

  it('does not warn when the picked device keeps speakers separable', async () => {
    renderScreen();

    await userEvent.selectOptions(screen.getByLabelText(/which device to record from/i), '77');

    expect(screen.queryByText(/you are on a room microphone/i)).toBeNull();
  });
});
