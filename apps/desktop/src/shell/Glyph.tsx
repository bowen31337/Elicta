/**
 * Source-list symbols.
 *
 * Drawn rather than imported: SF Symbols cannot be redistributed, and a font
 * of icons would arrive after first paint and reflow the sidebar. These are
 * cut to the same recipe as SF's small weights — a 24 grid, a 1.6 stroke,
 * round caps and joins — so they sit optically with the label beside them.
 *
 * They are decorative. Every row is already labelled in text, so a screen
 * reader that announced these too would read each destination twice.
 */
export type GlyphName =
  | 'clients'
  | 'doc'
  | 'seal'
  | 'waveform'
  | 'mic'
  | 'record'
  | 'pages'
  | 'bubble'
  | 'arc'
  | 'replay'
  | 'sliders'
  | 'info'
  | 'sidebar'
  | 'default';

const PATHS: Record<GlyphName, JSX.Element> = {
  // A folder of clients: the one thing every other screen hangs off.
  clients: (
    <>
      <path d="M3.75 7.25a1 1 0 0 1 1-1h4l1.75 2h8.75a1 1 0 0 1 1 1v9.5a1 1 0 0 1-1 1h-14.5a1 1 0 0 1-1-1Z" />
      <path d="M7.5 13h9" />
    </>
  ),
  doc: (
    <>
      <path d="M6 3.75h6.5L18 9.25v11a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4.75a1 1 0 0 1 1-1Z" />
      <path d="M12.25 4v5.25H17.5" />
      <path d="M9 13.5h6M9 17h4" />
    </>
  ),
  seal: (
    <>
      <circle cx="12" cy="12" r="8.25" />
      <path d="M8.5 12.2l2.4 2.4 4.6-4.9" />
    </>
  ),
  waveform: (
    <>
      <path d="M4 11v2" />
      <path d="M8 8.5v7" />
      <path d="M12 5v14" />
      <path d="M16 8.5v7" />
      <path d="M20 11v2" />
    </>
  ),
  mic: (
    <>
      <rect x="9.25" y="3" width="5.5" height="11" rx="2.75" />
      <path d="M5.75 11.5a6.25 6.25 0 0 0 12.5 0" />
      <path d="M12 17.75V21" />
    </>
  ),
  record: (
    <>
      <circle cx="12" cy="12" r="8.25" />
      <circle cx="12" cy="12" r="3.25" fill="currentColor" stroke="none" />
    </>
  ),
  pages: (
    <>
      <rect x="4" y="6.5" width="11" height="14" rx="1.6" />
      <path d="M8 3.5h9.4a1.6 1.6 0 0 1 1.6 1.6v11.4" />
      <path d="M7.5 11h4M7.5 15h6" />
    </>
  ),
  bubble: (
    <>
      <path d="M20 12.2c0 3.8-3.6 6.9-8 6.9a9.6 9.6 0 0 1-2.2-.25L5 20.5l1.2-3.2A6.5 6.5 0 0 1 4 12.2c0-3.8 3.6-6.9 8-6.9s8 3.1 8 6.9Z" />
      <path d="M9 12h6" />
    </>
  ),
  arc: (
    <>
      <path d="M4 17.5c4.5 0 6-3.2 8-6.4S16.2 5 20 5" />
      <path d="M16.5 5H20v3.5" />
      <circle cx="4" cy="17.5" r="1.5" fill="currentColor" stroke="none" />
    </>
  ),
  replay: (
    <>
      <path d="M19.5 12a7.5 7.5 0 1 1-2.4-5.5" />
      <path d="M19.75 4.5V9h-4.5" />
      <path d="M10.5 9.5l4.5 2.5-4.5 2.5z" fill="currentColor" stroke="none" />
    </>
  ),
  sliders: (
    <>
      <path d="M4 7.5h5.5M14 7.5h6" />
      <path d="M4 16.5h6M14.5 16.5h5.5" />
      <circle cx="11.75" cy="7.5" r="2.25" />
      <circle cx="12.25" cy="16.5" r="2.25" />
    </>
  ),
  info: (
    <>
      <circle cx="12" cy="12" r="8.25" />
      <path d="M12 11v5.25" />
      <circle cx="12" cy="7.9" r="0.9" fill="currentColor" stroke="none" />
    </>
  ),
  sidebar: (
    <>
      <rect x="3.25" y="4.75" width="17.5" height="14.5" rx="2.4" />
      <path d="M9.75 4.75v14.5" />
    </>
  ),
  default: (
    <>
      <circle cx="12" cy="12" r="8.25" />
      <circle cx="12" cy="12" r="2" fill="currentColor" stroke="none" />
    </>
  ),
};

export function Glyph({ name, size = 17 }: { name: GlyphName; size?: number }) {
  return (
    <svg
      className="glyph"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {PATHS[name] ?? PATHS.default}
    </svg>
  );
}
