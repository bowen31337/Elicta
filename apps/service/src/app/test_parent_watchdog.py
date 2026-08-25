"""The sidecar must not outlive the app that started it.

Killing the desktop process left `elicta-service` running and holding port
8000. That is worse than an ordinary leak: the shell starts its own service
only when nothing already answers on 8000, so the next launch silently adopts
the orphan — and an orphan from a previous build serves a stale backend from a
binary that no longer exists on disk, which is undiagnosable from outside.

The shell stops the service on a clean quit and cannot on a SIGTERM or a
crash, so the child has to end itself. The non-obvious part is *which* process
it watches: a PyInstaller onefile binary is two processes, a bootloader that
unpacks the archive and the real interpreter it re-execs as its child. Code in
the child that watches its own parent is watching the bootloader, which
survives the app's death, so `getppid()` never changes and the watchdog never
fires. The shell names the pid it wants watched instead.
"""

from __future__ import annotations

from app.parent_watchdog import should_exit


class TestWatchingThePidTheShellNamed:
    def test_a_dead_watched_process_means_exit(self):
        assert should_exit(watched_pid=4321, is_alive=lambda _pid: False)

    def test_a_live_watched_process_means_stay(self):
        assert not should_exit(watched_pid=4321, is_alive=lambda _pid: True)

    def test_nothing_named_means_stay(self):
        """A developer running the service by hand names no pid.

        Exiting on that basis would make `uvicorn app.main:app` unusable,
        which is how the service is run everywhere except inside the bundle.
        """

        assert not should_exit(watched_pid=None, is_alive=lambda _pid: False)

    def test_watching_the_bootloader_is_the_bug_this_replaced(self):
        """The regression in one line.

        `os.getppid()` in the frozen child returns the PyInstaller bootloader,
        which outlives the app: watching it is watching the wrong process.
        Nothing here may fall back to it.
        """

        import ast
        import inspect

        import app.parent_watchdog as watchdog

        # Read as code, not as text. The module docstring explains this trap
        # at length, so a substring check would fail on the explanation and
        # force the module to stop saying why — the wrong trade.
        tree = ast.parse(inspect.getsource(watchdog))
        called = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        assert "getppid" not in called
