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

ARCH_FLAG=()
case "$TRIPLE" in
  universal-apple-darwin) ARCH_FLAG=(--target-arch universal2) ;;
esac

echo "==> building the service for $TRIPLE with $("$PYTHON" --version) ($PYTHON)"

"$PYTHON" -m venv "$WORK/venv"
"$WORK/venv/bin/pip" install --quiet --upgrade pip
# Installed from the service's own metadata rather than a second list, so the
# frozen binary carries what the service declares and not a copy that drifts.
"$WORK/venv/bin/pip" install --quiet "$ROOT/apps/service"
"$WORK/venv/bin/pip" install --quiet pyinstaller

# `uvicorn[standard]` brings three native extras that a frozen service has no
# use for, and one of them cannot be frozen at all: `watchfiles` exists to
# power `--reload`, ships no universal2 wheel, and stops a universal build with
# "is not a fat binary". `uvloop` and `httptools` are speed-ups for a server
# under load; this one serves a single operator on the loopback address, and
# uvicorn falls back to asyncio and h11 without them.
#
# Removed after the install rather than avoided in the dependency list,
# because that list is the service's own and the reload extra is genuinely
# wanted by everybody running it from a terminal.
"$WORK/venv/bin/pip" uninstall --quiet --yes watchfiles uvloop httptools || true

mkdir -p "$OUT"
"$WORK/venv/bin/pyinstaller" \
  --onefile \
  --noconfirm \
  --name "elicta-service-$TRIPLE" \
  --distpath "$OUT" \
  --workpath "$WORK/build" \
  --specpath "$WORK" \
  --paths "$ROOT/apps/service/src" \
  `# The service reaches its hyphenated module directories through importlib,` \
  `# so nothing static points at them and the freezer cannot see them.` \
  --collect-submodules app \
  --collect-all uvicorn \
  `# Belt and braces: excluded as well as uninstalled, so a transitive` \
  `# reinstall does not quietly put the unfreezable binary back.` \
  --exclude-module watchfiles \
  --exclude-module uvloop \
  --exclude-module httptools \
  "${ARCH_FLAG[@]}" \
  "$ROOT/apps/service/service_main.py"

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
