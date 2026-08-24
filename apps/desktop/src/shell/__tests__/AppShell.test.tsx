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
