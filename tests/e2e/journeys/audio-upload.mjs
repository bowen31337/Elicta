#!/usr/bin/env node
/**
 * Does a recording made in the browser actually reach the service?
 *
 * Every part of the upload path is unit-tested on its own — the resampler, the
 * chunk uploader's sequencing, the consent gate the bridge asks, the tap that
 * reads the samples. What no test covers is the join: a real `getUserMedia`, a
 * real `AudioContext`, a real `fetch` and the real hold on the other end, in
 * one process each. This is that run.
 *
 * **The microphone is Chrome's own fake capture device, not a stubbed
 * `getUserMedia`.** Stubbing the one browser API the feature is built on would
 * test the stub. The fake device delivers a real `MediaStream` through the
 * genuine media path — a beeping tone by default, or a WAV of your choosing.
 *
 * What it asserts, and why these and not others:
 *
 * - **Chunks are numbered from zero with no gaps.** The hold refuses a chunk
 *   that is not the next one expected and goes on refusing every chunk after
 *   it, so a skipped sequence costs the rest of the meeting rather than the
 *   seconds it held. This is the invariant the whole design rests on.
 * - **The bytes account for the seconds.** Sixteen thousand samples per second
 *   of recording, two bytes each. A rate conversion that silently passed 48kHz
 *   through would show up here as three times the audio and nowhere else —
 *   the transcript would come back sped up and read as a bad engine.
 * - **Stop starts the record path.** The audio arriving is worth nothing if
 *   nobody asks for a transcript of it.
 *
 * It is deliberately not in CI: it needs a running service, a running panel,
 * and — from the moment Stop fires — real speech vendors on real credentials.
 *
 *   pnpm --filter elicta-desktop dev            # in another shell
 *   cd apps/service && uv run uvicorn app.main:app   # in another shell
 *   node tests/e2e/journeys/audio-upload.mjs
 *
 * To prove that speech comes back as words rather than that audio comes back
 * as bytes, hand it a WAV. There is no speech fixture in this repository — a
 * megabyte of audio that only a manual harness reads is not worth carrying —
 * so generate one, with anything that speaks:
 *
 *   uv venv /tmp/tts && uv pip install --python /tmp/tts/bin/python piper-tts
 *   /tmp/tts/bin/python -m piper.download_voices en_US-lessac-medium
 *   echo "The dashboard has to be fast." > /tmp/say.txt
 *   /tmp/tts/bin/python -m piper -m en_US-lessac-medium.onnx -i /tmp/say.txt -f /tmp/say.wav
 *   ffmpeg -i /tmp/say.wav -ar 48000 -ac 1 -c:a pcm_s16le /tmp/speech.wav
 *
 *   FAKE_AUDIO=/tmp/speech.wav EXPECT_WORDS="dashboard,fast" \
 *     node tests/e2e/journeys/audio-upload.mjs
 *
 * `EXPECT_WORDS` turns the vendors' answer into an assertion instead of a
 * printout. Without it their answer is reported and not judged, because a
 * tone contains no words and a harness that failed on that would be wrong.
 */

import { spawn } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';

import { Cdp } from './live-driver.mjs';

const APP = process.env.JOURNEY_BASE_URL ?? 'http://127.0.0.1:1420';
const SERVICE = process.env.SERVICE_BASE_URL ?? 'http://127.0.0.1:8000';
const CHROME =
  process.env.CHROME_PATH ??
  `${process.env.HOME}/.cache/ms-playwright/chromium-1228/chrome-linux64/chrome`;
/** A WAV for the fake microphone to play, instead of Chrome's beeping tone. */
const FAKE_AUDIO = process.env.FAKE_AUDIO ?? null;
/** Words the transcript must contain. Unset means the vendors are not judged. */
const EXPECT_WORDS = (process.env.EXPECT_WORDS ?? '')
  .split(',')
  .map((word) => word.trim().toLowerCase())
  .filter((word) => word !== '');
/** Long enough for two whole five-second chunks and a tail. */
const RECORD_MS = Number(process.env.RECORD_MS ?? 13_000);

/** What the uploader cuts a chunk at: five seconds of 16kHz mono linear16. */
const CHUNK_BYTES = 16_000 * 5 * 2;
const SAMPLE_RATE = 16_000;

const sleep = (ms) => new Promise((done) => setTimeout(done, ms));

const failures = [];
/** Records a failed expectation and carries on, so one run reports every
 *  problem rather than only the first — a second run costs vendor calls. */
function expect(condition, message) {
  if (condition) console.log(`  ok    ${message}`);
  else {
    console.log(`  FAIL  ${message}`);
    failures.push(message);
  }
}

