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
import { existsSync } from 'node:fs';

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
  const chrome = spawn(
    CHROME,
    [
      '--headless=new',
      `--remote-debugging-port=${port}`,
      '--no-sandbox',
      '--disable-gpu',
      '--hide-scrollbars',
      `--window-size=${width},${height}`,
      'about:blank',
    ],
    { stdio: 'ignore' },
  );

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
    chrome.kill();
    throw new Error('Chrome did not expose a CDP endpoint');
  }

  const socket = new WebSocket(wsUrl);
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

  return { cdp, chrome, socket, close: () => { socket.close(); chrome.kill(); } };
}

/**
 * Screencast frames arrive when the page repaints, which is not a frame rate —
 * a still screen emits nothing at all. Writing them straight through would
 * produce a video where five seconds of a settled screen lasts one frame. So
 * the newest frame is held and re-emitted on a fixed tick instead, which is
 * what makes playback match the wall clock the run actually took.
 */
export class Recorder {
  constructor(cdp, outPath, { fps = 10, scaleTo = 1280 } = {}) {
    this.cdp = cdp;
    this.outPath = outPath;
    this.fps = fps;
    this.scaleTo = scaleTo;
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

    await this.cdp.send('Page.startScreencast', {
      format: 'jpeg',
      quality: 85,
      everyNthFrame: 1,
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
