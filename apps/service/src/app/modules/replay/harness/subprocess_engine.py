"""Production `CoreEngine`: runs the shared Rust core as a subprocess.

A subprocess boundary is what makes NFR-3.8's demonstration possible: the
same core source is compiled to a platform-native binary on macOS, Windows,
and Linux, and this class invokes it through one uniform argv/stdin/stdout
contract that doesn't vary by platform. There is deliberately no suggestion
logic here for a platform to diverge on — only process plumbing.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from .errors import CoreProcessError


class SubprocessCoreEngine:
    """Feeds `input_bytes` to the core binary on stdin and returns its
    stdout as the suggestion log.

    `seed` is passed as a `--seed` argument rather than folded into stdin,
    so the core's replay entry point can read the transcript and the seed
    independently of one another.
    """

    def __init__(self, executable: Path | str) -> None:
        self._executable = Path(executable)

    def run(self, input_bytes: bytes, seed: int) -> bytes:
        if not self._executable.exists():
            raise CoreProcessError(f"core executable not found: {self._executable}")

        try:
            completed = subprocess.run(
                [str(self._executable), "--seed", str(seed)],
                input=input_bytes,
                capture_output=True,
                check=False,
            )
        except OSError as exc:
            raise CoreProcessError(
                f"failed to launch core executable {self._executable}: {exc}"
            ) from exc

        if completed.returncode != 0:
            stderr = completed.stderr.decode("utf-8", errors="replace")
            raise CoreProcessError(
                f"core executable {self._executable} exited with "
                f"{completed.returncode}: {stderr}"
            )

        return completed.stdout
