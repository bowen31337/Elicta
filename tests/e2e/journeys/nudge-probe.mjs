#!/usr/bin/env node
/**
 * Raises nudges on a meeting, so the panel can be watched doing its job.
 *
 * The live path needs a room, a microphone and something worth saying, which
 * makes "does the panel still work?" an expensive question to ask. This asks
 * it in a second: it speaks to the gate directly, over the same route a
 * recogniser uses, and then reads back what the panel's own connection would
 * carry.
 *
 * Usage:
 *   node tests/e2e/journeys/nudge-probe.mjs                  # newest meeting, one vague line
 *   node tests/e2e/journeys/nudge-probe.mjs meeting-42       # that meeting
 *   node tests/e2e/journeys/nudge-probe.mjs --listen         # watch, say nothing
 *   node tests/e2e/journeys/nudge-probe.mjs --quiet-check    # lines that must NOT fire
 *   node tests/e2e/journeys/nudge-probe.mjs --script         # the whole script, paced
 *   node tests/e2e/journeys/nudge-probe.mjs --list          # meetings, newest last
 *
 *   SERVICE=http://127.0.0.1:8000  the service to talk to
 *
 * **Which meeting.** The panel and the capture screen read their meeting from
 * the browser's own storage, on the machine running the browser — which this
 * cannot see. Neither can the service: a meeting's state stays `planned` while
 * it is being recorded, so nothing on the wire says which one is live. So the
 * meeting is named on the command line, `--list` shows what there is to name,
 * and without one the newest is used and printed. Check the printed id against
 * the toolbar picker before believing a quiet panel: pointing this at one
 * meeting while watching another is the likeliest way to conclude wrongly that
 * nothing works.
 *
 * **No audio is involved, and nothing is billed.** This posts finalised text
 * to the same intake a recogniser posts to, so it exercises the gate, the bank
 * selection, the rate limit and the delivery to the panel — everything except
 * turning sound into words. When the question is whether speech is *heard*,
 * this is the wrong tool and `audio-upload.mjs` is the right one.
 *
 * **One nudge a minute.** The service surfaces at most one per sixty seconds
 * however many lines pass the gate, so `--script` waits between them. Sending
 * five vague lines quickly and receiving one nudge is the rate limit working,
 * not the gate failing — which is why every line's answer is printed, not just
 * the ones that surfaced.
 */

const SERVICE = process.env.SERVICE ?? 'http://127.0.0.1:8000';
const args = process.argv.slice(2);
const flags = new Set(args.filter((arg) => arg.startsWith('--')));
const named = args.find((arg) => !arg.startsWith('--')) ?? null;

/** Lines that must raise a question, one per category the gate knows. */
const VAGUE = [
  'The new dashboard just has to be fast.',
  'We move a lot of pallets through Derby on a Friday.',
  'We need the depot cut over soon.',
  'Typically the marshalling area clears by ten, but it depends.',
];

/**
 * Lines that must raise nothing.
 *
 * Two of them are near-misses on purpose: a gate matching substrings rather
 * than whole words fires on "fastener" and "somebody", and each false fire is
 * an interruption in front of a client.
 */
const ORDINARY = [
  'We run three hundred and fifty consignments a day out of Wolverhampton.',
  'Tighten the fastener on the loading bay door before each run.',
  'Somebody from the depot signs off the manifest at six.',
];

const sleep = (ms) => new Promise((done) => setTimeout(done, ms));

