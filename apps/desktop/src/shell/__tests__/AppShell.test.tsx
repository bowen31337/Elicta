import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';

import { AppShell } from '../AppShell';
import { buildDestinations } from '../destinations';

/**
 * The window.
 *
 * The failure this replaced was not an ugly one, it was a misleading one:
 * every screen rendered at once down a single scroll, so the app looked like
 * one enormous document and there was no way to tell which screen you were
 * on. The assertions that matter here are therefore about *absence* — that
 * exactly one screen is mounted — and about the fragment, which is the only
 * record of where the operator is.
 */

const DESTINATIONS = buildDestinations(['prep', 'settings', 'about']);

function renderShell() {
  return render(
    <AppShell
      destinations={DESTINATIONS}
      renderScreen={(destination) => <p>{`screen: ${destination.feature}`}</p>}
    />,
  );
}

afterEach(() => {
  window.location.hash = '';
});

describe('the engagement control', () => {
  it('sits in the toolbar, where it applies to whatever is in the pane', () => {
    render(
      <AppShell
        destinations={DESTINATIONS}
        selector={<button type="button">Northwind Freight</button>}
        renderScreen={() => null}
      />,
    );

    const toolbar = screen.getByRole('banner');
    expect(
      within(toolbar).getByRole('button', { name: 'Northwind Freight' }),
    ).toBeInTheDocument();
  });

  it('is still a window when nothing supplies one', () => {
    renderShell();
    expect(screen.getByText('screen: prep')).toBeInTheDocument();
  });
});

describe('choosing a screen', () => {
  it('shows one screen, not all of them', () => {
    renderShell();

    expect(screen.getByText('screen: prep')).toBeInTheDocument();
    expect(screen.queryByText('screen: settings')).not.toBeInTheDocument();
    expect(screen.queryByText('screen: about')).not.toBeInTheDocument();
  });

  it('opens on the screen named in the address, so a link to one is a link to one', () => {
    window.location.hash = '#/settings';
    renderShell();

    expect(screen.getByText('screen: settings')).toBeInTheDocument();
    expect(screen.queryByText('screen: prep')).not.toBeInTheDocument();
  });

  it('follows the browser going back', async () => {
    renderShell();
    expect(screen.getByText('screen: prep')).toBeInTheDocument();

    window.location.hash = '#/about';
    window.dispatchEvent(new HashChangeEvent('hashchange'));

    expect(await screen.findByText('screen: about')).toBeInTheDocument();
  });

  it('falls back to the first screen when the address names one that is gone', () => {
    window.location.hash = '#/dictation';
    renderShell();

    expect(screen.getByText('screen: prep')).toBeInTheDocument();
  });

  it('moves when a row is clicked', async () => {
    renderShell();

    await userEvent.click(screen.getByRole('link', { name: 'Settings' }));
    window.dispatchEvent(new HashChangeEvent('hashchange'));

    expect(await screen.findByText('screen: settings')).toBeInTheDocument();
    expect(window.location.hash).toBe('#/settings');
  });
});

describe('saying where you are', () => {
  it('marks the current row for a screen reader, not only with colour', () => {
    window.location.hash = '#/about';
    renderShell();

    expect(screen.getByRole('link', { name: 'About' })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByRole('link', { name: 'Preparation' })).not.toHaveAttribute('aria-current');
  });

  it('names the screen and what it is for in the toolbar', () => {
    window.location.hash = '#/settings';
    renderShell();

    // Scoped to the toolbar: "Settings" is also the sidebar row, and an
    // assertion that passes on either one would not be checking the toolbar.
    const toolbar = document.querySelector('.toolbar') as HTMLElement;
    expect(within(toolbar).getByText('Settings')).toBeInTheDocument();
    expect(
      within(toolbar).getByText('Providers, credentials and transcription'),
    ).toBeInTheDocument();
  });

  it('titles the window, so a browser tab and a Dock entry read as this screen', () => {
    window.location.hash = '#/about';
    renderShell();

    expect(document.title).toBe('Elicta — About');
  });
});

describe('the sidebar at narrow widths', () => {
  it('reports whether it is open, so the control is not a mystery button', async () => {
    renderShell();
    const toggle = screen.getByRole('button', { name: /list of screens/ });

    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
  });

  it('gets out of the way once a screen has been chosen', async () => {
    renderShell();
    await userEvent.click(screen.getByRole('button', { name: /list of screens/ }));

    await userEvent.click(screen.getByRole('link', { name: 'About' }));
    window.dispatchEvent(new HashChangeEvent('hashchange'));

    expect(await screen.findByText('screen: about')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /list of screens/ })).toHaveAttribute(
      'aria-expanded',
      'false',
    );
  });
});

