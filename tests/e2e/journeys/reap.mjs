/**
 * Guarantee a spawned browser dies with the script that started it.
 *
 * Every journey tool launches Chrome as a bare child process rather than
 * through a library that owns its lifetime, so nothing reaps it for us. Each
 * one used to kill Chrome on the last line of its happy path, which is the one
 * path where a leak is impossible: a throw, an interrupt, or an early
 * `process.exit` all skipped it and left a headless browser reparented to
 * init, holding a DevTools port and a profile directory in `/tmp` — which is
 * tmpfs here, so the litter is resident memory, not disk. Forty-three days of
 * that cost seventeen browsers, 254 processes and ~9 GB.
 *
 * `exit` is the load-bearing hook, not `finally`: it fires on a normal return
 * *and* on every `process.exit()`, including the ones inside `main().catch()`
 * that made the leak in the first place. Signals need their own handlers
 * because the default disposition terminates without ever running `exit` —
 * and an interrupted run is the common case for these tools, which hang
 * silently against an HTTPS dev server and get answered with Ctrl-C.
 *
 * The callback must be synchronous. Node runs `exit` listeners on the way out
 * and will not wait for a promise, so anything asynchronous in there is
 * dropped: `child.kill()` and `rmSync` qualify, an `await` does not.
 */

import { readdirSync, readFileSync, rmSync, statSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';

/**
 * Delete profile directories left by earlier runs of this tool.
 *
 * Teardown alone cannot finish the job, for two reasons that no exit handler
 * can reach. `child.kill()` only *sends* SIGTERM: Chrome then shuts down
 * gracefully and writes `Local State` and `Secure Preferences` back out, so a
 * synchronous `rmSync` on the next line deletes a directory that is about to
 * be recreated. And SIGKILL to our own process runs no handler at all.
 * (SIGKILL to Chrome is not the answer either — its renderers and zygotes are
 * separate processes that a killed parent would orphan rather than reap.)
 *
 * So cleanup converges instead of preventing: each run removes what earlier
 * runs stranded. A directory is stale when no live process names it, which is
 * what makes this safe to call while other journey tools are running.
 *
 * @param {string} prefix Basename prefix, e.g. `elicta-capture-`.
 * @returns {number} How many directories were removed.
 */
export function sweepStaleProfiles(prefix) {
  let live = '';
  try {
    // One pass over /proc rather than one per candidate: the directory count
    // is what grows unbounded here, and it reached 190 before anyone noticed.
    for (const entry of readdirSync('/proc')) {
      if (!/^\d+$/.test(entry)) continue;
      try {
        live += readFileSync(`/proc/${entry}/cmdline`, 'utf8');
      } catch {
        /* the process ended mid-scan, or is not ours to read */
      }
    }
  } catch {
    // No /proc — treat nothing as live and fall back to the age check below.
  }

  let removed = 0;
  const cutoff = Date.now() - 60 * 60 * 1000;
  for (const name of readdirSync(tmpdir())) {
    if (!name.startsWith(prefix)) continue;
    const dir = path.join(tmpdir(), name);
    if (live.includes(dir)) continue;
    try {
      // Without /proc the age check is the only guard, and an hour is longer
      // than any journey run takes.
      if (live === '' && statSync(dir).mtimeMs > cutoff) continue;
      rmSync(dir, { recursive: true, force: true });
      removed += 1;
    } catch {
      /* someone else's, or already gone */
    }
  }
  return removed;
}

/**
 * Register `kill` to run once, on whatever path this process leaves by.
 *
 * @param {() => void} kill Synchronous teardown. Must tolerate being called
 *   when the thing it is tearing down never started.
 * @returns {() => void} The same teardown, guarded so it runs at most once.
 *   Callers that want the browser gone before they print a report can invoke
 *   it early; the exit handler then does nothing.
 */
export function reapOnExit(kill) {
  let reaped = false;

  const reap = () => {
    if (reaped) return;
    reaped = true;
    // A teardown that throws must not become the failure the run reports —
    // the browser is already going away and the exit code is already decided.
    try {
      kill();
    } catch {
      /* ignore */
    }
  };

  process.on('exit', reap);

  // 128 + signal number, which is what a shell reports for a signalled child.
  for (const [signal, code] of [
    ['SIGINT', 130],
    ['SIGTERM', 143],
    ['SIGHUP', 129],
  ]) {
    process.on(signal, () => {
      reap();
      process.exit(code);
    });
  }

  return reap;
}
