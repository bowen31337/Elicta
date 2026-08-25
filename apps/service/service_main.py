"""The service, as a program the desktop app can start.

`uvicorn app.main:app` is how a developer runs this and needs a Python
environment to do it. Somebody who downloaded a `.dmg` has none, and should
not be asked to acquire one: the app they opened is expected to work.

So this is the entry point that gets frozen into a single executable and
shipped inside the bundle. It is deliberately thin — the app it serves is the
same `app.main:app` as everywhere else, because a second assembly for the
packaged case is a second thing to drift.

The port is taken from the environment rather than fixed, so the shell can
hand over one it has already found free, and defaults to the port a developer
would have used.
"""

from __future__ import annotations

import os
import sys


def main() -> int:
    import uvicorn

    host = os.environ.get("ELICTA_SERVICE_HOST", "127.0.0.1")
    port = int(os.environ.get("ELICTA_SERVICE_PORT", "8000"))

    # Imported here rather than at module scope: a frozen binary starts by
    # running this file, and an import error at module scope is reported
    # without the log configuration below ever being applied.
    from app.main import app
    from app.parent_watchdog import exit_with_parent

    # The shell stops this service when it quits cleanly, and cannot when it
    # does not: a SIGTERM or a crash never runs its exit handler, and this
    # process is left holding the port under launchd. That matters more than
    # an ordinary leak because the shell starts its own service only when
    # nothing already answers, so the next launch adopts the orphan — serving
    # a stale backend from a binary that has since been replaced on disk.
    exit_with_parent()

    uvicorn.run(app, host=host, port=port, log_level="info")
    return 0


if __name__ == "__main__":
    sys.exit(main())