async function api(method, path, body) {
  const response = await fetch(`${SERVICE}${path}`, {
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

/** Every meeting, oldest first, with the engagement it belongs to. */
async function allMeetings() {
  const engagements = await api('GET', '/api/engagements');
  if (engagements.status !== 200) {
    throw new Error(`the service answered ${engagements.status} for its engagements`);
  }
  const rows = [];
  for (const engagement of engagements.json.items ?? []) {
    const meetings = await api('GET', `/api/engagements/${engagement.engagement_id}/meetings`);
    for (const meeting of meetings.json?.meetings ?? []) {
      rows.push({
        id: meeting.meeting_id,
        engagement: engagement.engagement_id,
        client: engagement.client_organisation,
        mode: meeting.capture_mode,
      });
    }
  }
  // Ids are issued in order, so the highest number is the newest. Compared as
  // numbers rather than as text, or meeting-9 outranks meeting-40.
  return rows.sort((a, b) => Number(a.id.split('-').pop()) - Number(b.id.split('-').pop()));
}

/** The most recently created meeting, across every engagement. */
async function newestMeeting() {
  const engagements = await api('GET', '/api/engagements');
  if (engagements.status !== 200) {
    throw new Error(`the service answered ${engagements.status} for its engagements`);
  }
  const found = [];
  for (const engagement of engagements.json.items ?? []) {
    const meetings = await api('GET', `/api/engagements/${engagement.engagement_id}/meetings`);
    for (const meeting of meetings.json?.meetings ?? []) found.push(meeting.meeting_id);
  }
  if (found.length === 0) throw new Error('this service has no meetings to speak to');
  // Ids are issued in order, so the highest number is the newest. Compared as
  // numbers rather than as text, or meeting-9 outranks meeting-40.
  return found.sort((a, b) => Number(a.split('-').pop()) - Number(b.split('-').pop())).pop();
}

/**
 * Everything the panel's connection carries right now.
 *
 * The connection is held open for the length of a meeting, so this reads up to
 * the first comment frame — the stream's own mark for "that is all there is
 * for now" — rather than waiting for an end that will not come for minutes.
 */
async function panelFrames(meetingId) {
  const response = await fetch(`${SERVICE}/api/meetings/${meetingId}/session/stream`);
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

async function say(meetingId, text) {
  const said = await api('POST', `/api/meetings/${meetingId}/live/utterance`, { text });
  if (said.status !== 202) {
    console.log(`  ✗ the service answered ${said.status}: ${said.text.slice(0, 160)}`);
    return null;
  }
  const { triggered, trigger_reason: reason, surfaced, nudge_id: id } = said.json;
  if (!triggered) console.log('  · nothing to ask about');
  else if (surfaced) console.log(`  ✓ ${id} — ${reason}`);
  else console.log(`  · ${reason}, held back by the one-a-minute limit`);
  return said.json;
}

async function main() {
  if (flags.has('--list')) {
    const rows = await allMeetings();
    if (rows.length === 0) console.log('this service has no meetings');
    for (const row of rows) {
      console.log(`  ${row.id.padEnd(12)} ${row.mode.padEnd(11)} ${row.client} (${row.engagement})`);
    }
    console.log('\nnewest is last. The capture screen names the one it is on in the toolbar.');
    return;
  }

  const meetingId = named ?? (await newestMeeting());
  console.log(`meeting: ${meetingId}${named ? '' : '   (newest — check this against the picker)'}`);
  console.log(`service: ${SERVICE}\n`);

  if (!flags.has('--listen')) {
    const lines = flags.has('--quiet-check')
      ? ORDINARY
      : flags.has('--script')
        ? VAGUE
        : [VAGUE[0]];

    for (const [index, line] of lines.entries()) {
      console.log(`"${line}"`);
      await say(meetingId, line);
      // Only `--script` is asking to see more than one nudge, and only it can
      // afford to wait out the limit that stands between them.
      if (flags.has('--script') && index < lines.length - 1) {
        console.log('  … waiting 61s for the rate limit\n');
        await sleep(61_000);
      }
    }
    console.log('');
  }

  const frames = await panelFrames(meetingId);
  const nudges = frames.filter(([name]) => name === 'nudge');
  console.log(`--- what the panel's connection carries (${frames.length} frames) ---`);
  if (nudges.length === 0) console.log('(no nudge on this meeting)');
  for (const [, nudge] of nudges) {
    console.log(`\n  ${nudge.stub}`);
    console.log(`  ${nudge.question}`);
    console.log(`  ${nudge.trigger_reason}   [${nudge.id}]`);
  }
}

main().catch((cause) => {
  console.error(String(cause?.message ?? cause));
  process.exit(1);
});
