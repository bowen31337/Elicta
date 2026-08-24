#!/usr/bin/env node
/**
 * Watches a nudge arrive *on the panel*, in a real browser, for one meeting.
 *
 * `nudge-probe.mjs` next door answers "did the service raise one?" — it posts
 * to the gate and reads the session stream itself. That leaves the last hop
 * unmeasured, and it is the hop the operator sees: a nudge can be raised,
 * carried on the stream, and never reach the screen, because the panel is
 * pointed at another meeting or never opened a connection at all. This runs
 * the whole path: it opens the app, chooses the meeting the way the toolbar
 * does, posts one vague line, and waits for that question to appear in the
 * panel's own markup.
 *
 * Usage:
 *   node tests/e2e/journeys/panel-nudge.mjs 37            # or meeting-37
 *   node tests/e2e/journeys/panel-nudge.mjs               # newest meeting
 *   node tests/e2e/journeys/panel-nudge.mjs 37 --wait     # sit out the rate limit
 *   node tests/e2e/journeys/panel-nudge.mjs 37 --act      # tap Park it and Go deeper
 *   node tests/e2e/journeys/panel-nudge.mjs 37 --quiet-check   # a line that must NOT fire
 *
 *   --app  <url>   the panel               (default: probed, http then https)
 *   --api  <url>   the service             (default: $SERVICE, else :8000)
 *   --out  <dir>   where screenshots go    (default: ./panel-nudge-out)
 *   --line "..."   say this instead of the built-in vague line
 *   --timeout <s>  how long to wait for the screen to change (default: 20)
 *
 * **The panel is connected before the line is posted, on purpose.** Reloading
 * afterwards would prove only that the backlog replays, which it does even
 * when live delivery is broken. Everything here is measured against a
 * connection that was already open.
 *
 * **A nudge already on the meeting would pass a lazy check.** So the question
 * is bound to identity: the POST answers with a `nudge_id`, that id's question
 * is read off the stream, and the panel is required to show *that* text — not
 * merely something non-empty where an empty state used to be.
 *
 * **No audio, nothing billed.** Same intake a recogniser posts to, so the
 * gate, the bank, the rate limit, the stream and the screen are all exercised;
 * turning sound into words is not. For that, `audio-upload.mjs`.
 *
 * **One nudge a minute.** A line that triggers and does not surface is the
 * limit working (FR-5.8), not the panel failing — that is reported as such,
 * and `--wait` sits out the sixty seconds and sends again.
 */

import { mkdirSync, writeFileSync } from 'node:fs';

import { launchBrowser, sleep } from './live-driver.mjs';

const argv = process.argv.slice(2);
const VALUE_FLAGS = new Set(['app', 'api', 'out', 'line', 'timeout']);
const has = (name) => argv.includes(`--${name}`);
const arg = (name, fallback) => {
  const at = argv.indexOf(`--${name}`);
  return at === -1 ? fallback : argv[at + 1];
};
const positional = [];
for (let index = 0; index < argv.length; index += 1) {
  const item = argv[index];
  if (!item.startsWith('--')) {
    positional.push(item);
    continue;
  }
  if (VALUE_FLAGS.has(item.slice(2))) index += 1;
}

const API = arg('api', process.env.SERVICE ?? 'http://127.0.0.1:8000');
const OUT = arg('out', './panel-nudge-out');
const WAIT_MS = Number(arg('timeout', '20')) * 1000;
const VIEWPORT = { width: 1280, height: 900, scale: 2 };

/** Vague enough that the gate owes a question; the sibling harness sends the
 *  same line, so the two tools disagreeing means the browser, not the gate. */
const VAGUE = 'The new dashboard just has to be fast.';
/** Ordinary, and a near-miss on purpose: a gate matching substrings rather
 *  than whole words fires on "fastener", and a false fire is an interruption
 *  in front of a client. */
const ORDINARY = 'Tighten the fastener on the loading bay door before each run.';

const LINE = arg('line', has('quiet-check') ? ORDINARY : VAGUE);

// A self-signed certificate is what `start.sh --https` serves, and Node
// refuses it by default — scoped to the addresses this tool was pointed at
// rather than set globally for the process's whole life elsewhere.
if (API.startsWith('https:')) process.env.NODE_TLS_REJECT_UNAUTHORIZED = '0';

