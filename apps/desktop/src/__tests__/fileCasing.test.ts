import { readdirSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

/**
 * Two modules whose paths differ only in case.
 *
 * They are two files on Linux and one on macOS, so a repository that builds
 * here fails there — and fails late, on a runner, thirty seconds into a job
 * billed at ten times the usual rate. That is exactly how it went: a component
 * `SectionIndex.tsx` beside its logic `sectionIndex.ts` compiled cleanly on
 * this machine and stopped the macOS bundle with TS1149.
 *
 * The same blind spot the Rust targets have, in a language nobody expects it
 * in. The check has to run where the failure cannot be reproduced, so it looks
 * for the cause rather than waiting for the effect.
 */
export function collisions(paths: readonly string[]): string[][] {
  const byLowercase = new Map<string, string[]>();
  for (const path of paths) {
    const key = path.toLowerCase();
    byLowercase.set(key, [...(byLowercase.get(key) ?? []), path]);
  }
  return [...byLowercase.values()].filter((group) => group.length > 1);
}

function filesUnder(root: string): string[] {
  const found: string[] = [];
  for (const entry of readdirSync(root, { withFileTypes: true })) {
    const path = join(root, entry.name);
    if (entry.isDirectory()) found.push(...filesUnder(path));
    else found.push(path);
  }
  return found;
}

describe('paths that differ only in case', () => {
  it('is what the check is looking for', () => {
    // Proves the check can fail. Without it the assertion below is only ever
    // observed passing, and a walk that silently found nothing would look
    // identical to a tree with nothing wrong in it.
    expect(collisions(['a/SectionIndex', 'a/sectionIndex'])).toHaveLength(1);
    expect(collisions(['a/one', 'b/one'])).toHaveLength(0);
  });

  it('are absent from the desktop source, which macOS would read as one module', () => {
    // Only the files an import without an extension can resolve to. A
    // component beside its own stylesheet shares a stem — `route.tsx` and
    // `route.css` — and is not this problem: those are imported by their full
    // name, and there is exactly one module among them.
    //
    // Compared without the extension all the same, because `SectionIndex.tsx`
    // and `sectionIndex.ts` are distinct filenames that still resolve from one
    // import path, which is the form this actually took.
    const modules = filesUnder('src')
      .filter((path) => path.endsWith('.ts') || path.endsWith('.tsx'))
      .map((path) => path.replace(/\.[^./]+$/, ''));

    expect(collisions(modules)).toEqual([]);
  });
});
