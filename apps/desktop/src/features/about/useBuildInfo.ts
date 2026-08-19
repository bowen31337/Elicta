declare const __APP_VERSION__: string;

export interface BuildInfo {
  readonly version: string;
  readonly platform: string;
  readonly architecture: string;
}

/**
 * What the app can honestly know about itself from inside the webview.
 *
 * Version comes from the package manifest at build time, so it cannot drift
 * from what shipped. Platform and architecture are read from the browser.
 *
 * Signing status and install method are deliberately *not* here: neither is
 * observable from a webview. They come from the desktop shell, which can ask
 * the OS, and until it does the screen shows what it was given rather than a
 * confident guess. A screen that guessed "signed" would be worse than one that
 * admits it does not know.
 */
export function buildInfo(): BuildInfo {
  const agent = typeof navigator === 'undefined' ? '' : navigator.userAgent;
  const platform =
    /Mac/i.test(agent) ? 'macOS' : /Win/i.test(agent) ? 'Windows' : /Linux/i.test(agent) ? 'Linux' : 'Unknown';
  const architecture = /arm64|aarch64/i.test(agent) ? 'arm64' : /x86_64|Win64|x64/i.test(agent) ? 'x64' : '';

  return {
    version: typeof __APP_VERSION__ === 'string' ? __APP_VERSION__ : '—',
    platform,
    architecture,
  };
}
