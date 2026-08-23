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

/** Audited at both widths the product is actually seen at: the 420px panel —
 *  which also exercises WCAG 1.4.10 reflow — and the desk width the review
 *  screens are read at. Layout changes with width, and so can contrast: a
 *  wrapped label sits on a different ground than an unwrapped one. */
const VIEWPORTS = [
  { width: 420, height: 900 },
  { width: 820, height: 1100 },
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
  await cdp.send('Emulation.setDeviceMetricsOverride', { ...viewport, deviceScaleFactor: 1, mobile: false });
  for (const theme of THEMES) {
    await cdp.send('Emulation.setEmulatedMedia', {
      features: [{ name: 'prefers-color-scheme', value: theme }],
    });

    for (const scene of SCENES) {
      await cdp.send('Page.navigate', { url: `${APP}/journeys.html?scene=${scene}` });
      await sleep(700);
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
        findings.push({ theme, scene, width: viewport.width, ...violation });
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
        `× ${VIEWPORTS.length} widths (${VIEWPORTS.map((v) => v.width + 'px').join(', ')}).\n`,
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
      console.log(`    [${finding.theme}/${finding.scene}@${finding.width}] ${finding.id}: ${finding.nodes[0]?.target}`);
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
