import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

/**
 * What a build leaves behind, and what a stale leftover costs.
 *
 * Two kinds of staleness bit this project in one afternoon, and neither
 * announced itself.
 *
 * A copy of the app installed in `/Applications` weeks earlier had its
 * service on port 8000. The shell starts its own only when nothing is already
 * answering, so every rebuild launched from the build tree talked to the old
 * service: a panel built minutes ago against an API from another version, with
 * the symptom appearing as endpoints answering 404 that answered 200
 * in-process against the same database. The shell refuses to adopt a stranger
 * now, but refusing is not clearing — somebody still has to find and stop it.
 *
 * And the frozen service is reused unless something it was built from is
 * newer. "Something" was every Python file under `apps/service` alone, which
 * leaves out the two inputs that decide what goes into the binary: the locked
 * dependency set the freezer verifies against, and the freeze script itself.
 * Change either and the build silently ships the previous service.
 *
 * Asserted here for the reason the drag-drop guard beside it is: the failure
 * only exists in a packaged build, so no test that runs can reproduce the
 * effect. The cause is checkable, and this is where it is checked.
 */
const ROOT = join(__dirname, '..', '..', '..', '..');
const BUILD = join(ROOT, 'scripts', 'build-macos.sh');
const PRUNE = join(ROOT, 'scripts', 'prune-stale-builds.sh');

function read(path: string): string {
  return readFileSync(path, 'utf8');
}

describe('the frozen service is not reused when it is out of date', () => {
  // The predicate lives in the pruner, which deletes a stale sidecar so the
  // build's own "is there one?" check refreezes. One rule in one place, rather
  // than a condition in the build script that has to be kept in step with what
  // the freeze actually reads.
  const pruner = read(PRUNE);

  it('refreezes when the locked dependency set changed', () => {
    // The freeze script refuses to build an environment that disagrees with
    // `uv.lock`, so a lock change is a change to what the binary contains —
    // and no Python file need move for that to happen.
    expect(pruner).toMatch(/uv\.lock/);
  });

  it('refreezes when the freeze script itself changed', () => {
    // It decides the hidden imports, the exclusions and the entry point. A
    // binary built by a previous version of it is a different binary.
    expect(pruner).toMatch(/build-service-sidecar\.sh/);
  });

  it('leaves the build script with no second opinion about freshness', () => {
    // Two predicates would disagree, and the one in the build script is the
    // one nobody would think to update.
    expect(read(BUILD)).not.toMatch(/find apps\/service -newer/);
  });
});

describe('a build clears what it makes stale', () => {
  it('ships a pruner', () => {
    expect(() => read(PRUNE)).not.toThrow();
  });

  it('runs it as part of building', () => {
    expect(read(BUILD)).toMatch(/prune-stale-builds\.sh/);
  });

  it('never deletes the operator\'s installed copy on its own', () => {
    // `/Applications/Elicta.app` is somebody's install, not a build output.
    // Reporting it is useful; removing it behind their back is not, so the
    // removal is behind an explicit flag.
    const pruner = read(PRUNE);
    expect(pruner).toMatch(/Applications/);
    expect(pruner).toMatch(/--remove-installed|--force/);
  });
});

describe('a deleted disk image does not stay mounted', () => {
  // Deleting a superseded `.dmg` does not eject what was mounted from it, and
  // macOS keeps such a mount alive indefinitely. Every build that opened one
  // left a volume behind serving an `Elicta.app` from a version nobody could
  // rebuild: four were mounted at once here, all 0.1.0, all backed by an image
  // the pruner had already deleted. Nothing announced them — a mounted volume
  // is indistinguishable from the real thing to anything that finds an app by
  // name.
  const pruner = read(PRUNE);

  it('ejects a mount whose backing image is gone', () => {
    // Bound to the branch that runs it, not to the word: `hdiutil detach` also
    // appears in the sentence that *reports* a live mount, so matching the
    // bare command passed with the eject deleted.
    expect(pruner).toMatch(/elif hdiutil detach "\$mount"/);
  });

  it('leaves a mount alone while its image is still on disk', () => {
    // That one may be open in front of somebody dragging the app across, so
    // it is named with the command rather than pulled out from under them.
    // The guard is the test of the image file, and losing it would turn a
    // report into an eject.
    expect(pruner).toMatch(/-f "\$image"/);
  });
});

describe('what the machine thinks is Elicta is what was last built', () => {
  // Ejecting a volume does not unregister what was on it: LaunchServices keys
  // a registration by volume UUID and holds it against the volume returning.
  // A hundred and five `Elicta.app` registrations had accumulated that way,
  // one per image ever opened, every one of them 0.1.0 — and that list is
  // what decides which copy the machine answers with when somebody searches
  // for the app, so the newest build sat under a hundred dead ones.
  const pruner = read(PRUNE);
  const build = read(BUILD);

  it('unregisters copies that are no longer on disk', () => {
    // The call, not the path to the binary — naming the tool is not using it.
    expect(pruner).toMatch(/"\$lsreg" -u "\$path"/);
  });

  it('unregisters only what is actually gone', () => {
    // The guard that keeps this from ever dropping a copy somebody has. `-gc`
    // does not collect these and `-kill` was removed in macOS 26, so `-u` on
    // the individual path is the whole mechanism — and it is as safe as this
    // check.
    expect(pruner).toMatch(/\[ -e "\$path" \] && continue/);
  });

  it('installs what it just built', () => {
    // Left to somebody remembering to open the `.dmg`, `/Applications` drifts
    // behind the build tree with nothing saying so — 0.1.0 sat there for a
    // fortnight while 0.1.37 was being built, and the machine went on offering
    // the old one, because that is the copy in the place applications live.
    expect(build).toMatch(/ditto "\$app" "\$installed"/);
  });

  it('refuses to overwrite a copy that is running', () => {
    // `ditto` over a bundle whose executable is mapped leaves a process
    // running code that is no longer on disk, which fails later and somewhere
    // else. Refusing and saying so is the smaller problem.
    expect(build).toMatch(/pgrep -f "\$installed/);
  });

  it('can be told not to', () => {
    // Installing is the default because a build nobody can find is the
    // failure being fixed, but a build is not always an install.
    // The arm that reads it. The flag is named in the header too, and a
    // documented flag that no `case` accepts is an error, not an option.
    expect(build).toMatch(/--no-install\) install=0/);
  });
});
