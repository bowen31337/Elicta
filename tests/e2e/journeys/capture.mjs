#!/usr/bin/env node
/**
 * Regenerates the screenshots in `docs/journeys/screenshots/`.
 *
 * Talks CDP directly over Node's built-in WebSocket rather than pulling in a
 * browser-automation dependency: this runs a handful of navigations and one
 * screenshot each, and a dependency that only documentation needs is one more
 * thing to keep current.
 *
 * The scenes come from `apps/desktop/src/journeys/`, which renders the real
 * components with fixed state. Fixed state is the point — a screenshot that
 * changes because a clock moved makes every diff noise, and a diff that is
 * always noise stops being read.
 *
 * Usage:
 *   pnpm --filter elicta-desktop dev      # in another shell
 *   node tests/e2e/journeys/capture.mjs
 *   node tests/e2e/journeys/capture.mjs settings-   # just these
 *
 * A trailing argument keeps only the screenshots whose name starts with it.
 * Regenerating all of them to fix one is not free: every rewritten file is a
 * diff a person has to read, and a chapter showing an unrelated screen gets
 * asked for a re-read it does not need.
 */

import { spawn } from 'node:child_process';
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path, { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { reapOnExit, sweepStaleProfiles } from './reap.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = resolve(HERE, '../../../docs/journeys/screenshots');
const APP = process.env.JOURNEY_BASE_URL ?? 'http://127.0.0.1:1420';
const CHROME =
  process.env.CHROME_PATH ??
  `${process.env.HOME}/.cache/ms-playwright/chromium-1228/chrome-linux64/chrome`;

/** The panel ships in a 420x720 window; capturing at that size keeps the
 *  screenshots honest about how much actually fits on screen. */
const PANEL = { width: 420, height: 720 };
/**
 * Settings is taller than any window it is read in, so its screenshots show
 * the top and `stopAfter` decides where they end.
 *
 * A fixed height is what broke here: the box stayed 1000 while the screen
 * grew credentials, storage, documents, speech, capture and consent, so the
 * picture came to end partway down a card with a floating Save bar across it
 * — which reads as a broken screen rather than a cropped one. A boundary
 * named in words survives the next section being added; a number does not.
 */
const SETTINGS = { width: 480, height: 1000 };
/** The review screens are read at desk width, not in the meeting panel. */
const SCREEN = { width: 820, height: 1100 };

const SCENES = [
  { scene: 'before-meeting', name: 'panel-before-meeting', ...PANEL },
  { scene: 'nudge-surfaced', name: 'panel-nudge-surfaced', ...PANEL },
  { scene: 'code-switched', name: 'panel-code-switched', ...PANEL },
  {
    scene: 'nudge-surfaced',
    name: 'panel-asked-it',
    ...PANEL,
    // Tap the chip and capture the confirmed state, so the screenshot shows
    // the coverage meter actually moving rather than a staged "after" fixture.
    action: `[...document.querySelectorAll('button')]
       .find(b => b.textContent.includes('Asked it'))?.click()`,
  },
  { scene: 'degraded', name: 'panel-degraded', ...PANEL },
  // Taller than the other review screens: preparation grew documents,
  // vocabulary, the bank, meetings and engagement management, and a picture
  // cropped above half of what the chapter describes is worse than no picture.
  { scene: 'engagements', name: 'engagements-list', ...SCREEN },
  { scene: 'prep', name: 'prep-question-tree', ...SCREEN, height: 2000 },
  { scene: 'consent-pending', name: 'consent-pending', ...SCREEN },
  { scene: 'consent-confirmed', name: 'consent-confirmed', ...SCREEN },
  { scene: 'consent-not-required', name: 'consent-not-asked', ...SCREEN },
  { scene: 'recording', name: 'recording-divergences', ...SCREEN },
  { scene: 'debrief', name: 'debrief-artifacts', ...SCREEN },
  { scene: 'debrief-chat', name: 'debrief-conversation', ...SCREEN },
  { scene: 'debrief-chat-empty', name: 'debrief-conversation-start', ...SCREEN },
  { scene: 'arc', name: 'arc-carried-forward', ...SCREEN },
  { scene: 'replay', name: 'replay-passing', ...SCREEN },
  { scene: 'replay-failing', name: 'replay-failing', ...SCREEN },
  { scene: 'capturing', name: 'capture-recording', ...SCREEN },
  { scene: 'paused', name: 'capture-paused', ...SCREEN },
  { scene: 'capture-acoustic', name: 'capture-acoustic-warning', ...SCREEN },
  { scene: 'about-managed', name: 'about-managed', ...SCREEN },
  { scene: 'about-unmanaged', name: 'about-unmanaged', ...SCREEN },
  { scene: 'settings-first-run', name: 'settings-first-run', ...SETTINGS,
    stopAfter: 'Where the data is kept' },
  { scene: 'settings-configured', name: 'settings-configured', ...SETTINGS,
    stopAfter: 'Where the data is kept' },
  { scene: 'settings-compatible', name: 'settings-compatible-endpoint', ...SETTINGS,
    stopAfter: 'Where the data is kept' },
  {
    scene: 'settings-configured',
    name: 'settings-speech-vendors',
    ...SETTINGS,
    action: `document.querySelector('#live-vendor')
       ?.scrollIntoView({ block: 'center' })`,
  },
];

const sleep = (ms) => new Promise((done) => setTimeout(done, ms));

async function waitForApp() {
  for (let attempt = 0; attempt < 30; attempt += 1) {
    try {
      const response = await fetch(`${APP}/journeys.html`);
      if (response.ok) return;
    } catch {
      // dev server not up yet
    }
    await sleep(500);
  }
  throw new Error(
    `${APP}/journeys.html is not reachable. Start it with:\n` +
      '  pnpm --filter elicta-desktop dev',
  );
}

function launchChrome(port, profile) {
  const chrome = spawn(
    CHROME,
    [
      '--headless=new',
      `--remote-debugging-port=${port}`,
      `--user-data-dir=${profile}`,
      '--no-sandbox',
      '--hide-scrollbars',
      '--force-device-scale-factor=2',
      'about:blank',
    ],
    { stdio: 'ignore' },
  );
  return chrome;
}

async function connect(port) {
  for (let attempt = 0; attempt < 40; attempt += 1) {
    try {
      const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
      const page = targets.find((target) => target.type === 'page');
      if (page) return page.webSocketDebuggerUrl;
    } catch {
      // devtools endpoint not listening yet
    }
    await sleep(250);
  }
  throw new Error('Chrome did not expose a CDP endpoint');
}

class Cdp {
  constructor(socket) {
    this.socket = socket;
    this.id = 0;
    this.pending = new Map();
    socket.addEventListener('message', (event) => {
      const message = JSON.parse(event.data);
      const waiter = this.pending.get(message.id);
      if (waiter) {
        this.pending.delete(message.id);
        message.error ? waiter.reject(new Error(message.error.message)) : waiter.resolve(message.result);
      }
    });
  }

  send(method, params = {}) {
    const id = (this.id += 1);
    this.socket.send(JSON.stringify({ id, method, params }));
    return new Promise((resolve, reject) => this.pending.set(id, { resolve, reject }));
  }
}

async function main() {
  const only = process.argv.slice(2);
  const wanted = only.length
    ? SCENES.filter((entry) => only.some((prefix) => entry.name.startsWith(prefix)))
    : SCENES;
  if (!wanted.length) {
    throw new Error(`no screenshot name starts with: ${only.join(', ')}`);
  }

  await waitForApp();
  mkdirSync(OUT, { recursive: true });

  const port = 9222 + Math.floor(Math.random() * 500);
  // Chrome mints its own profile under /tmp when it is not given one, and
  // removes it only on a graceful shutdown — which a reaped run is not. On
  // this host /tmp is tmpfs, so each abandoned profile is resident memory
  // rather than disk. Owning the directory makes its removal ours to
  // guarantee instead of Chrome's to skip.
  sweepStaleProfiles('elicta-capture-');
  const profile = mkdtempSync(path.join(tmpdir(), 'elicta-capture-'));
  const chrome = launchChrome(port, profile);
  const reap = reapOnExit(() => {
    chrome.kill();
    try { rmSync(profile, { recursive: true, force: true }); } catch { /* ignore */ }
  });
  const socket = new WebSocket(await connect(port));
  await new Promise((ready) => socket.addEventListener('open', ready));
  const cdp = new Cdp(socket);

  await cdp.send('Page.enable');
  await cdp.send('Runtime.enable');

  let captured = 0;
  for (const { scene, name, width, height, action, stopAfter } of wanted) {
    await cdp.send('Emulation.setDeviceMetricsOverride', {
      width,
      height,
      deviceScaleFactor: 2,
      mobile: false,
    });
    await cdp.send('Page.navigate', { url: `${APP}/journeys.html?scene=${scene}` });
    await sleep(900);

    if (action) {
      await cdp.send('Runtime.evaluate', { expression: action });
      await sleep(400);
    }

    if (stopAfter) {
      // Measure where that section actually ends and re-size the window to
      // it, so the cut lands in the gap between sections rather than through
      // one. Falls back to the declared height when the section is not found
      // — a renamed heading should leave the screenshot as it was, not
      // silently produce a one-pixel image.
      const { result } = await cdp.send('Runtime.evaluate', {
        expression: `(() => {
          const heading = [...document.querySelectorAll('h2')]
            .find((node) => node.textContent.trim() === ${JSON.stringify(stopAfter)});
          if (!heading) return 0;
          const section = heading.closest('section') ?? heading.parentElement;
          const end = section.getBoundingClientRect().bottom + window.scrollY + 18;

          // A bottom-anchored sticky bar — Settings has one carrying Save —
          // floats over the foot of whatever window it is given, so cutting
          // at the section boundary puts it straight across the last card.
          // Leaving its full footprint below the boundary is what makes the
          // shot look like the screen rather than like a broken render.
          // Anchored at the bottom is the test: a sticky *header* resolves
          // \`bottom\` to 'auto' and must not be counted.
          const overlay = [...document.querySelectorAll('body *')].reduce((tallest, node) => {
            const style = getComputedStyle(node);
            if (style.position !== 'sticky' && style.position !== 'fixed') return tallest;
            const offset = parseFloat(style.bottom);
            if (!Number.isFinite(offset)) return tallest;
            const box = node.getBoundingClientRect();
            return box.height > 0 ? Math.max(tallest, box.height + offset) : tallest;
          }, 0);

          return Math.ceil(end + overlay);
        })()`,
        returnByValue: true,
      });
      const measured = Number(result?.value) || 0;
      if (measured > 0) {
        await cdp.send('Emulation.setDeviceMetricsOverride', {
          width,
          height: measured,
          deviceScaleFactor: 2,
          mobile: false,
        });
        await sleep(350);
      } else {
        console.warn(`  ! ${name}: no section titled ${JSON.stringify(stopAfter)}; kept height ${height}`);
      }
    }

    const { data } = await cdp.send('Page.captureScreenshot', { format: 'png' });
    writeFileSync(`${OUT}/${name}.png`, Buffer.from(data, 'base64'));
    console.log(`  captured ${name}.png`);
    captured += 1;
  }

  socket.close();
  reap();
  console.log(`\n${captured} screenshots written to docs/journeys/screenshots/`);
}

main().catch((error) => {
  console.error(error.message);
  process.exit(1);
});
