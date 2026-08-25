import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

/**
 * The dropzone works in a browser and does nothing in the packaged app.
 *
 * `dragDropEnabled` defaults to **true**, and at that setting Tauri installs
 * an OS-level drag handler on the webview. wry's `performDragOperation`
 * override then either hands the drop to that handler *or* calls `super` —
 * and `super` is what lets WebKit deliver the HTML5 `dragover`/`drop` events
 * the dropzone is built on. Handled means swallowed: the operator drags a
 * document onto the panel and nothing at all happens.
 *
 * It cannot fail anywhere it would be noticed. `pnpm dev`, `start.sh` and
 * every test in this suite run in a real browser, where there is no Tauri
 * webview to intercept anything and the dropzone works perfectly. Only the
 * bundle is broken, and the bundle is the thing nobody builds on a whim.
 *
 * So the check looks for the cause rather than waiting for the effect, the
 * way the file-casing guard beside it does. Nothing in this app listens for
 * `tauri://drag-drop`, so turning the interception off costs nothing; if that
 * ever changes, this test is the place that explains the trade.
 */
const CONFIG = join(__dirname, '..', '..', 'src-tauri', 'tauri.conf.json');

interface TauriConfig {
  readonly app?: { readonly windows?: readonly Record<string, unknown>[] };
}

function windows(): readonly Record<string, unknown>[] {
  const parsed = JSON.parse(readFileSync(CONFIG, 'utf8')) as TauriConfig;
  return parsed.app?.windows ?? [];
}

describe('the packaged window lets the page handle dropped files', () => {
  it('declares dragDropEnabled false on every window', () => {
    const declared = windows();

    expect(declared.length).toBeGreaterThan(0);
    for (const window of declared) {
      // Explicitly false, not merely absent: absent *is* the broken value.
      expect(window.dragDropEnabled).toBe(false);
    }
  });
});
