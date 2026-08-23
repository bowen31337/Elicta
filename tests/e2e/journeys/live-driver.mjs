/**
 * Driving and recording the *live* app, as opposed to the fixed scenes.
 *
 * `capture.mjs` next door drives `/journeys.html?scene=…`, which renders the
 * real components against frozen fixture state. That is right for screenshots
 * a diff has to stay readable across, and it is worth nothing as evidence
 * that anything is wired: a scene renders identically whether the service is
 * running or switched off.
 *
 * This drives `/` — the shell, the sidebar, the features' own `route.tsx`
 * defaults — against a service that is actually up, and records what happened.
 * It follows its sibling in speaking CDP over Node's built-in WebSocket rather
 * than taking a browser-automation dependency; the addition here is that
 * `Page.startScreencast` already emits JPEG frames, which is exactly what
 * ffmpeg's `image2pipe` wants, so video costs one pipe and no new package.
 */

import { spawn } from 'node:child_process';
import { existsSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';

import { reapOnExit, sweepStaleProfiles } from './reap.mjs';

const sleep = (ms) => new Promise((done) => setTimeout(done, ms));

export const CHROME =
  process.env.CHROME_PATH ??
  `${process.env.HOME}/.cache/ms-playwright/chromium-1228/chrome-linux64/chrome`;

/**
 * Prefer a full ffmpeg when the machine has one: it can encode H.264, which
 * plays anywhere without explanation. Playwright's bundled build is a
 * deliberately stripped one — mjpeg in, VP8/webm out — which is enough for
 * this and is the fallback rather than the default.
 */
export function findFfmpeg() {
  const bundled = `${process.env.HOME}/.cache/ms-playwright/ffmpeg-1011/ffmpeg-linux`;
  for (const candidate of ['/usr/bin/ffmpeg', '/usr/local/bin/ffmpeg', '/snap/bin/ffmpeg']) {
    if (existsSync(candidate)) return { bin: candidate, full: true, ext: 'mp4' };
  }
  if (existsSync(bundled)) return { bin: bundled, full: false, ext: 'webm' };
  return null;
}

export class Cdp {
  constructor(socket) {
    this.socket = socket;
    this.id = 0;
    this.pending = new Map();
    this.listeners = new Map();
    socket.addEventListener('message', (event) => {
      const message = JSON.parse(event.data);
      if (message.id !== undefined) {
        const waiter = this.pending.get(message.id);
        if (!waiter) return;
        this.pending.delete(message.id);
        if (message.error) waiter.reject(new Error(message.error.message));
        else waiter.resolve(message.result);
        return;
      }
      for (const handler of this.listeners.get(message.method) ?? []) handler(message.params);
    });
  }

  on(method, handler) {
    const existing = this.listeners.get(method) ?? [];
    this.listeners.set(method, [...existing, handler]);
  }

  send(method, params = {}) {
    const id = (this.id += 1);
    this.socket.send(JSON.stringify({ id, method, params }));
    return new Promise((resolve, reject) => this.pending.set(id, { resolve, reject }));
  }

  /** Evaluates in the page and returns the JSON value, not the wrapper. */
  async eval(expression) {
    const result = await this.send('Runtime.evaluate', {
      expression: `(() => { ${expression} })()`,
      returnByValue: true,
      awaitPromise: true,
    });
    if (result.exceptionDetails) {
      throw new Error(result.exceptionDetails.exception?.description ?? 'evaluation threw');
    }
    return result.result.value;
  }
}

export async function launchBrowser({ width, height, scale = 2 }) {
  const port = 9222 + Math.floor(Math.random() * 500);
  // A profile of this run's own, thrown away with it. Without one Chrome uses
  // its default profile, so `localStorage` — which is where the toolbar keeps
  // the chosen engagement and meeting — survives from run to run. Against a
  // fresh state database that means the picker opens holding an id the service
  // has never heard of, and journey 1 fails on "the engagement can be chosen
  // from the toolbar" with the previous run's id in the message. It reads
  // exactly like a regression in the picker, and the picker is fine.
  sweepStaleProfiles('elicta-live-run-');
  const profile = mkdtempSync(path.join(tmpdir(), 'elicta-live-run-'));
  const chrome = spawn(
    CHROME,
    [
      '--headless=new',
      `--remote-debugging-port=${port}`,
      `--user-data-dir=${profile}`,
      '--no-sandbox',
      '--disable-gpu',
      '--hide-scrollbars',
      `--window-size=${width},${height}`,
      'about:blank',
    ],
    { stdio: 'ignore' },
  );

  // Registered against the child the instant it exists, not once the session
  // is built: callers reach `close()` on their happy path only, and the paths
  // that skip it — a throw anywhere below, an interrupt, an early exit — are
  // exactly the ones that used to strand the browser. `socket` is captured by
  // reference because the reaper outlives every step that might fail before
  // there is one.
  let socket = null;
  const close = reapOnExit(() => {
    try { socket?.close(); } catch { /* already gone */ }
    chrome.kill();
    // Best effort: a profile left behind is litter in the temp directory,
    // not a failed run, so it must never take the run down with it.
    try { rmSync(profile, { recursive: true, force: true }); } catch { /* ignore */ }
  });

  let wsUrl = null;
  for (let attempt = 0; attempt < 60 && wsUrl === null; attempt += 1) {
    try {
      const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
      wsUrl = targets.find((target) => target.type === 'page')?.webSocketDebuggerUrl ?? null;
    } catch {
      // devtools endpoint not listening yet
    }
    if (wsUrl === null) await sleep(250);
  }
  if (wsUrl === null) {
    close();
    throw new Error('Chrome did not expose a CDP endpoint');
  }

  socket = new WebSocket(wsUrl);
  await new Promise((ready) => socket.addEventListener('open', ready));
  const cdp = new Cdp(socket);

  await cdp.send('Page.enable');
  await cdp.send('Runtime.enable');
  await cdp.send('Log.enable').catch(() => undefined);
  await cdp.send('Network.enable');
  await cdp.send('Emulation.setDeviceMetricsOverride', {
    width,
    height,
    deviceScaleFactor: scale,
    mobile: false,
  });

  return { cdp, chrome, socket, close };
}

/**
 * Screencast frames arrive when the page repaints, which is not a frame rate —
 * a still screen emits nothing at all. Writing them straight through would
 * produce a video where five seconds of a settled screen lasts one frame. So
 * the newest frame is held and re-emitted on a fixed tick instead, which is
 * what makes playback match the wall clock the run actually took.
 */
export class Recorder {
  constructor(cdp, outPath, { fps = 10, scaleTo = 1280, viewport = null } = {}) {
    this.cdp = cdp;
    this.outPath = outPath;
    this.fps = fps;
    this.scaleTo = scaleTo;
    this.viewport = viewport;
    this.latest = null;
    this.frames = 0;
    this.ffmpeg = null;
    this.ticker = null;
  }

  async start(tool) {
    const args = tool.full
      ? ['-y', '-f', 'image2pipe', '-framerate', String(this.fps), '-i', 'pipe:0',
         '-vf', `scale=${this.scaleTo}:-2`, '-c:v', 'libx264', '-preset', 'veryfast',
         '-pix_fmt', 'yuv420p', '-movflags', '+faststart', this.outPath]
      : ['-y', '-f', 'image2pipe', '-c:v', 'mjpeg', '-framerate', String(this.fps), '-i', 'pipe:0',
         '-vf', `scale=${this.scaleTo}:-2`, '-c:v', 'libvpx', '-b:v', '1200k', this.outPath];

    this.ffmpeg = spawn(tool.bin, args, { stdio: ['pipe', 'ignore', 'pipe'] });
    this.stderr = '';
    this.ffmpeg.stderr.on('data', (chunk) => { this.stderr += chunk.toString(); });
    this.ffmpeg.stdin.on('error', () => undefined);

    this.cdp.on('Page.screencastFrame', ({ data, sessionId }) => {
      this.latest = Buffer.from(data, 'base64');
      void this.cdp.send('Page.screencastFrameAck', { sessionId }).catch(() => undefined);
    });

    // Re-assert the emulated viewport immediately before the screencast, or
    // the capture is the headless *window's* visible area instead: Chrome
    // returned 1280x657 against a viewport whose own `innerHeight` reported
    // 800, and the missing 143px were the bottom of the page — exactly where
    // the caption bar is fixed. Every recording silently cropped the one piece
    // of chrome that says what the run was doing at that moment, while the
    // screenshots beside it (`Page.captureScreenshot`, which does honour the
    // override) came out full height. `maxWidth`/`maxHeight` alone do not fix
    // it; they cap a frame rather than choosing what is in it.
    if (this.viewport !== null) {
      await this.cdp.send('Emulation.setDeviceMetricsOverride', {
        width: this.viewport.width,
        height: this.viewport.height,
        deviceScaleFactor: this.viewport.scale ?? 1,
        mobile: false,
      });
    }

    await this.cdp.send('Page.startScreencast', {
      format: 'jpeg',
      quality: 85,
      everyNthFrame: 1,
      ...(this.viewport === null
        ? {}
        : { maxWidth: this.viewport.width, maxHeight: this.viewport.height }),
    });

    this.ticker = setInterval(() => {
      if (this.latest === null || this.ffmpeg === null) return;
      if (this.ffmpeg.stdin.writable) {
        this.ffmpeg.stdin.write(this.latest);
        this.frames += 1;
      }
    }, Math.round(1000 / this.fps));
  }

  async stop() {
    if (this.ticker !== null) clearInterval(this.ticker);
    await this.cdp.send('Page.stopScreencast').catch(() => undefined);
    if (this.ffmpeg === null) return { frames: 0, ok: false };
    const done = new Promise((resolve) => this.ffmpeg.on('close', (code) => resolve(code)));
    this.ffmpeg.stdin.end();
    const code = await done;
    return { frames: this.frames, ok: code === 0, stderr: this.stderr };
  }
}

export { sleep };
