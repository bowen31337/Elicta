#!/usr/bin/env bash
# Freeze the service into a single executable for the desktop bundle.
#
# Somebody who downloads the .dmg has no Python and should not need one: the
# app they opened is expected to work. So the service ships inside the bundle
# as a sidecar, and Tauri looks for it under the target triple it is building
# for.
#
#   ./scripts/build-service-sidecar.sh universal-apple-darwin
#   ./scripts/build-service-sidecar.sh aarch64-apple-darwin
#
# The universal target needs a universal2 Python — the python.org builds are,
# and the standalone ones `uv python install` fetches are not, which is why CI
# uses `actions/setup-python` for this step and not for anything else.
set -euo pipefail

TRIPLE="${1:?usage: build-service-sidecar.sh <target-triple>}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$ROOT/apps/desktop/src-tauri/binaries"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# Which interpreter is frozen. Overridable because the choice matters and is
# not always the one on PATH: the universal target needs a universal2 build,
# and a machine's own `python3` may be a version this service does not support
# or one without `venv` at all.
PYTHON="${PYTHON:-python3}"

# The frozen environment is resolved from `uv.lock`, not from the dependency
# ranges in `pyproject.toml` -- see `freeze` below for why -- so `uv` is needed
# to render the lock as something `pip` can install.
command -v uv >/dev/null || {
  echo "error: uv not found. The bundled service is frozen from apps/service/uv.lock," >&2
  echo "       which is what everything else runs. Install from https://docs.astral.sh/uv/" >&2
  exit 1
}

# Rendered once, outside `freeze`, because both architectures of a universal
# build must be frozen from the same resolution -- two exports could straddle a
# lockfile change and produce halves that disagree.
LOCKED="$WORK/requirements-locked.txt"
uv export \
  --project "$ROOT/apps/service" \
  --frozen \
  --no-hashes \
  --no-emit-project \
  --format requirements-txt \
  >"$LOCKED"

# macOS wants one binary covering both architectures, and it cannot be got by
# asking PyInstaller for `universal2`: the packages this service is built on —
# pydantic-core, cryptography, asyncpg, jiter, rpds-py, cffi — publish no
# universal2 wheels at all, only one per architecture. So each architecture is
# frozen on its own and the two are joined with `lipo`, which is what a
# universal binary is anyway.
#
# The second architecture is built through Rosetta on an Apple Silicon
# machine. Where that is not available the arm64 half is shipped alone and
# said so: a bundle that works on most Macs and reports it honestly is better
# than no bundle, and far better than one that claims to be universal.
UNIVERSAL=0
case "$TRIPLE" in
  universal-apple-darwin) UNIVERSAL=1 ;;
esac

freeze() {
  # freeze <output-path> [arch-prefix...]
  local output="$1"; shift
  local venv="$WORK/venv-$(basename "$output")"

  "$@" "$PYTHON" -m venv "$venv"
  "$@" "$venv/bin/pip" install --quiet --upgrade pip
  # Installed from `uv.lock` -- the same resolution `uv sync --locked` gives a
  # developer and CI -- and then the service itself with `--no-deps`, so pip
  # never resolves anything.
  #
  # This used to `pip install "$ROOT/apps/service"`, on the reasoning that the
  # service's own metadata is the honest source and a second list would drift.
  # The metadata is ranges, not versions: `anthropic>=0.40`, `httpx>=0.27`. So
  # the bundle got whatever pip resolved on the day it was built, and the
  # thing that drifted was the bundle. It shipped `httpx2` where every other
  # way of running this service has `httpx`, and every bank compile failed in
  # the packaged app -- `Error -3 while decompressing data` out of the model
  # call -- while the same compile succeeded from a terminal. The lockfile is
  # the service's own list too, and it pins.
  "$@" "$venv/bin/pip" install --quiet --require-virtualenv -r "$LOCKED"
  "$@" "$venv/bin/pip" install --quiet --no-deps "$ROOT/apps/service"
  "$@" "$venv/bin/pip" install --quiet pyinstaller

  # `uvicorn[standard]` brings native extras a frozen service has no use for,
  # and one of them cannot be frozen at all: `watchfiles` exists to power
  # `--reload`. `uvloop` and `httptools` are speed-ups for a server under
  # load; this one serves a single operator over the loopback address, and
  # uvicorn falls back to asyncio and h11 without them. Removed after the
  # install rather than dropped from the dependency list, because that list is
  # the service's own and the reload extra is wanted by everybody running it
  # from a terminal.
  "$@" "$venv/bin/pip" uninstall --quiet --yes watchfiles uvloop httptools || true

  # Fails the build if the environment about to be frozen is not the one the
  # lockfile describes. The bug this exists for shipped happily: pip resolved a
  # different set, PyInstaller froze it without complaint, the bundle started,
  # and the divergence only showed as a stage failing inside the packaged app.
  # Checked per locked package rather than as a whole set, because PyInstaller
  # brings dependencies of its own that are correctly absent from the lock.
  "$@" "$venv/bin/python" - "$LOCKED" <<'PYCHECK'
import re, sys
from importlib.metadata import PackageNotFoundError, version

# Compares only what is installed. A locked package can be legitimately
# absent -- the lock covers every platform, so `colorama` and `pywin32` are
# in it and are not installed here, and the three removed above are meant to
# be gone. What must never differ is the *version* of something that is
# present, which is exactly what an unpinned resolution changes.
wrong = []
for line in open(sys.argv[1], encoding="utf-8"):
    line = line.split("#", 1)[0].strip()
    match = re.match(r"^([A-Za-z0-9._-]+)==([^\s;]+)", line)
    if not match:
        continue
    name, pinned = match.group(1), match.group(2)
    try:
        found = version(name)
    except PackageNotFoundError:
        continue
    if found != pinned:
        wrong.append(f"{name}: locked {pinned}, installed {found}")

if wrong:
    print("error: the environment to be frozen does not match apps/service/uv.lock:", file=sys.stderr)
    for line in wrong:
        print(f"    {line}", file=sys.stderr)
    raise SystemExit(1)
PYCHECK

  "$@" "$venv/bin/pyinstaller" \
    --onefile \
    --noconfirm \
    --name "$(basename "$output")" \
    --distpath "$(dirname "$output")" \
    --workpath "$WORK/build-$(basename "$output")" \
    --specpath "$WORK" \
    --paths "$ROOT/apps/service/src" \
    `# The service reaches its hyphenated module directories through importlib,` \
    `# so nothing static points at them and the freezer cannot see them.` \
    --collect-submodules app \
    --collect-all uvicorn \
    `# Excluded as well as uninstalled, so a transitive reinstall cannot` \
    `# quietly put an unfreezable binary back.` \
    --exclude-module watchfiles \
    --exclude-module uvloop \
    --exclude-module httptools \
    "$ROOT/apps/service/service_main.py"
}

