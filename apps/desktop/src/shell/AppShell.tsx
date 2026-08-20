import { useCallback, useEffect, useRef, useState } from 'react';

import './shell.css';

import { Mark } from '../ui/Mark';
import { Glyph } from './Glyph';
import { bySection, type Destination } from './destinations';

/**
 * The window.
 *
 * Elicta is a set of screens an operator moves between across an engagement,
 * which on this platform is a split view: a source list on the left, a toolbar
 * naming where you are, and one screen at a time in the pane. Before this,
 * every feature rendered at once down a single seven-thousand-pixel scroll —
 * navigable only by knowing what order the files happened to glob in.
 *
 * The selected screen lives in the URL fragment (`#/settings`), so a screen can
 * be linked, reloaded and reached with the browser's own back and forward.
 * Rows are ordinary anchors for the same reason: keyboard, focus and
 * command-click come from the platform rather than from us re-implementing it.
 */
export interface AppShellProps {
  readonly destinations: readonly Destination[];
  /** Renders the screen for a feature. The router owns lazy loading. */
  readonly renderScreen: (destination: Destination) => React.ReactNode;
  /**
   * The control naming which engagement the pane is about, shown at the
   * trailing edge of the toolbar.
   *
   * Injected rather than imported, for the reason `renderScreen` is: this
   * component is the window and knows nothing about the service. Handed a
   * `<SelectionPicker />` by the router, it renders it; handed nothing, it is
   * still a window.
   */
  readonly selector?: React.ReactNode;
}

/** `#/settings` → `settings`. */
function readFragment(): string {
  if (typeof window === 'undefined') return '';
  return decodeURIComponent(window.location.hash.replace(/^#\/?/, '')).trim();
}

export function AppShell({ destinations, renderScreen, selector }: AppShellProps) {
  const [fragment, setFragment] = useState(readFragment);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);
  const paneRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const onHashChange = () => setFragment(readFragment());
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  // An unknown or empty fragment lands on the first destination rather than
  // an error page: the fragment is a convenience, not a route contract.
  const selected =
    destinations.find((destination) => destination.feature === fragment) ?? destinations[0] ?? null;

  // A new screen starts at its own top. Carrying the previous screen's scroll
  // position over drops the reader into the middle of a document they have
  // not seen the start of.
  useEffect(() => {
    // Assigned rather than scrolled: arriving at a screen is not a journey
    // through the previous one, so it should not be animated.
    if (paneRef.current !== null) paneRef.current.scrollTop = 0;
    setScrolled(false);
    setDrawerOpen(false);
  }, [selected?.feature]);

  useEffect(() => {
    if (selected) document.title = `Elicta — ${selected.title}`;
  }, [selected?.title]);

  // Escape closes the sidebar when it is over the content, which is the only
  // state it can be dismissed from.
  useEffect(() => {
    if (!drawerOpen) return undefined;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setDrawerOpen(false);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [drawerOpen]);

  const onPaneScroll = useCallback(() => {
    // The toolbar only earns its edge treatment once something is actually
    // underneath it; on a short screen it stays flat.
    setScrolled((current) => {
      const next = (paneRef.current?.scrollTop ?? 0) > 6;
      return next === current ? current : next;
    });
  }, []);

  if (selected === null) {
    return (
      <div className="shell shell--empty">
        <p className="t-body">No screens are registered in this build.</p>
      </div>
    );
  }

  return (
    <div className={`shell${drawerOpen ? ' is-drawer-open' : ''}`}>
      <aside className="sidebar" id="sidebar">
        <div className="sidebar-head">
          <Mark size={22} title="Elicta" />
          <span className="sidebar-wordmark">Elicta</span>
        </div>

        <nav className="sidebar-nav" aria-label="Screens">
          {bySection(destinations).map((group) => (
            <div className="sidebar-group" key={group.section}>
              <h2 className="t-section sidebar-group-title">{group.title}</h2>
              <ul className="sidebar-list">
                {group.items.map((destination) => {
                  const current = destination.feature === selected.feature;
                  return (
                    <li key={destination.feature}>
                      <a
                        className={`sidebar-item${current ? ' is-selected' : ''}`}
                        href={`#/${destination.feature}`}
                        aria-current={current ? 'page' : undefined}
                      >
                        <Glyph name={destination.glyph} />
                        <span className="sidebar-item-label">{destination.title}</span>
                      </a>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </nav>
      </aside>

      {/* Only reachable when the sidebar is over the content; at desk width
          the sidebar is part of the layout and there is nothing to dismiss. */}
      <button
        className="sidebar-scrim"
        type="button"
        tabIndex={-1}
        aria-hidden="true"
        onClick={() => setDrawerOpen(false)}
      />

      <div className="pane">
        <header className={`toolbar${scrolled ? ' is-scrolled' : ''}`}>
          <button
            className="toolbar-button"
            type="button"
            aria-expanded={drawerOpen}
            aria-controls="sidebar"
            onClick={() => setDrawerOpen((open) => !open)}
          >
            <Glyph name="sidebar" size={18} />
            <span className="sr-only">
              {drawerOpen ? 'Hide the list of screens' : 'Show the list of screens'}
            </span>
          </button>
          <div className="toolbar-titles">
            <span className="toolbar-title t-headline">{selected.title}</span>
            <span className="toolbar-caption t-caption">{selected.caption}</span>
          </div>
          {selector}
        </header>

        <div className="pane-scroll" ref={paneRef} onScroll={onPaneScroll}>
          {/* Keyed on the destination so a screen change is an arrival — the
              material settles into place rather than the old screen's pixels
              being overwritten in situ. */}
          <div
            className={`pane-body materialize${selected.floating ? ' pane-body--stage' : ''}`}
            key={selected.feature}
          >
            {renderScreen(selected)}
          </div>
        </div>
      </div>
    </div>
  );
}
