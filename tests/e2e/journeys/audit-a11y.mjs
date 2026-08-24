#!/usr/bin/env node
/**
 * WCAG 2.2 AA audit of every journey screen, in both themes.
 *
 * Runs axe-core against the real rendered DOM rather than reasoning about the
 * CSS. Contrast in particular cannot be checked by reading a stylesheet: it
 * depends on what a colour composites over, which is only knowable once the
 * page exists.
 *
 * Both themes are audited because they are different palettes, not one palette
 * inverted — a token that clears the bar on white can fail on black.
 *
 * Usage:
 *   pnpm --filter elicta-desktop dev
 *   node tests/e2e/journeys/audit-a11y.mjs           # fails the process on any violation
 *   node tests/e2e/journeys/audit-a11y.mjs --json    # machine-readable
 */

import { spawn } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path, { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { reapOnExit, sweepStaleProfiles } from './reap.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const APP = process.env.JOURNEY_BASE_URL ?? 'http://127.0.0.1:1420';
const CHROME =
  process.env.CHROME_PATH ??
  `${process.env.HOME}/.cache/ms-playwright/chromium-1228/chrome-linux64/chrome`;
const AXE = readFileSync(
  resolve(HERE, '../../../apps/desktop/node_modules/axe-core/axe.min.js'),
  'utf8',
);

const SCENES = [
  // The window itself: source list, toolbar and pane, with fixed screens in
  // it. Audited at 820px the sidebar is docked; at 420px it is a closed
  // drawer, which is the state it ships in at that width.
  'shell',
  'engagements',
  'before-meeting',
  'nudge-surfaced',
  'code-switched',
  'degraded',
  'prep',
  'consent-pending',
  'consent-confirmed',
  'consent-not-required',
  'recording',
  'recording-empty',
  'debrief',
  'debrief-chat',
  'debrief-chat-empty',
  'arc',
  'replay',
  'replay-failing',
  'capturing',
  'paused',
  'capture-acoustic',
  'checking',
  'about-managed',
  'about-unmanaged',
  'settings-first-run',
  'settings-configured',
  'settings-compatible',
];

const THEMES = ['light', 'dark'];

/** Audited at every width the product is actually seen at: the 420px panel —
 *  which also exercises WCAG 1.4.10 reflow — the desk width the review screens
 *  are read at, and a phone. Layout changes with width, and so can contrast: a
 *  wrapped label sits on a different ground than an unwrapped one.
 *
 *  The phone row carries `touch`, and that is not decoration. The panel's
 *  layout for a hand is gated on `(pointer: coarse)` rather than on a width,
 *  because the two tools that document this product both render at 420px with
 *  a cursor and a width gate would have restyled the desk panel as a side
 *  effect. The consequence is that width emulation alone cannot see the touch
 *  layout at all: without `Emulation.setTouchEmulationEnabled` this audit
 *  would report a clean run over a screen it never drew — the docked action
 *  bar, its material, the 34pt nudge and the grid of full-width targets are
 *  all behind that media query. */
const VIEWPORTS = [
  { width: 420, height: 900 },
  { width: 820, height: 1100 },
  { width: 390, height: 844, touch: true },
  // A real desk. 820px is a *narrow* window, and layouts that only exist in a
  // wide one were never audited at all: the preparation screen's contents rail
  // needs 1220px of viewport before there is a margin to put it in, so every
  // colour and target in it was outside this file's reach. The same blind spot
  // is why the touch row exists — a viewport this suite does not visit is a
  // screen it reports clean without drawing.
  { width: 1440, height: 900 },
];

const sleep = (ms) => new Promise((done) => setTimeout(done, ms));

class Cdp {
  constructor(socket) {
    this.socket = socket;
    this.id = 0;
    this.pending = new Map();
    socket.addEventListener('message', (event) => {
      const message = JSON.parse(event.data);
      const waiter = this.pending.get(message.id);
      if (!waiter) return;
      this.pending.delete(message.id);
      message.error
        ? waiter.reject(new Error(message.error.message))
        : waiter.resolve(message.result);
    });
  }

  send(method, params = {}) {
    const id = (this.id += 1);
    this.socket.send(JSON.stringify({ id, method, params }));
    return new Promise((res, rej) => this.pending.set(id, { resolve: res, reject: rej }));
  }
}

async function connect(port) {
  for (let i = 0; i < 40; i += 1) {
    try {
      const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
      const page = targets.find((t) => t.type === 'page');
      if (page) return page.webSocketDebuggerUrl;
    } catch {
      /* not listening yet */
    }
    await sleep(250);
  }
  throw new Error('Chrome did not expose a CDP endpoint');
}

/**
 * Refuse to audit a page that is not the app.
 *
 * axe will happily audit whatever the tab is showing, and Chrome's network
 * error page is a real document — one that carries
 * `maximum-scale=1.0, user-scalable=no` in its own viewport tag. Pointed at a
 * dev server it cannot reach, this tool therefore reported one confident
 * meta-viewport violation per scene: 104 findings about a page belonging to
 * the browser, phrased as findings about Elicta. A pass would be worse than
 * the failure was, because nobody re-reads a green run.
 *
 * The usual cause is protocol, not a stopped server: `start.sh --https` serves
 * TLS on the same port, and a plain-HTTP request to it returns nothing at all
 * rather than redirecting.
 */
async function assertSceneRendered(cdp, scene) {
  const { result } = await cdp.send('Runtime.evaluate', {
    returnByValue: true,
    expression: `JSON.stringify({
      url: location.href,
      mounted: (document.getElementById('root')?.childElementCount ?? 0) > 0,
    })`,
  });
  const { url, mounted } = JSON.parse(result.value);

  if (url.startsWith('chrome-error://')) {
    throw new Error(
      `${scene}: ${APP} did not serve the app — the tab is on Chrome's error ` +
        `page, so every finding below it would be the browser's, not ours. ` +
        `If the dev server is up, check the protocol: --https serves TLS on ` +
        `this port and answers plain HTTP with nothing.`,
    );
  }
  if (!mounted) {
    throw new Error(
      `${scene}: the page loaded from ${APP} but #root is empty, so axe would ` +
        `audit a blank document and call it clean.`,
    );
  }
}

async function main() {
  const json = process.argv.includes('--json');
  const port = 9800 + Math.floor(Math.random() * 300);
  // Chrome mints its own profile under /tmp when it is not given one, and
  // removes it only on a graceful shutdown — which a reaped run is not. On
  // this host /tmp is tmpfs, so each abandoned profile is resident memory
  // rather than disk. Owning the directory makes its removal ours to
  // guarantee instead of Chrome's to skip.
  sweepStaleProfiles('elicta-audit-a11y-');
  const profile = mkdtempSync(path.join(tmpdir(), 'elicta-audit-a11y-'));
  const chrome = spawn(
    CHROME,
    [
      '--headless=new',
      `--remote-debugging-port=${port}`,
      `--user-data-dir=${profile}`,
      '--no-sandbox',
      // `start.sh --https` generates its own certificate in .certs/, so a TLS
      // run is unauditable without this: Chrome would land on an interstitial
      // and the scene check below would stop the run. Scoped to an https base
      // URL rather than always on, because silently accepting a bad
      // certificate is not a default worth carrying into an http run.
      ...(APP.startsWith('https:') ? ['--ignore-certificate-errors'] : []),
      'about:blank',
    ],
    { stdio: 'ignore' },
  );
  const reap = reapOnExit(() => {
    chrome.kill();
    try { rmSync(profile, { recursive: true, force: true }); } catch { /* ignore */ }
  });

  const socket = new WebSocket(await connect(port));
  await new Promise((ready) => socket.addEventListener('open', ready));
  const cdp = new Cdp(socket);
  await cdp.send('Page.enable');
  await cdp.send('Runtime.enable');
  const findings = [];

  for (const viewport of VIEWPORTS) {
  const { touch = false, ...metrics } = viewport;
  await cdp.send('Emulation.setDeviceMetricsOverride', { ...metrics, deviceScaleFactor: 1, mobile: touch });
  // What actually flips `(pointer: coarse)`. Device metrics alone leave the
  // primary pointer fine however narrow the viewport is.
  await cdp.send('Emulation.setTouchEmulationEnabled', { enabled: touch, maxTouchPoints: touch ? 5 : 1 });
  for (const theme of THEMES) {
    await cdp.send('Emulation.setEmulatedMedia', {
      features: [{ name: 'prefers-color-scheme', value: theme }],
    });

    for (const scene of SCENES) {
      await cdp.send('Page.navigate', { url: `${APP}/journeys.html?scene=${scene}` });
      await sleep(700);
      await assertSceneRendered(cdp, scene);
      await cdp.send('Runtime.evaluate', { expression: AXE });

      const { result } = await cdp.send('Runtime.evaluate', {
        expression: `axe.run(document, {
          runOnly: { type: 'tag', values: ['wcag2a','wcag2aa','wcag21a','wcag21aa','wcag22aa'] }
        }).then(r => JSON.stringify(r.violations.map(v => ({
          id: v.id, impact: v.impact, help: v.help,
          nodes: v.nodes.map(n => ({ target: n.target.join(' '), summary: n.failureSummary }))
        }))))`,
        awaitPromise: true,
        returnByValue: true,
      });

      for (const violation of JSON.parse(result.value)) {
        findings.push({
          theme,
          scene,
          width: viewport.width,
          pointer: touch ? 'coarse' : 'fine',
          ...violation,
        });
      }
    }
  }
  }

  socket.close();
  reap();

  if (json) {
    console.log(JSON.stringify(findings, null, 2));
  } else if (findings.length === 0) {
    console.log(
      `\n  No WCAG 2.2 AA violations across ${SCENES.length} scenes × ${THEMES.length} themes ` +
        `× ${VIEWPORTS.length} viewports (${VIEWPORTS.map((v) => v.width + 'px' + (v.touch ? ' touch' : '')).join(', ')}).\n`,
    );
  } else {
    const byRule = new Map();
    for (const finding of findings) {
      const key = `${finding.id} (${finding.impact})`;
      byRule.set(key, (byRule.get(key) ?? 0) + finding.nodes.length);
    }
    console.log(`\n  ${findings.length} violation group(s):\n`);
    for (const [rule, count] of [...byRule].sort((a, b) => b[1] - a[1])) {
      console.log(`    ${String(count).padStart(3)}  ${rule}`);
    }
    console.log('\n  Worst offenders:');
    for (const finding of findings.slice(0, 6)) {
      console.log(`    [${finding.theme}/${finding.scene}@${finding.width}${finding.pointer === 'coarse' ? '/touch' : ''}] ${finding.id}: ${finding.nodes[0]?.target}`);
      const detail = finding.nodes[0]?.summary?.split('\n').slice(0, 2).join(' ');
      if (detail) console.log(`        ${detail}`);
    }
    console.log();
  }

  process.exit(findings.length === 0 ? 0 : 1);
}

main().catch((error) => {
  console.error(error.message);
  process.exit(2);
});
