#!/usr/bin/env node
/**
 * Runs the twelve journeys against a live system and records what happened.
 *
 *   ELICTA_ANTHROPIC_TOKEN=… node tests/e2e/journeys/live-run.mjs \
 *     --app http://192.168.99.233:1420 --api http://192.168.99.233:8000 --out ./out
 *
 * One video and a numbered set of screenshots per journey, plus `report.json`
 * and `report.md`. Checks record rather than throw: the point of the run is a
 * map of what is connected, and a map that stops at the first hole is not one.
 */

import { mkdirSync, writeFileSync } from 'node:fs';
import { launchBrowser, Recorder, findFfmpeg, sleep } from './live-driver.mjs';
import { JOURNEYS } from './live-journeys.mjs';

const argv = process.argv.slice(2);
const arg = (name, fallback) => {
  const at = argv.indexOf(`--${name}`);
  return at === -1 ? fallback : argv[at + 1];
};

const APP = arg('app', 'http://127.0.0.1:1420');
const API = arg('api', 'http://127.0.0.1:8000');
const OUT = arg('out', './live-run-out');
const ONLY = arg('only', null);
const VIEWPORT = { width: 1280, height: 800, scale: 2 };

const SECRETS = {
  anthropicToken: process.env.ELICTA_ANTHROPIC_TOKEN ?? '',
  deepgramKey: process.env.ELICTA_DEEPGRAM_KEY ?? '',
};
if (SECRETS.anthropicToken === '') {
  console.error('ELICTA_ANTHROPIC_TOKEN is not set — journey 10 cannot run.');
  process.exit(2);
}

/** Never let a secret reach a log line, a report or a filename. */
const redact = (text) => {
  if (typeof text !== 'string') return text;
  let out = text;
  for (const secret of [SECRETS.anthropicToken, SECRETS.deepgramKey]) {
    if (secret) out = out.split(secret).join('«redacted»');
  }
  return out;
};