describe('a build with no screens', () => {
  it('says so rather than rendering an empty window', () => {
    render(<AppShell destinations={[]} renderScreen={() => null} />);
    expect(screen.getByText(/No screens are registered/)).toBeInTheDocument();
  });
});

describe('the pane as somewhere a keyboard can go', () => {
  /**
   * The window scrolls in exactly one place — the pane — and the pane was a
   * bare `<div>` with `overflow-y: auto` inside a shell that is
   * `overflow: hidden`. That combination has a cost nobody paid for: the
   * document has nothing to scroll and an unfocusable div is not in the tab
   * order, so End, Page Down and the arrow keys moved the preparation screen
   * by zero pixels. Measured on the running app, not assumed.
   *
   * On a screen that is twelve viewports long, that left the wheel and
   * dragging the scrollbar as the only ways down. A scrollable region has to
   * be focusable for the keys the platform already binds to work in it.
   */
  it('is a focusable region, so the scroll keys reach it', () => {
    renderShell();

    const pane = screen.getByRole('region', { name: 'Preparation' });
    expect(pane).toHaveAttribute('tabindex', '0');
  });

  it('names itself after the screen it is showing, not "region"', async () => {
    renderShell();

    await userEvent.click(screen.getByRole('link', { name: 'About' }));
    window.dispatchEvent(new HashChangeEvent('hashchange'));

    expect(await screen.findByRole('region', { name: 'About' })).toBeInTheDocument();
  });
});

describe('a screen that outlives being looked at', () => {
  /**
   * A meeting does not pause while somebody looks something up.
   *
   * Unmounted, the live panel's session stream closes and reconnects, its
   * clock restarts from whatever the service last said, and everything it
   * holds that no stream can replay — which bank questions have been dealt
   * with, which nudge was brought back — is gone. An operator who checked a
   * document mid-meeting came back to a panel that had forgotten the meeting.
   *
   * Asserted by **DOM node identity**, not by appearance and not by a render
   * count. A screen rendered afresh looks identical and is not the same, and
   * only the one that was never unmounted still holds a stream open; a render
   * count answers a different question, since React re-renders a mounted
   * component freely. The same element object is the claim that matters.
   *
   * `engagements` leads this list so the shell's default landing is not the
   * panel — otherwise every case here starts already visited.
   */
  const WITH_PANEL = buildDestinations(['engagements', 'panel', 'settings']);

  function renderKeeping() {
    return render(
      <AppShell
        destinations={WITH_PANEL}
        renderScreen={(destination) => <p data-testid={destination.feature}>{destination.title}</p>}
      />,
    );
  }

  const go = (name: RegExp) => userEvent.click(screen.getByRole('link', { name }));

  it('keeps the live panel mounted, and the same one, after navigating away', async () => {
    renderKeeping();
    await go(/live panel/i);
    const panel = screen.getByTestId('panel');

    await go(/settings/i);

    expect(screen.getByTestId('panel')).toBe(panel);
  });

  it('hides it rather than showing two screens at once', async () => {
    renderKeeping();
    await go(/live panel/i);

    await go(/settings/i);

    // `hidden` and not a class: it has to leave the accessibility tree and
    // the tab order too — a keyboard user must not tab into a meeting they
    // are not looking at.
    expect(screen.getByTestId('panel').closest('.pane-body')).toHaveAttribute('hidden');
    expect(screen.getByTestId('settings')).toBeVisible();
  });

  it('shows that same instance again on the way back', async () => {
    renderKeeping();
    await go(/live panel/i);
    const panel = screen.getByTestId('panel');
    await go(/settings/i);

    await go(/live panel/i);

    expect(screen.getByTestId('panel')).toBe(panel);
    expect(screen.getByTestId('panel').closest('.pane-body')).not.toHaveAttribute('hidden');
  });

  it('mounts nothing until the screen has been visited', () => {
    // "Persistent" means it survives leaving, not that it starts before
    // anybody asks: an unopened panel would hold a stream connection and
    // fetch a consent gate for nothing.
    renderKeeping();

    expect(screen.queryByTestId('panel')).not.toBeInTheDocument();
  });

  it('does not keep an ordinary screen', async () => {
    renderKeeping();
    await go(/settings/i);

    await go(/engagements/i);

    expect(screen.queryByTestId('settings')).not.toBeInTheDocument();
  });
});
