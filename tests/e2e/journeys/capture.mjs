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
 */

import { spawn } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = resolve(HERE, '../../../docs/journeys/screenshots');
const APP = process.env.JOURNEY_BASE_URL ?? 'http://127.0.0.1:1420';
const CHROME =
  process.env.CHROME_PATH ??
  `${process.env.HOME}/.cache/ms-playwright/chromium-1228/chrome-linux64/chrome`;

/** The panel ships in a 420x720 window; capturing at that size keeps the
 *  screenshots honest about how much actually fits on screen. */
const PANEL = { width: 420, height: 720 };
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
  { scene: 'settings-first-run', name: 'settings-first-run', ...SETTINGS },
  { scene: 'settings-configured', name: 'settings-configured', ...SETTINGS },
  { scene: 'settings-compatible', name: 'settings-compatible-endpoint', ...SETTINGS },
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

function launchChrome(port) {
  const chrome = spawn(
    CHROME,
    [
      '--headless=new',
      `--remote-debugging-port=${port}`,
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
  await waitForApp();
  mkdirSync(OUT, { recursive: true });

  const port = 9222 + Math.floor(Math.random() * 500);
  const chrome = launchChrome(port);
  const socket = new WebSocket(await connect(port));
  await new Promise((ready) => socket.addEventListener('open', ready));
  const cdp = new Cdp(socket);

  await cdp.send('Page.enable');
  await cdp.send('Runtime.enable');

  let captured = 0;
  for (const { scene, name, width, height, action } of SCENES) {
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

    const { data } = await cdp.send('Page.captureScreenshot', { format: 'png' });
    writeFileSync(`${OUT}/${name}.png`, Buffer.from(data, 'base64'));
    console.log(`  captured ${name}.png`);
    captured += 1;
  }

  socket.close();
  chrome.kill();
  console.log(`\n${captured} screenshots written to docs/journeys/screenshots/`);
}

main().catch((error) => {
  console.error(error.message);
  process.exit(1);
});