const checks = [];
function check(name, ok, detail) {
  checks.push({ name, ok: Boolean(ok), detail: String(detail ?? '') });
  console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${name}`);
  if (!ok && detail) console.log(`        ${String(detail).slice(0, 300)}`);
}

async function api(method, path, body) {
  const response = await fetch(`${API}${path}`, {
    method,
    headers: body === undefined ? undefined : { 'content-type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await response.text();
  let json = null;
  try {
    json = JSON.parse(text);
  } catch {
    json = null;
  }
  return { status: response.status, json, text };
}

/**
 * Which panel to drive.
 *
 * The dev server answers on one port under either scheme — `start.sh --https`
 * serves TLS on the same 1420 — and pointing a browser at the wrong one fails
 * as a blank page rather than as an error. So when nobody said, both are
 * tried and the one that answers is named in the output.
 */
async function resolveApp() {
  const named = arg('app', process.env.JOURNEY_BASE_URL ?? null);
  const candidates = named ? [named] : ['http://127.0.0.1:1420', 'https://127.0.0.1:1420'];
  for (const candidate of candidates) {
    if (candidate.startsWith('https:')) process.env.NODE_TLS_REJECT_UNAUTHORIZED = '0';
    try {
      const response = await fetch(candidate, { signal: AbortSignal.timeout(4000) });
      if (response.status < 500) return candidate;
    } catch {
      // try the next scheme
    }
  }
  throw new Error(
    `nothing answers on ${candidates.join(' or ')}. Start the panel (./start.sh, or\n` +
      '--https for TLS) or name it with --app.',
  );
}

/** Every meeting, with the engagement that owns it — the picker needs both. */
async function allMeetings() {
  const engagements = await api('GET', '/api/engagements');
  if (engagements.status !== 200) {
    throw new Error(`the service answered ${engagements.status} for its engagements`);
  }
  const rows = [];
  for (const engagement of engagements.json.items ?? []) {
    const meetings = await api('GET', `/api/engagements/${engagement.engagement_id}/meetings`);
    for (const meeting of meetings.json?.meetings ?? []) {
      rows.push({ id: meeting.meeting_id, engagement: engagement.engagement_id });
    }
  }
  // Ids are issued in order, so the highest number is the newest. Compared as
  // numbers rather than as text, or meeting-9 outranks meeting-40.
  return rows.sort((a, b) => Number(a.id.split('-').pop()) - Number(b.id.split('-').pop()));
}

/**
 * Everything the panel's connection carries right now.
 *
 * Read to the first comment frame — the stream's own mark for "that is all
 * there is for now" — rather than to an end that will not come for minutes.
 */
async function streamFrames(meetingId) {
  const response = await fetch(`${API}/api/meetings/${meetingId}/session/stream`);
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let text = '';
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    text += decoder.decode(value, { stream: true });
    const mark = text.search(/^:/m);
    if (mark !== -1) {
      text = text.slice(0, mark);
      break;
    }
  }
  await reader.cancel().catch(() => {});

  const frames = [];
  let name = null;
  for (const line of text.split('\n')) {
    if (line.startsWith('event: ')) name = line.slice(7);
    else if (line.startsWith('data: ') && name) {
      frames.push([name, JSON.parse(line.slice(6))]);
      name = null;
    }
  }
  return frames;
}

async function nudgeById(meetingId, nudgeId) {
  const frames = await streamFrames(meetingId);
  for (const [name, frame] of frames) {
    if (name === 'nudge' && frame.id === nudgeId) return frame;
  }
  return null;
}

/** What the panel is showing: the active question, or the empty state. */
async function panelReads(cdp) {
  return cdp.eval(
    `const q = document.querySelector('.nudge-stack__question');
     if (q) return { question: q.textContent.trim(),
                     stub: document.querySelector('.nudge-stack__stub')?.textContent.trim() ?? null,
                     reason: document.querySelector('.nudge-stack__reason')?.textContent.trim() ?? null,
                     history: document.querySelectorAll('.nudge-stack__history-item').length };
     const empty = document.querySelector('.nudge-stack__empty');
     return { question: null, empty: empty ? empty.textContent.trim() : null,
              history: document.querySelectorAll('.nudge-stack__history-item').length }`,
  );
}

/**
 * Polls until the panel shows this question *and* it is the new one.
 *
 * Text alone is not identity. Two nudges on the same trigger can carry the
 * same wording — a run raised `nudge-2` and `nudge-3` with the same sentence —
 * so a text match against a card that was already on screen proves nothing.
 * When something was already showing, the card that arrives pushes it into
 * history (`route.tsx` keeps the previous active nudge there), and that growth
 * is the evidence a new one landed. Nothing in the markup carries the id.
 */
async function waitForQuestion(cdp, question, timeoutMs, before) {
  const deadline = Date.now() + timeoutMs;
  const arrived = (reading) =>
    reading.question !== null &&
    reading.question === question.trim() &&
    (before.question === null || reading.history > before.history);
  let last = null;
  for (;;) {
    last = await panelReads(cdp);
    if (arrived(last)) return { ...last, matched: true };
    if (Date.now() >= deadline) return { ...last, matched: false };
    await sleep(400);
  }
}

async function shot(cdp, dir, label) {
  const { data } = await cdp.send('Page.captureScreenshot', { format: 'png' });
  const name = `${label}.png`;
  writeFileSync(`${dir}/${name}`, Buffer.from(data, 'base64'));
  console.log(`  … ${dir}/${name}`);
}

async function clickChip(cdp, label) {
  const clicked = await cdp.eval(
    `const el = [...document.querySelectorAll('button')]
       .find(b => b.textContent.trim() === ${JSON.stringify(label)} && !b.disabled);
     if (el) { el.click(); return true; } return false`,
  );
  await sleep(1200);
  return clicked;
}

async function main() {
  const APP = await resolveApp();

  const meetings = await allMeetings();
  if (meetings.length === 0) throw new Error('this service has no meetings to speak to');
  // "37" is what a person says; "meeting-37" is what the service calls it.
  const asked = positional[0] ?? null;
  const wanted = asked === null ? null : /^\d+$/.test(asked) ? `meeting-${asked}` : asked;
  const meeting = wanted === null ? meetings[meetings.length - 1] : meetings.find((row) => row.id === wanted);
  if (!meeting) {
    throw new Error(
      `${wanted} is not a meeting on this service. It has: ` +
        `${meetings.map((row) => row.id).join(', ')}`,
    );
  }

  mkdirSync(OUT, { recursive: true });
  console.log(`meeting: ${meeting.id}${wanted === null ? '   (newest)' : ''}  of ${meeting.engagement}`);
  console.log(`panel:   ${APP}`);
  console.log(`service: ${API}`);
  console.log(`shots:   ${OUT}\n`);

  const { cdp, close } = await launchBrowser({
    ...VIEWPORT,
    // `start.sh --https` serves a certificate signed by nobody, and Chrome
    // stops at its own interstitial rather than loading the panel.
    flags: APP.startsWith('https:') ? ['--ignore-certificate-errors'] : [],
  });

  /** Every API call the *page* made that failed — the panel's own round trips,
   *  which a screenshot cannot show and which is where Park it used to 404. */
  const failedRequests = [];
  cdp.on('Network.responseReceived', ({ response }) => {
    if (response.status >= 400) failedRequests.push(`${response.status} ${response.url}`);
  });
  /**
   * Every URL the page asked for, watched from the browser rather than from
   * inside the page. `performance.getEntriesByType('resource')` does not list
   * an `EventSource` connection, and the session stream is one — asking the
   * page produced "the panel never opened the stream" in the same run in
   * which the panel visibly received a nudge over it.
   */
  const requested = [];
  cdp.on('Network.requestWillBeSent', ({ request }) => requested.push(request.url));

  try {
    await cdp.send('Page.navigate', { url: `${APP}/#/panel` });
    await sleep(3500);

    // The operator's own path: the toolbar picker, not a write to localStorage.
    // React owns a <select>'s value, so the native setter has to be called
    // before the change event or React puts the old value straight back.
    const setSelect = (selector, value) =>
      cdp.eval(
        `const el = document.querySelector(${JSON.stringify(selector)});
         if (!el) return 'no-picker';
         const setter = Object.getOwnPropertyDescriptor(
           window.HTMLSelectElement.prototype, 'value').set;
         setter.call(el, ${JSON.stringify(value)});
         el.dispatchEvent(new Event('change', { bubbles: true }));
         return el.value`,
      );
    await setSelect('#current-engagement', meeting.engagement);
    await sleep(1500);
    const chose = await setSelect('#current-meeting', meeting.id);
    if (chose !== meeting.id) {
      // The picker lists what the service reports; if it cannot hold this id,
      // say so rather than testing a panel quietly pointed somewhere else.
      throw new Error(
        `the toolbar picker would not take ${meeting.id} (it reads ${JSON.stringify(chose)}).`,
      );
    }
    await sleep(2000);

    check('the panel renders', (await cdp.eval(`return document.querySelectorAll('main.panel').length`)) === 1,
      'no <main class="panel"> on the page — is the app on the panel screen?');

    // "Connected, with nothing to send" and "not connected at all" look
    // identical on screen. So ask whether the connection was opened, and for
    // this meeting: pointing the panel at one meeting while posting to another
    // is the likeliest way to conclude wrongly that nothing works.
    const streamUrl = `/meetings/${meeting.id}/session/stream`;
    const streamOpened = requested.some((url) => url.includes(streamUrl));
    check(`the panel opened ${meeting.id}'s live session stream`, streamOpened,
      `nothing requested ${streamUrl} — the picker may not have taken. The panel ` +
      `asked for: ${requested.filter((url) => url.includes('/api/')).join(', ') || 'nothing'}`);

    const before = await panelReads(cdp);
    console.log(`\n  the panel currently reads: ${JSON.stringify(before.question ?? before.empty)}`);
    // Two of the four chips — `Asked it` and `What am I missing?` — are gated
    // on coverage rather than on a nudge, so they stay unrendered on a meeting
    // whose session carries none. Said out loud, because their absence beside
    // a working nudge reads as a broken dock and is not one.
    const meter = await cdp.eval(
      `const m = document.querySelector('.meter'); return m ? m.textContent.trim() : null`);
    if (meter === null || !/\d/.test(meter)) {
      console.log(`  the coverage meter reads ${JSON.stringify(meter)} — nothing has written`);
      console.log('  coverage for this session, so the two coverage-gated chips stay away.');
    }
    await shot(cdp, OUT, '01-before');

    // ---- say the line -------------------------------------------------
    console.log(`\n"${LINE}"`);
    let said = await api('POST', `/api/meetings/${meeting.id}/live/utterance`, { text: LINE });
    if (said.status !== 202) {
      check('the service accepts the utterance', false, `${said.status} ${said.text.slice(0, 200)}`);
    } else if (said.json.triggered && !said.json.surfaced && has('wait')) {
      console.log('  · triggered, held back by the one-a-minute limit — waiting 61s\n');
      await sleep(61_000);
      said = await api('POST', `/api/meetings/${meeting.id}/live/utterance`, { text: LINE });
    }
    const { triggered, trigger_reason: reason, surfaced, nudge_id: nudgeId } = said.json ?? {};
    console.log(
      `  gate: ${triggered ? `triggered (${reason})` : 'nothing to ask about'}` +
        `${triggered ? (surfaced ? `, surfaced as ${nudgeId}` : ', held back by the one-a-minute limit') : ''}`,
    );

    // ---- the quiet case: nothing must appear --------------------------
    if (has('quiet-check')) {
      check('an ordinary line raises nothing', triggered === false,
        `the gate fired on an ordinary sentence (${reason}) — a false fire is an ` +
        'interruption in front of a client');
      await sleep(3000);
      const after = await panelReads(cdp);
      check('the panel did not change',
        (after.question ?? null) === (before.question ?? null) && after.history === before.history,
        `the panel now reads ${JSON.stringify(after.question ?? after.empty)}`);
      await shot(cdp, OUT, '02-after-quiet');
    } else {
      check('the line earns a question', triggered === true,
        'the gate found nothing vague in it — try --line "..." with something vaguer');
      if (triggered && !surfaced) {
        check('a question is surfaced', false,
          'triggered but held back by the one-a-minute rate limit. That is FR-5.8 working, ' +
          'not the panel failing — re-run with --wait to sit it out.');
      } else if (surfaced) {
        // Identity, not "something non-empty": a nudge already on this meeting
        // would satisfy any looser check while proving nothing arrived now.
        const raised = await nudgeById(meeting.id, nudgeId);
        check('the stream carries the nudge the service says it raised', raised !== null,
          `${nudgeId} is not on ${meeting.id}'s session stream`);

        if (raised) {
          console.log(`\n  raised: ${raised.stub}\n          ${raised.question}\n          ${raised.trigger_reason}`);
          const shown = await waitForQuestion(cdp, raised.question, WAIT_MS, before);
          check('the panel shows that question, on the connection it already had',
            shown.matched,
            `after ${WAIT_MS / 1000}s the panel reads ` +
            `${JSON.stringify(shown.question ?? shown.empty)}, with ${shown.history} ` +
            `in history (it held ${before.history})`);
        }
        await shot(cdp, OUT, '02-after');

        // The chips are gated on there being an active nudge, so they are part
        // of the same arrival — and they were rendering and 404ing until
        // recently, which no screenshot would have shown.
        if (has('act')) {
          const at = failedRequests.length;
          for (const label of ['Park it', 'Go deeper']) {
            const clicked = await clickChip(cdp, label);
            check(`the ${label} chip is there to tap`, clicked === true, 'no enabled button with that label');
          }
          await sleep(1500);
          const broke = failedRequests.slice(at);
          check('tapping the chips reaches the service', broke.length === 0, broke.join('; '));
          await shot(cdp, OUT, '03-after-chips');
        }
      }
    }

    const pageFailures = failedRequests.filter((row) => row.includes('/api/'));
    if (pageFailures.length > 0) {
      console.log(`\n  the page's own API calls that failed:\n    ${pageFailures.join('\n    ')}`);
    }
  } finally {
    close();
  }

  const failed = checks.filter((row) => !row.ok);
  console.log(`\n${checks.length - failed.length}/${checks.length} checks passed`);
  if (failed.length > 0) process.exitCode = 1;
}

main().catch((cause) => {
  console.error(String(cause?.message ?? cause));
  process.exit(1);
});
