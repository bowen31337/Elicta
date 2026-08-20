#!/usr/bin/env node
/** Turns a live run's `report.json` into a report a person reads. */

import { readFileSync, writeFileSync, existsSync } from 'node:fs';

const dir = process.argv[2];
const report = JSON.parse(readFileSync(`${dir}/report.json`, 'utf8'));

const lines = [];
const say = (text = '') => lines.push(text);

const total = report.totals.passed + report.totals.failed;
say('# Live journey run');
say();
say(`Driven against a running system — panel at ${report.startedAgainst.app}, service at ${report.startedAgainst.api}.`);
say(`**${report.totals.passed} of ${total} checks passed; ${report.totals.failed} failed.**`);
say();
say('| # | Journey | Passed | Failed | Recording |');
say('|---|---|---|---|---|');
for (const j of report.journeys) {
  const flag = j.blocked ? ' ⚠︎' : '';
  say(`| ${j.id} | ${j.title}${flag} | ${j.passed} | ${j.failed} | \`${j.video}\` |`);
}
say();
say('⚠︎ — journey depends on a speech-vendor credential that is not configured.');
say();

for (const j of report.journeys) {
  say(`## ${j.id} — ${j.title}`);
  say();
  if (j.blocked) say(`> Blocked: ${j.blocked}`);
  if (j.blocked) say();
  say(`Video: \`${j.video}\` (${j.frames} frames). Screenshots: ${j.shots.length}.`);
  say();
  const failed = j.checks.filter((c) => !c.ok);
  const passed = j.checks.filter((c) => c.ok);
  if (passed.length) {
    say('**Passed**');
    say();
    for (const c of passed) say(`- ${c.name}`);
    say();
  }
  if (failed.length) {
    say('**Failed**');
    say();
    for (const c of failed) {
      say(`- **${c.name}**`);
      say(`  - ${c.detail.replace(/\n/g, ' ').slice(0, 400)}`);
    }
    say();
  }
  for (const note of j.notes ?? []) say(`- note — ${note.name}: ${note.detail}`);
  if ((j.notes ?? []).length) say();
  if (j.error) {
    say('**The journey stopped early**');
    say();
    say('```');
    say(j.error.slice(0, 800));
    say('```');
    say();
  }
  if (j.networkFailures?.length) {
    say(`Failed browser requests during this journey: ${j.networkFailures.length}`);
    say();
    for (const f of [...new Set(j.networkFailures)].slice(0, 8)) say(`- \`${f}\``);
    say();
  }
}

if (report.consoleErrors?.length) {
  say('## Uncaught errors in the page');
  say();
  for (const e of report.consoleErrors) say(`- \`${e.split('\n')[0]}\``);
  say();
}

writeFileSync(`${dir}/report.md`, lines.join('\n'));
console.log(`report.md written (${lines.length} lines)`);
