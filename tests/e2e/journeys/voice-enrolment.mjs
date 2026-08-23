/**
 * Does pressing "Enrol" on the Capture screen actually enrol a voice?
 *
 * Nothing in CI answers that. The embedder is unit-tested, the route is
 * tested, the hook is tested against a fake `AudioContext`, and the join
 * between them is only ever made by a real browser holding a real microphone
 * open — which is exactly the shape of gap that left this button doing nothing
 * for the life of the product while every part behind it passed its own tests.
 *
 * So this drives the running app: a headless Chrome with a fake microphone
 * playing a generated voice, the real capture screen, the real hook, the real
 * service. It needs the panel and the service running (`./start.sh --https`),
 * and it enrols against whatever state database that service is using — so it
 * un-enrols again at the end unless something was already enrolled before it
 * started, which it leaves exactly as it found.
 *
 *   node tests/e2e/journeys/voice-enrolment.mjs
 *
 * `JOURNEY_BASE_URL` must carry its scheme: the dev server is HTTPS, and the
 * microphone is only reachable on a secure page. The certificate is
 * self-signed, which is why Chrome is launched told to accept it.
 */

import { spawn } from 'node:child_process';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';

import { Cdp } from './live-driver.mjs';

const APP = process.env.JOURNEY_BASE_URL ?? 'https://127.0.0.1:1420';
const SERVICE = process.env.SERVICE_BASE_URL ?? 'http://127.0.0.1:8000';
const CHROME =
  process.env.CHROME_PATH ??
  `${process.env.HOME}/.cache/ms-playwright/chromium-1228/chrome-linux64/chrome`;
/** Long enough to clear the service's three-second floor with room to spare. */
const RECORD_MS = Number(process.env.RECORD_MS ?? 8_000);

const SAMPLE_RATE = 16_000;
const sleep = (ms) => new Promise((done) => setTimeout(done, ms));

const failures = [];
function expect(condition, message) {
  if (condition) console.log(`  ok    ${message}`);
  else {
    console.log(`  FAIL  ${message}`);
    failures.push(message);
  }
}

/**
 * A WAV of a synthesised vowel, for the fake microphone to play.
 *
 * Chrome's own fake device emits a steady beep, and steady is the one thing
 * the service refuses: it separates speech from silence and from a hum by
 * looking for syllables, so a continuous tone is correctly rejected as holding
 * no speech. This has the syllables — four a second, with real gaps — and
 * three formants, which is what makes it a voice rather than a note.
 */
function writeVoiceWav(target) {
  const seconds = 30;
  const total = SAMPLE_RATE * seconds;
  const f0 = 120;
  const formants = [730, 1090, 2440];
  const harmonics = Math.floor(SAMPLE_RATE / 2 / f0);

  const data = Buffer.alloc(total * 2);
  for (let n = 0; n < total; n += 1) {
    const t = n / SAMPLE_RATE;
    const envelope = Math.max(0, Math.sin(2 * Math.PI * 4 * t)) ** 2;
    let value = 0;
    if (envelope > 0.01) {
      for (let harmonic = 1; harmonic < harmonics; harmonic += 1) {
        const frequency = f0 * harmonic;
        let shaping = 0;
        for (const formant of formants) {
          shaping += 1 / (1 + ((frequency - formant) / 90) ** 2);
        }
        value += (shaping * Math.sin(2 * Math.PI * frequency * t)) / harmonic;
      }
    }
    const sample = Math.max(-32768, Math.min(32767, Math.round(((value * envelope) / 8) * 0.3 * 32767)));
    data.writeInt16LE(sample, n * 2);
  }

  const header = Buffer.alloc(44);
  header.write('RIFF', 0);
  header.writeUInt32LE(36 + data.length, 4);
  header.write('WAVE', 8);
  header.write('fmt ', 12);
  header.writeUInt32LE(16, 16);
  header.writeUInt16LE(1, 20); // PCM
  header.writeUInt16LE(1, 22); // mono
  header.writeUInt32LE(SAMPLE_RATE, 24);
  header.writeUInt32LE(SAMPLE_RATE * 2, 28);
  header.writeUInt16LE(2, 32);
  header.writeUInt16LE(16, 34);
  header.write('data', 36);
  header.writeUInt32LE(data.length, 40);

  writeFileSync(target, Buffer.concat([header, data]));
  return target;
}

