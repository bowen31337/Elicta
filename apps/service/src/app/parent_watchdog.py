"""Exit when the app that started this service is gone.

The desktop shell starts the frozen service as a child and stops it on
`RunEvent::Exit`. That covers a clean quit and nothing else: a SIGTERM or a
crash never runs the exit handler, and the service is left holding port 8000,
reparented to launchd.

An ordinary leak would be tolerable. This one is not, because the shell starts
its own service *only when nothing already answers on 8000* — so the next
launch adopts the orphan instead. An orphan from a previous build then serves
a stale backend out of a binary that has since been replaced on disk, which is
invisible to every check anyone would think to run: the file is current, the
port answers, the version matches.

**Which process to watch is the whole problem.** The obvious implementation
watches `os.getppid()`, and it does not work here: a PyInstaller onefile
binary is two processes — a bootloader that unpacks the archive, and the real
interpreter it re-execs as its child. This code runs in the child, so its
parent is the bootloader, which survives the app's death perfectly happily.
`getppid()` never changes and the watchdog never fires. Verified the hard way:
after killing the app, `54169 ppid=1` (bootloader, orphaned) and
`54172 ppid=54169` (this process, parent alive).

So the shell names the pid it wants watched, in `ELICTA_PARENT_PID`, and this
watches that. Absent the variable there is nothing to watch and nothing to do
— which is the case for every way of running the service outside the bundle.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable

#: How often to look. One signal-free `kill` each time, and an orphan holding
#: the port for a couple of seconds after the app quits harms nobody: the next
#: launch is a human action away.
POLL_SECONDS = 2.0

#: Where the shell writes the pid it wants watched.
PARENT_PID_ENV = "ELICTA_PARENT_PID"


def process_is_alive(pid: int) -> bool:
    """Whether `pid` still exists, without signalling it.

    Signal 0 performs the permission and existence checks and delivers
    nothing. `PermissionError` means the process exists and belongs to
    somebody else, which for this purpose is alive.
    """

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def should_exit(
    *, watched_pid: int | None, is_alive: Callable[[int], bool] = process_is_alive
) -> bool:
    """Whether the process this service was told to follow has gone."""

    if watched_pid is None:
        return False
    return not is_alive(watched_pid)


def watched_pid_from_env(environ: dict[str, str] | None = None) -> int | None:
    """The pid the shell asked us to follow, if it asked.

    A malformed value is treated as absent rather than fatal: refusing to
    start over an unparseable environment variable would turn a bad launch
    argument into a service that does not run at all.
    """

    raw = (environ if environ is not None else os.environ).get(PARENT_PID_ENV)
    if not raw:
        return None
    try:
        pid = int(raw)
    except ValueError:
        return None
    return pid if pid > 0 else None


def watch(
    *,
    watched_pid: int | None,
    on_gone: Callable[[], None],
    is_alive: Callable[[int], bool] = process_is_alive,
    sleep: Callable[[float], None] = time.sleep,
    poll_seconds: float = POLL_SECONDS,
    forever: bool = True,
) -> None:
    """Poll until the watched process is gone, then call `on_gone`."""

    if watched_pid is None:
        return
    while True:
        sleep(poll_seconds)
        if should_exit(watched_pid=watched_pid, is_alive=is_alive):
            on_gone()
            return
        if not forever:
            return


def exit_with_parent() -> threading.Thread | None:
    """Start the watchdog on a daemon thread, if the shell named a pid."""

    watched_pid = watched_pid_from_env()
    if watched_pid is None:
        return None

    def gone() -> None:  # pragma: no cover - the process ends here
        print(
            "elicta-service: the app that started this is gone; exiting",
            flush=True,
        )
        # `os._exit` rather than a graceful shutdown: there is no user left to
        # serve and no request worth draining, and uvicorn's shutdown waits on
        # connections a departed app may still be holding open.
        os._exit(0)

    thread = threading.Thread(
        target=watch,
        kwargs={"watched_pid": watched_pid, "on_gone": gone},
        daemon=True,
    )
    thread.start()
    return thread