async function api(method, route, body) {
  const response = await fetch(`${SERVICE}${route}`, {
    method,
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok && response.status !== 404) {
    throw new Error(`${method} ${route} answered ${response.status}`);
  }
  const text = await response.text();
  return text === '' ? null : JSON.parse(text);
}

/**
 * A meeting of this run's own, with consent on the record.
 *
 * Made here rather than taken as an argument because the bridge refuses to
 * upload without a confirmed gate — so a harness that borrowed an existing
 * meeting would pass or fail on that meeting's history rather than on the
 * code under test.
 */
async function setUpMeeting() {
  const engagement = await api('POST', '/api/engagements', {
    client_organisation: 'Audio upload harness',
    sector: 'logistics',
    commercial_context: 'tests/e2e/journeys/audio-upload.mjs',
  });
  const meeting = await api('POST', '/api/meetings', {
    engagement_id: engagement.engagement_id,
    capture_mode: 'acoustic',
  });
  await api('POST', `/api/meetings/${meeting.meeting_id}/consent-confirmation`, {
    confirmed_by: 'Audio upload harness',
  });
  return { engagementId: engagement.engagement_id, meetingId: meeting.meeting_id };
}

async function launch() {
  const port = 9500 + Math.floor(Math.random() * 400);
  const profile = mkdtempSync(path.join(tmpdir(), 'elicta-audio-upload-'));
  const chrome = spawn(
    CHROME,
    [
      '--headless=new',
      `--remote-debugging-port=${port}`,
      `--user-data-dir=${profile}`,
      '--no-sandbox',
      '--disable-gpu',
      // The three that matter: a microphone that produces real audio, a
      // permission prompt answered yes, and an audio graph allowed to run with
      // no click to start it.
      '--use-fake-device-for-media-stream',
      ...(FAKE_AUDIO === null ? [] : [`--use-file-for-fake-audio-capture=${FAKE_AUDIO}`]),
      '--use-fake-ui-for-media-stream',
      '--autoplay-policy=no-user-gesture-required',
      '--window-size=900,1200',
      'about:blank',
    ],
    { stdio: 'ignore' },
  );

  let wsUrl = null;
  for (let attempt = 0; attempt < 80 && wsUrl === null; attempt += 1) {
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
    throw new Error(`Chrome did not expose a CDP endpoint (looked for ${CHROME})`);
  }

  const socket = new WebSocket(wsUrl);
  await new Promise((ready) => socket.addEventListener('open', ready));
  const cdp = new Cdp(socket);
  await cdp.send('Page.enable');
  await cdp.send('Runtime.enable');
  // Request bodies are deliberately not collected. A chunk is 200KB of base64
  // and CDP omits `postData` wholesale rather than truncating it once it
  // exceeds this, so reading the sequence from the request meant reading it
  // from a field that is never there. The service reports the sequence it
  // accepted, which is the better witness anyway: it is the hold's own account
  // of where it has got to, and a client that skipped one would be refused.
  await cdp.send('Network.enable', { maxPostDataSize: 128 });

  return {
    cdp,
    close: () => {
      socket.close();
      chrome.kill();
      try {
        rmSync(profile, { recursive: true, force: true });
      } catch {
        // A profile left in the temp directory is litter, not a failed run.
      }
    },
  };
}

/** Clicks the first enabled button whose label contains `text`. */
async function clickButton(cdp, text) {
  const clicked = await cdp.eval(`
    const button = [...document.querySelectorAll('button')]
      .find((b) => b.textContent.includes(${JSON.stringify(text)}) && !b.disabled);
    if (!button) return false;
    button.click();
    return true;
  `);
  if (!clicked) throw new Error(`no enabled button labelled "${text}" on the capture screen`);
}

async function record(cdp, { engagementId, meetingId }) {
  const chunks = [];
  const calls = [];

  cdp.on('Network.requestWillBeSent', ({ requestId, request }) => {
    if (request.url.includes('/audio-chunk')) {
      chunks.push({ requestId, sequence: null });
    } else if (request.url.includes('/record/transcribe') || request.url.includes('/consent-gate')) {
      calls.push({ path: new URL(request.url).pathname, method: request.method, status: null });
    }
  });
  cdp.on('Network.responseReceived', ({ requestId, response }) => {
    const chunk = chunks.find((entry) => entry.requestId === requestId);
    if (chunk) chunk.status = response.status;
    const call = calls.find((entry) => entry.status === null && response.url.includes(entry.path));
    if (call) call.status = response.status;
  });
  cdp.on('Network.loadingFinished', async ({ requestId }) => {
    const chunk = chunks.find((entry) => entry.requestId === requestId);
    if (chunk === undefined) return;
    try {
      const { body } = await cdp.send('Network.getResponseBody', { requestId });
      chunk.body = JSON.parse(body);
      // `next_sequence` is what the hold expects next, so the chunk it just
      // took was the one before it.
      chunk.sequence = chunk.body.next_sequence - 1;
    } catch {
      // Body already evicted; the status is the assertion that matters.
    }
  });

  // Seeded before the app loads: the toolbar reads the chosen engagement and
  // meeting out of `localStorage`, and the bridge reads the same two keys.
  await cdp.send('Page.addScriptToEvaluateOnNewDocument', {
    source: `
      localStorage.setItem('elicta.selection.engagementId', ${JSON.stringify(engagementId)});
      localStorage.setItem('elicta.selection.meetingId', ${JSON.stringify(meetingId)});
    `,
  });
  await cdp.send('Page.navigate', { url: `${APP}/#/capture` });
  await sleep(3500);

  await clickButton(cdp, 'Start recording');
  console.log(`recording ${RECORD_MS / 1000}s of ${FAKE_AUDIO ?? "Chrome's test tone"}...`);
  await sleep(RECORD_MS);
  await clickButton(cdp, 'Stop recording');
  // The tail chunk and the transcribe call both go after the click.
  await sleep(3000);

  return { chunks, calls };
}

async function main() {
  const { engagementId, meetingId } = await setUpMeeting();
  console.log(`meeting ${meetingId} of engagement ${engagementId}, consent confirmed\n`);
  const browser = await launch();

  try {
    const { chunks, calls } = await record(browser.cdp, { engagementId, meetingId });

    console.log('uploads');
    for (const chunk of chunks) {
      const bytes = chunk.body ? `  received_bytes=${chunk.body.received_bytes}` : '';
      console.log(`  chunk ${chunk.sequence} → ${chunk.status}${bytes}`);
    }
    for (const call of calls) console.log(`  ${call.method} ${call.path} → ${call.status}`);

    console.log('\nassertions');
    expect(chunks.length > 0, 'the recording uploaded at least one chunk');
    expect(
      chunks.every((chunk) => chunk.status === 202),
      'every chunk was accepted',
    );
    expect(
      chunks.length > 0 && chunks.every((chunk, index) => chunk.sequence === index),
      'the service accepted them numbered from zero with no gaps',
    );

    // The last accepted chunk knows the total, which is what the seconds are
    // checked against — a chunk count alone cannot tell 16kHz from 48kHz.
    const total = chunks.filter((chunk) => chunk.body).at(-1)?.body.received_bytes ?? 0;
    const seconds = total / 2 / SAMPLE_RATE;
    const expected = RECORD_MS / 1000;
    console.log(`  (${total} bytes = ${seconds.toFixed(1)}s of 16kHz mono, recorded ${expected}s)`);
    expect(
      seconds > expected * 0.85 && seconds < expected * 1.05,
      "the bytes account for the seconds recorded (±15%)",
    );
    expect(
      chunks.slice(0, -1).every((chunk) => (chunk.body?.received_bytes ?? 0) % CHUNK_BYTES === 0),
      'every chunk but the last was a whole five seconds',
    );
    expect(
      calls.some((call) => call.path.endsWith('/record/transcribe') && call.status === 202),
      'stopping asked the service for a transcript',
    );

    // The vendors take a moment, and are reported whether or not they are
    // judged: a run against a tone has nothing to transcribe, and saying so is
    // information rather than a failure.
    await sleep(15_000);
    const transcripts = (await api('GET', `/api/sessions/${meetingId}/record-path-transcript`)) ?? [];
    console.log('\ntranscripts');
    for (const transcript of transcripts) {
      console.log(`  [${transcript.engine}] ${transcript.status}: ${transcript.text || transcript.error || ''}`.slice(0, 200));
    }
    if (EXPECT_WORDS.length > 0) {
      const said = transcripts.map((transcript) => (transcript.text ?? '').toLowerCase());
      for (const word of EXPECT_WORDS) {
        expect(
          said.some((text) => text.includes(word)),
          `some engine heard "${word}"`,
        );
      }
    }

    const destruction = await api('GET', `/api/sessions/${meetingId}/audio-destruction`);
    console.log(`\naudio destruction: ${destruction?.status ?? 'none recorded'}`);
  } finally {
    browser.close();
    // Soft, like every deletion here: the engagement stops loading and
    // listing, and the meeting's records stay where they are.
    await api('DELETE', `/api/engagements/${engagementId}`).catch(() => undefined);
    console.log(`cleaned up ${engagementId}`);
  }

  if (failures.length > 0) {
    console.error(`\n${failures.length} assertion(s) failed`);
    process.exit(1);
  }
  console.log('\nall assertions passed');
}

await main();