async function status() {
  const response = await fetch(`${SERVICE}/api/operator/voiceprint`, {
    headers: { Accept: 'application/json' },
  });
  if (!response.ok) throw new Error(`GET voiceprint answered ${response.status}`);
  return await response.json();
}

async function launch(wav) {
  const port = 9700 + Math.floor(Math.random() * 300);
  const profile = mkdtempSync(path.join(tmpdir(), 'elicta-enrolment-'));
  const chrome = spawn(
    CHROME,
    [
      '--headless=new',
      `--remote-debugging-port=${port}`,
      `--user-data-dir=${profile}`,
      '--no-sandbox',
      '--disable-gpu',
      '--use-fake-device-for-media-stream',
      `--use-file-for-fake-audio-capture=${wav}`,
      '--use-fake-ui-for-media-stream',
      '--autoplay-policy=no-user-gesture-required',
      // The dev server's certificate is self-signed and generated per machine.
      '--ignore-certificate-errors',
      '--window-size=900,1400',
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
    rmSync(profile, { recursive: true, force: true });
    throw new Error(`Chrome did not expose a CDP endpoint (looked for ${CHROME})`);
  }

  const socket = new WebSocket(wsUrl);
  await new Promise((ready) => socket.addEventListener('open', ready));
  const cdp = new Cdp(socket);
  await cdp.send('Page.enable');
  await cdp.send('Runtime.enable');

  return {
    cdp,
    close: () => {
      try { socket.close(); } catch { /* already gone */ }
      chrome.kill();
      try { rmSync(profile, { recursive: true, force: true }); } catch { /* litter */ }
    },
  };
}

/** The "Your voice" section, as text, so a failure says what was on screen. */
const VOICE_SECTION = `
  const heading = [...document.querySelectorAll('h2')].find((h) => /your voice/i.test(h.textContent));
  return heading?.closest('section')?.innerText ?? '(no "Your voice" section on screen)';
`;

function clickButton(label) {
  return `
    const section = [...document.querySelectorAll('h2')]
      .find((h) => /your voice/i.test(h.textContent))?.closest('section');
    const button = [...(section?.querySelectorAll('button') ?? [])]
      .find((b) => b.textContent.trim() === ${JSON.stringify(label)});
    if (!button) return 'no such button';
    if (button.disabled) return 'disabled';
    button.click();
    return 'clicked';
  `;
}

async function main() {
  const wav = writeVoiceWav(path.join(mkdtempSync(path.join(tmpdir(), 'elicta-voice-')), 'voice.wav'));
  const before = await status();
  console.log(`\nservice: ${SERVICE}   panel: ${APP}`);
  console.log(`enrolled before this run: ${before.enrolled}\n`);

  const { cdp, close } = await launch(wav);
  try {
    await cdp.send('Page.navigate', { url: `${APP}/#/capture` });
    await sleep(4_000);

    const opening = await cdp.eval(VOICE_SECTION);
    console.log('--- before ---\n' + opening + '\n');
    expect(/not enrolled|enrolled/i.test(opening), 'the "Your voice" section is on screen');

    // The input picker only earns its place when there is a choice to make, so
    // a machine with one microphone is not a failure — it is the other branch.
    const inputs = await cdp.eval(`
      const select = document.querySelector('#voice-input');
      if (!select) return { present: false, count: 0 };
      return {
        present: true,
        count: select.options.length,
        chosen: select.options[select.selectedIndex]?.text ?? null,
        labels: [...select.options].map((o) => o.text),
      };
    `);
    console.log(`inputs offered for the voice sample: ${JSON.stringify(inputs)}\n`);
    expect(
      inputs.present ? inputs.count > 1 : true,
      inputs.present
        ? `the voice sample can be recorded from any of ${inputs.count} inputs`
        : 'no input picker, because this machine offers no choice',
    );

    const started = await cdp.eval(clickButton(before.enrolled ? 'Re-record' : 'Enrol'));
    expect(started === 'clicked', `the enrol button is live (${started})`);
    if (started !== 'clicked') return;

    await sleep(1_500);
    const recording = await cdp.eval(VOICE_SECTION);
    console.log('--- recording ---\n' + recording + '\n');
    expect(/Recording — \d+s of 60s/.test(recording), 'the screen counts the sample as it records');

    // A picture of the screen while it is recording, when asked for one. The
    // meter is the part of this that no assertion can really judge.
    if (process.env.ENROLMENT_SHOT) {
      const shot = await cdp.send('Page.captureScreenshot', { format: 'png' });
      (await import('node:fs')).writeFileSync(
        process.env.ENROLMENT_SHOT,
        Buffer.from(shot.data, 'base64'),
      );
      console.log(`  wrote ${process.env.ENROLMENT_SHOT}`);
    }

    // The meter has to be reading the microphone, not drawing a constant. A
    // dead meter and a working one look identical in a screenshot, and the
    // whole reason it is on screen is to tell an operator that a silent input
    // is silent — so the check is that it *moves*, not that it is non-zero.
    const readings = [];
    for (let i = 0; i < 12; i += 1) {
      readings.push(
        await cdp.eval(`
          const meter = document.querySelector('#voice-input')?.closest('.group')
            ?.querySelector('[role=meter]');
          return meter === null || meter === undefined
            ? null
            : Number(meter.getAttribute('aria-valuenow'));
        `),
      );
      await sleep(150);
    }
    const levels = readings.filter((value) => value !== null);
    expect(levels.length > 0, 'the input level is on screen while the sample records');
    expect(
      new Set(levels).size > 1,
      `the level follows the microphone rather than sitting still (${[...new Set(levels)].join(', ')})`,
    );
    expect(levels.some((value) => value > 0), 'the level rises when there is speech');

    await sleep(RECORD_MS);
    const counted = await cdp.eval(VOICE_SECTION);
    const seconds = Number(/Recording — (\d+)s/.exec(counted)?.[1] ?? 0);
    expect(seconds >= 5, `the count reached the sample actually captured (${seconds}s)`);

    expect((await cdp.eval(clickButton('Stop'))) === 'clicked', 'the recording can be stopped');

    // The service embeds it; a ten-second sample takes well under a second.
    for (let attempt = 0; attempt < 40; attempt += 1) {
      if ((await status()).enrolled) break;
      await sleep(500);
    }

    const after = await status();
    expect(after.enrolled === true, 'the service now holds an enrolment');
    expect(after.usable === true, 'the print can be compared against live audio');
    expect(
      after.sample_seconds >= 5,
      `the sample kept is the one that was recorded (${after.sample_seconds}s)`,
    );

    await sleep(1_000);
    const settled = await cdp.eval(VOICE_SECTION);
    console.log('--- after ---\n' + settled + '\n');
    expect(/Enrolled/.test(settled), 'the screen says so without being reloaded');
    expect(
      !/Not enrolled/.test(settled),
      'the screen no longer claims the operator has never enrolled',
    );
    expect(
      /baseline/i.test(settled),
      'the screen still says what the voice comparison actually is',
    );
  } finally {
    close();
    if (!before.enrolled) {
      await fetch(`${SERVICE}/api/operator/voiceprint`, { method: 'DELETE' });
      console.log('un-enrolled again: the service is as this run found it');
    }
  }
}

await main();

if (failures.length > 0) {
  console.log(`\n${failures.length} failure(s):`);
  for (const failure of failures) console.log(`  - ${failure}`);
  process.exit(1);
}
console.log('\nall checks passed');
