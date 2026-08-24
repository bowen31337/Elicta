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
  # Installed from the service's own metadata rather than a second list, so the
  # frozen binary carries what the service declares and not a copy that drifts.
  "$@" "$venv/bin/pip" install --quiet "$ROOT/apps/service"
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
    exit 0
  fi
done

echo "the frozen service never answered:" >&2
tail -30 "$WORK/run.log" >&2
kill "$SERVICE_PID" 2>/dev/null || true
exit 1
