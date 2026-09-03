import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

/**
 * The transcript sits beside the question, and the gate that says so is
 * reachable.
 *
 * `route.css` splits the panel into two columns at
 * `@container panel (min-width: 52rem)`, and that rule was right from the day
 * it was written. It had also never once applied. The shell stages the panel
 * as a card — `width: min(420px, 100%)` — so the container it asks about was
 * 420px on every display ever built, and the columns stacked on a 27-inch
 * monitor exactly as they stacked on a phone. Nothing failed. No test went
 * red, no console said anything, and the screenshots looked like a deliberate
 * one-column design.
 *
 * That is the failure this file is about, and it is not really a CSS bug: two
 * numbers in two files have to agree, they are separated by a padding chain,
 * and when they disagree the symptom is a feature that silently does not
 * exist. So the numbers are read back out of the stylesheets and checked
 * against each other rather than trusted to stay in step.
 *
 * The chain, from the pane inwards:
 *
 *   .pane-body--stage   content box          ← the `stage` container
 *     .panel            − 2 × --panel-inset  ← the `panel` container
 *       .panel-split    the grid
 *
 * so the stage must clear the split's threshold by twice the panel's inset,
 * and the width it is allowed to grow to must clear the stage's own gate —
 * otherwise it widens to a number that still cannot split.
 */
const SRC = join(__dirname, '..', '..', '..');
const SHELL_CSS = readFileSync(join(SRC, 'shell', 'shell.css'), 'utf8');
const ROUTE_CSS = readFileSync(join(SRC, 'features', 'panel', 'route.css'), 'utf8');
const TOKENS_CSS = readFileSync(join(SRC, 'tokens.css'), 'utf8');
const STYLES_CSS = readFileSync(join(SRC, 'styles.css'), 'utf8');

/** `16px` and `1rem` are the same distance; the test may not care which. */
function toPx(value: string): number {
  const match = /^([\d.]+)(rem|px)$/.exec(value.trim());
  if (match === null) throw new Error(`not a length: ${value}`);
  return match[2] === 'rem' ? Number(match[1]) * 16 : Number(match[1]);
}

/** The width a named container query waits for. */
function containerThreshold(css: string, name: string): number {
  const match = new RegExp(`@container\\s+${name}\\s*\\(\\s*min-width:\\s*([^)]+)\\)`).exec(css);
  if (match === null) throw new Error(`no @container ${name} query`);
  return toPx(match[1]);
}

/**
 * What `--panel-inset` resolves to, followed through the one indirection it
 * has. Read rather than hardcoded: the whole point here is that a number
 * moving in one file must be seen in another.
 */
function panelInset(): number {
  const named = /--panel-inset:\s*var\((--space-\d+)\)/.exec(STYLES_CSS);
  if (named === null) throw new Error('--panel-inset is no longer a space token');
  const value = new RegExp(`${named[1]}:\\s*([\\d.]+rem)`).exec(TOKENS_CSS);
  if (value === null) throw new Error(`${named[1]} is not declared in tokens.css`);
  return toPx(value[1]);
}

/** What the widened stage declares for the card, as one block of CSS. */
function widenedPanelRule(): string {
  const match = /@container stage[\s\S]*?\.pane-body--stage > \.panel\s*\{([\s\S]*?)\}/.exec(
    SHELL_CSS,
  );
  if (match === null) throw new Error('the stage no longer widens the panel');
  return match[1];
}

describe('the two-column panel is reachable from the shell', () => {
  it('stages the panel inside a container the split can be measured against', () => {
    // Without a name there is nothing for the `@container stage` query to
    // bind to, and an unresolvable container query never matches — silently,
    // which is the same shape of failure all over again.
    expect(SHELL_CSS).toMatch(/\.pane-body--stage\b[\s\S]*?container-name:\s*stage/);
    expect(SHELL_CSS).toMatch(/\.pane-body--stage\b[\s\S]*?container-type:\s*inline-size/);
  });

  it('opens the stage wide enough that the split can then apply', () => {
    const split = containerThreshold(ROUTE_CSS, 'panel');
    const stage = containerThreshold(SHELL_CSS, 'stage');

    // Twice, because the inset is paid on both edges of the card.
    expect(stage).toBeGreaterThanOrEqual(split + 2 * panelInset());
  });

  it('gives the card the whole of the pane once it splits', () => {
    // Every pixel the card holds back is a pixel of transcript, which is the
    // thing an operator runs out of. The reading measure is kept by the
    // columns inside — `1.2fr` against `1fr`, each with a floor — rather than
    // by a ceiling on the card, which took the width from the transcript and
    // gave it to the margin.
    const rule = widenedPanelRule();

    expect(rule).toMatch(/width:\s*100%/);
    expect(rule).not.toMatch(/max-width:/);
  });

  it('does not ask the stage to answer a question about itself either', () => {
    // The same no-op, one level out. `align-items: stretch` was written on
    // `.pane-body--stage` inside `@container stage` and simply never applied;
    // it read as a rule the browser had ignored for some other reason. Rules
    // in here may only reach the stage's descendants — `align-self` on the
    // panel does the job `align-items` on the stage cannot.
    const query = /@container stage \(min-width:[^)]+\)\s*\{([\s\S]*?)\n  \}/.exec(SHELL_CSS);
    expect(query).not.toBeNull();
    expect(query?.[1]).toMatch(/\.pane-body--stage > \.panel/);
    expect(query?.[1]).not.toMatch(/^\s*\.pane-body--stage\s*\{/m);
  });

  it('does not ask the panel to answer a question about itself', () => {
    // `.panel` is the container, so a rule for `.panel` inside
    // `@container panel` does nothing whatsoever and reports nothing. The grid
    // therefore belongs to `.panel-split`. This shipped once as a stacked
    // layout for exactly that reason.
    const query = /@container panel \(min-width:[^)]+\)\s*\{([\s\S]*?)\n  \}/.exec(ROUTE_CSS);
    expect(query).not.toBeNull();
    expect(query?.[1]).toMatch(/\.panel-split\s*\{[\s\S]*?display:\s*grid/);
    expect(query?.[1]).not.toMatch(/^\s*\.panel\s*\{/m);
  });

  it('keeps a floor under the column the operator reads', () => {
    // `minmax(0, 1fr)` here once let the question column collapse to 40px
    // while the transcript beside it gave up nothing.
    const columns = /grid-template-columns:\s*minmax\(([^,]+),[^)]+\)\s*minmax\(/.exec(ROUTE_CSS);
    expect(columns).not.toBeNull();
    expect(toPx(columns![1])).toBeGreaterThan(0);
  });
});
