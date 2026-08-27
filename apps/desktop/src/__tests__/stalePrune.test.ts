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
