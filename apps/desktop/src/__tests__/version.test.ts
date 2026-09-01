import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

/**
 * One version, in three files, bumped by the build.
 *
 * Every `.dmg` was `Elicta_0.1.0_aarch64.dmg`, so a rebuild overwrote the
 * last one and no artifact said which build it was. That matters more here
 * than it looks: a stale install shadowing a fresh build cost most of an
 * afternoon, and "which one is this?" had no answer on disk.
 *
 * The three have to move together. `tauri.conf.json` names the bundle and is
 * what the updater compares; `Cargo.toml` versions the shell binary;
 * `package.json` is what `pnpm` reports. Two of them agreeing and one not is
 * a build whose artifact and whose binary disagree about what they are.
 */
const ROOT = join(__dirname, '..', '..', '..', '..');
const TAURI = join(ROOT, 'apps', 'desktop', 'src-tauri', 'tauri.conf.json');
const CARGO = join(ROOT, 'apps', 'desktop', 'src-tauri', 'Cargo.toml');
const PACKAGE = join(ROOT, 'apps', 'desktop', 'package.json');
const BUILD = join(ROOT, 'scripts', 'build-macos.sh');
const BUMP = join(ROOT, 'scripts', 'bump-version.sh');

function read(path: string): string {
  return readFileSync(path, 'utf8');
}

describe('the version the build stamps', () => {
  it('is the same in all three files that carry it', () => {
    const tauri = JSON.parse(read(TAURI)) as { version: string };
    const pkg = JSON.parse(read(PACKAGE)) as { version: string };
    const cargo = /^version\s*=\s*"([^"]+)"/m.exec(read(CARGO))?.[1];

    expect(pkg.version).toBe(tauri.version);
    expect(cargo).toBe(tauri.version);
  });

  it('looks like a version, so the bump has something to add to', () => {
    const { version } = JSON.parse(read(TAURI)) as { version: string };
    expect(version).toMatch(/^\d+\.\d+\.\d+$/);
  });
});

describe('bumping it', () => {
  it('ships a script that does it', () => {
    expect(() => read(BUMP)).not.toThrow();
  });

  it('runs as part of building the bundle', () => {
    expect(read(BUILD)).toMatch(/bump-version\.sh/);
  });

  it('can be skipped, for a rebuild of the same version', () => {
    // Rebuilding a version deliberately — to re-sign it, or after a failed
    // bundler run — must not invent a new number for the same code.
    expect(read(BUMP)).toMatch(/--no-bump|--keep/);
  });
});