async function callApi(method, path, body, timeoutMs = 30000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${API}${path}`, {
      method,
      signal: controller.signal,
      headers: body ? { 'content-type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
    const text = await response.text();
    let json = null;
    try { json = JSON.parse(text); } catch { json = text.slice(0, 400); }
    return { status: response.status, json };
  } catch (error) {
    return { status: 0, json: { error: String(error.message ?? error) } };
  } finally {
    clearTimeout(timer);
  }
}

/** A caption bar so a recording explains itself without a commentary track.
 *  It is harness chrome, drawn over the app rather than part of it. */
const OVERLAY = (journey, message) => `
  let bar = document.getElementById('__elicta_caption');
  if (!bar) {
    bar = document.createElement('div');
    bar.id = '__elicta_caption';
    bar.style.cssText = 'position:fixed;left:0;right:0;bottom:0;z-index:2147483647;' +
      'font:500 14px/1.45 ui-sans-serif,system-ui,sans-serif;color:#fff;' +
      'background:rgba(10,12,16,.92);padding:10px 16px;display:flex;gap:14px;' +
      'align-items:baseline;pointer-events:none';
    document.body.appendChild(bar);
  }
  bar.innerHTML = '<span style="opacity:.62;letter-spacing:.06em;text-transform:uppercase;' +
    'font-size:11px;white-space:nowrap">' + ${JSON.stringify(journey)} + '</span>' +
    '<span>' + ${JSON.stringify(message)} + '</span>';
  return true;`;

async function main() {
  const tool = findFfmpeg();
  if (tool === null) throw new Error('No ffmpeg found — cannot record.');
  mkdirSync(OUT, { recursive: true });
  console.log(`app ${APP}\napi ${API}\nout ${OUT}\nffmpeg ${tool.bin} (${tool.ext})\n`);

  const { cdp, close } = await launchBrowser(VIEWPORT);
  const consoleErrors = [];
  cdp.on('Runtime.exceptionThrown', ({ exceptionDetails }) =>
    consoleErrors.push(redact(exceptionDetails?.exception?.description ?? 'exception')));
  const failedRequests = [];
  cdp.on('Network.responseReceived', ({ response }) => {
    if (response.status >= 400) failedRequests.push(`${response.status} ${response.url}`);
  });

  await cdp.send('Page.navigate', { url: `${APP}/#/about` });
  await sleep(3500);

  const state = {};
  const results = [];
  const selected = ONLY ? JOURNEYS.filter((j) => ONLY.split(',').includes(j.id)) : JOURNEYS;

  for (const journey of selected) {
    const dir = `${OUT}/${journey.id}-${journey.slug}`;
    mkdirSync(dir, { recursive: true });
    const record = {
      id: journey.id, slug: journey.slug, title: journey.title,
      blocked: journey.blocked ?? null, checks: [], notes: [], shots: [], error: null,
      video: `${journey.id}-${journey.slug}/journey.${tool.ext}`,
    };
    let shotIndex = 0;
    const networkAt = failedRequests.length;

    const recorder = new Recorder(cdp, `${dir}/journey.${tool.ext}`, { fps: 10, scaleTo: 1280 });
    await recorder.start(tool);

    const ctx = {
      state, secrets: SECRETS, sleep,
      eval: (expression) => cdp.eval(expression),
      api: (method, path, body = null, timeoutMs) => callApi(method, path, body, timeoutMs),
      async narrate(message) {
        console.log(`    · ${message}`);
        await cdp.eval(OVERLAY(`${journey.id} — ${journey.title}`, message));
        await sleep(900);
      },
      async go(feature) {
        await cdp.eval(`window.location.hash = '#/${feature}'; return true`);
        await sleep(1800);
        await cdp.eval(OVERLAY(`${journey.id} — ${journey.title}`, `Screen: ${feature}`));
      },
      async shot(label) {
        shotIndex += 1;
        const name = `${String(shotIndex).padStart(2, '0')}-${label}.png`;
        const { data } = await cdp.send('Page.captureScreenshot', { format: 'png' });
        writeFileSync(`${dir}/${name}`, Buffer.from(data, 'base64'));
        record.shots.push(name);
      },
      text: (selector) => cdp.eval(
        `const el = document.querySelector(${JSON.stringify(selector)});
         return el ? el.textContent.trim() : null`),
      count: (selector) => cdp.eval(
        `return document.querySelectorAll(${JSON.stringify(selector)}).length`),
      async clickText(tag, label) {
        const clicked = await cdp.eval(
          `const el = [...document.querySelectorAll(${JSON.stringify(tag)})]
             .find(x => x.textContent.trim() === ${JSON.stringify(label)} && !x.disabled);
           if (el) { el.click(); return true; } return false`);
        await sleep(1200);
        return clicked;
      },
      /** React owns a <select>'s value too, so the native setter has to be
       *  called before the change event or React re-renders the old value
       *  straight back over it. */
      async select(selector, value) {
        const ok = await cdp.eval(
          `const el = document.querySelector(${JSON.stringify(selector)});
           if (!el) return false;
           const setter = Object.getOwnPropertyDescriptor(
             window.HTMLSelectElement.prototype, 'value').set;
           setter.call(el, ${JSON.stringify(value)});
           el.dispatchEvent(new Event('change', { bubbles: true }));
           return el.value === ${JSON.stringify(value)}`);
        await sleep(700);
        return ok;
      },
      /** Clicks a button inside the row that owns `selector` — the settings
       *  screen has one "Test" button per credential, so clicking by label
       *  alone would always hit the first. */
      async clickBeside(selector, label) {
        const clicked = await cdp.eval(
          `const field = document.querySelector(${JSON.stringify(selector)});
           const row = field?.closest('.settings-secret-row');
           const el = [...(row?.querySelectorAll('button') ?? [])]
             .find(b => b.textContent.trim() === ${JSON.stringify(label)} && !b.disabled);
           if (el) { el.click(); return true; } return false`);
        await sleep(1200);
        return clicked;
      },
      /** Typed as keystrokes rather than assigned: React owns the value, and
       *  setting `.value` directly changes the DOM without telling React. */
      async type(selector, value, { secret = false } = {}) {
        await cdp.eval(
          `const el = document.querySelector(${JSON.stringify(selector)});
           if (!el) return false; el.focus(); el.select?.(); return true`);
        await cdp.send('Input.insertText', { text: value });
        await sleep(500);
        if (!secret) console.log(`    typed ${JSON.stringify(value)} into ${selector}`);
      },
      check(name, ok, detail) {
        record.checks.push({ name, ok: Boolean(ok), detail: redact(String(detail ?? '')) });
        console.log(`    ${ok ? 'PASS' : 'FAIL'}  ${name}`);
        if (!ok) console.log(`          ${redact(String(detail ?? '')).slice(0, 220)}`);
      },
      note(name, detail) {
        record.notes.push({ name, detail: redact(String(detail ?? '')) });
      },
    };

    console.log(`\n${journey.id} — ${journey.title}`);
    if (journey.blocked) console.log(`    (blocked: ${journey.blocked})`);
    try {
      await journey.run(ctx);
    } catch (error) {
      record.error = redact(String(error.stack ?? error.message ?? error));
      console.log(`    ERROR ${record.error.split('\n')[0]}`);
    }

    await sleep(800);
    const video = await recorder.stop();
    record.frames = video.frames;
    record.videoOk = video.ok;
    record.networkFailures = failedRequests.slice(networkAt);
    record.passed = record.checks.filter((c) => c.ok).length;
    record.failed = record.checks.filter((c) => !c.ok).length;
    results.push(record);
    console.log(`    ${record.passed} passed, ${record.failed} failed · ${video.frames} frames`);
  }

  const summary = {
    startedAgainst: { app: APP, api: API },
    ffmpeg: tool.bin,
    consoleErrors: [...new Set(consoleErrors)].slice(0, 40),
    journeys: results,
    totals: {
      passed: results.reduce((n, r) => n + r.passed, 0),
      failed: results.reduce((n, r) => n + r.failed, 0),
    },
  };
  writeFileSync(`${OUT}/report.json`, JSON.stringify(summary, null, 2));
  console.log(`\n${summary.totals.passed} passed, ${summary.totals.failed} failed across ${results.length} journeys`);
  console.log(`report written to ${OUT}/report.json`);
  close();
  process.exit(0);
}

main().catch((error) => {
  console.error(error.stack ?? error.message);
  process.exit(1);
});