mkdir -p "$OUT"
echo "==> building the service for $TRIPLE with $("$PYTHON" --version) ($PYTHON)"

if [ "$UNIVERSAL" = "1" ]; then
  freeze "$WORK/elicta-service-arm64"
  if arch -x86_64 /usr/bin/true 2>/dev/null; then
    echo "==> building the second architecture through Rosetta"
    freeze "$WORK/elicta-service-x86_64" arch -x86_64
    lipo -create -output "$OUT/elicta-service-$TRIPLE" \
      "$WORK/elicta-service-arm64" "$WORK/elicta-service-x86_64"
    echo "==> joined: $(lipo -archs "$OUT/elicta-service-$TRIPLE")"
  else
    echo "!!! Rosetta is unavailable, so the bundled service covers arm64 only." >&2
    echo "!!! The app will run on an Intel Mac; its service will not start there." >&2
    cp "$WORK/elicta-service-arm64" "$OUT/elicta-service-$TRIPLE"
  fi
else
  freeze "$OUT/elicta-service-$TRIPLE"
fi

BINARY="$OUT/elicta-service-$TRIPLE"
test -x "$BINARY" || { echo "the freezer produced nothing at $BINARY" >&2; exit 1; }
echo "==> $(ls -lh "$BINARY" | awk '{print $5}') at $BINARY"

# Proves it starts and serves rather than merely that a file exists. A binary
# that is missing a module fails on its first request, which is late.
PORT=8911
ELICTA_SERVICE_PORT="$PORT" ELICTA_STATE_DIR="$WORK/state" "$BINARY" >"$WORK/run.log" 2>&1 &
SERVICE_PID=$!
for _ in $(seq 1 60); do
  sleep 1
  if curl -fsS -o /dev/null "http://127.0.0.1:$PORT/api/engagements"; then
    echo "==> the frozen service answered"
    kill "$SERVICE_PID" 2>/dev/null || true

    # **Answering is the check**, and only because every import is now at the
    # top of its module.
    #
    # PyInstaller finds modules by reading the source, so an import written
    # inside a function is one it never sees and never bundles. `websockets`
    # was imported inside `FluxUtterances._open`; the desktop app shipped
    # without it, every socket raised `ModuleNotFoundError` inside the chunk
    # handler — which swallows failures to protect the recording — and a
    # meeting recorded perfectly while transcribing nothing at all. Starting
    # up proved nothing, because nothing on the way up touched the import.
    #
    # Moved to module scope, it is reached by `composition`'s own import chain
    # before the first request, so a missing module is a service that does not
    # start and this loop never sees an answer. That is the guarantee, and it
    # is why the import's *position* is enforced by a test
    # (`test_deepgram_flux.py`) rather than left to taste.
    #
    # Grepping the archive was tried here and is not possible: a onefile build
    # compresses its table of contents, so no module name appears in `strings`
    # whether it is bundled or not — the check reported every module missing,
    # including the ones plainly present.
    exit 0
  fi
done

echo "the frozen service never answered:" >&2
tail -30 "$WORK/run.log" >&2
kill "$SERVICE_PID" 2>/dev/null || true
exit 1
