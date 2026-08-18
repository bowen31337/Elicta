from __future__ import annotations

import os
import stat
import sys
import textwrap
from pathlib import Path

import pytest

from .errors import CoreProcessError
from .subprocess_engine import SubprocessCoreEngine

_ECHO_CORE_SCRIPT = "#!" + sys.executable + "\n" + textwrap.dedent(
    """\
    import sys

    seed = sys.argv[sys.argv.index("--seed") + 1]
    transcript = sys.stdin.buffer.read().decode("utf-8")
    sys.stdout.write('{"span_id": "%s", "candidate_id": "%s"}\\n' % (transcript, seed))
    """
)

_FAILING_CORE_SCRIPT = "#!" + sys.executable + "\n" + textwrap.dedent(
    """\
    import sys

    sys.stderr.write("core panicked\\n")
    sys.exit(1)
    """
)


def _write_executable(path: Path, script: str) -> Path:
    path.write_text(script)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


def test_runs_the_binary_and_returns_its_stdout(tmp_path: Path):
    core = _write_executable(tmp_path / "core", _ECHO_CORE_SCRIPT)
    engine = SubprocessCoreEngine(core)

    output = engine.run(b"transcript-1", seed=42)

    assert output == b'{"span_id": "transcript-1", "candidate_id": "42"}\n'


def test_the_same_input_and_seed_produce_identical_output_on_repeated_runs(
    tmp_path: Path,
):
    core = _write_executable(tmp_path / "core", _ECHO_CORE_SCRIPT)
    engine = SubprocessCoreEngine(core)

    first = engine.run(b"transcript-1", seed=42)
    second = engine.run(b"transcript-1", seed=42)

    assert first == second


def test_a_missing_executable_raises_core_process_error(tmp_path: Path):
    engine = SubprocessCoreEngine(tmp_path / "does-not-exist")

    with pytest.raises(CoreProcessError, match="not found"):
        engine.run(b"input", seed=1)


def test_a_nonzero_exit_raises_core_process_error_with_stderr(tmp_path: Path):
    core = _write_executable(tmp_path / "core", _FAILING_CORE_SCRIPT)
    engine = SubprocessCoreEngine(core)

    with pytest.raises(CoreProcessError, match="core panicked"):
        engine.run(b"input", seed=1)


def test_an_unexecutable_file_raises_core_process_error(tmp_path: Path):
    core = tmp_path / "core"
    core.write_text("not actually executable")
    os.chmod(core, 0o644)
    engine = SubprocessCoreEngine(core)

    with pytest.raises(CoreProcessError):
        engine.run(b"input", seed=1)
