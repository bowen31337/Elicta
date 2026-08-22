#!/usr/bin/env bash
#
# Run Elicta as a web app on this machine, reachable from the network.
#
# Two processes make up the running system: the FastAPI service tier
# (apps/service) and the panel UI (apps/desktop). Normally the Tauri shell
# hosts the UI; this script serves it over HTTP instead, so the app can be
# opened in a browser — on this machine or another one — before anything is
# packaged into a .dmg / .msi / .AppImage.
#
# The UI reaches the service through a same-origin `/api` proxy on the web
# port (declared in apps/desktop/vite.config.ts). That matters: parts of the
# panel request `/api/...` relative to the page, and the service mounts no
# CORS middleware, so a cross-origin browser would fail on both counts.
#
#   ./start.sh                 # dev server, hot reload, on 0.0.0.0:1420
#   ./start.sh --prod          # build once, serve the production bundle
#   ./start.sh --host 127.0.0.1        # keep it on this machine only
#   ./start.sh --web-port 3000 --api-port 8080
#   ./start.sh --reload        # also restart the service on Python edits
#   ./start.sh --https         # serve over TLS, so the microphone works
#
# Microphone capture needs a *secure context*. Browsers expose
# `navigator.mediaDevices` only over HTTPS or on localhost, so on a plain-HTTP
# LAN address the API is absent rather than merely blocked and the Capture
# screen says so. `--https` generates a self-signed certificate covering this
# machine's addresses and serves the panel over TLS, which is enough to make
# the context secure. The browser will warn that the certificate is not
# trusted; accepting it once is expected.
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

HOST="${ELICTA_HOST:-0.0.0.0}"
WEB_PORT="${ELICTA_WEB_PORT:-1420}"
API_PORT="${ELICTA_API_PORT:-8000}"
HTTPS="${ELICTA_HTTPS:-0}"
MODE=dev
RELOAD=0
INSTALL=auto

usage() {
  sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^#\{1,2\} \{0,1\}//'
  cat <<'USAGE'
Options:
  --host HOST        interface to bind (default 0.0.0.0, all interfaces)
  --web-port PORT    port for the panel UI (default 1420)
  --api-port PORT    port for the service tier (default 8000)
  --prod             build the bundle and serve it, instead of the dev server
  --https            serve over TLS with a self-signed certificate, so the
                     browser will allow microphone access from a LAN address
  --reload           restart the service when its Python sources change
  --install          install/sync dependencies before starting
  --no-install       never install, fail if dependencies are missing
  -h, --help         this message
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host) HOST="${2:?--host needs a value}"; shift 2 ;;
    --web-port) WEB_PORT="${2:?--web-port needs a value}"; shift 2 ;;
    --api-port) API_PORT="${2:?--api-port needs a value}"; shift 2 ;;
    --prod|--preview) MODE=prod; shift ;;
    --dev) MODE=dev; shift ;;
    --https) HTTPS=1; shift ;;
    --reload) RELOAD=1; shift ;;
    --install) INSTALL=always; shift ;;
    --no-install) INSTALL=never; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "start.sh: unknown option '$1' (try --help)" >&2; exit 2 ;;
  esac
done

die() { echo "start.sh: $*" >&2; exit 1; }

# `.env` is the headless fallback for vendor credentials (the operator-facing
# route is the app's own Settings screen, which wins over anything here). It is
# optional: with no credentials at all the API still serves in full.
if [[ -f .env ]]; then
  echo "→ reading .env"
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

for tool in uv pnpm node; do
  command -v "$tool" >/dev/null 2>&1 || die "'$tool' is not on PATH. See CLAUDE.md for the toolchain."
done

# ── dependencies ──────────────────────────────────────────────────────────
# `uv sync` and `pnpm install` are cheap when everything is already in place,
# but not free, so by default they run only when the tree is missing.
sync_service_deps() { echo "→ uv sync (apps/service)"; (cd apps/service && uv sync --locked); }
sync_web_deps() { echo "→ pnpm install"; pnpm install --frozen-lockfile; }

case "$INSTALL" in
  always) sync_service_deps; sync_web_deps ;;
  auto)
    [[ -d apps/service/.venv ]] || sync_service_deps
    [[ -d apps/desktop/node_modules ]] || sync_web_deps
    ;;
  never)
    [[ -d apps/service/.venv ]] || die "apps/service/.venv is missing; run without --no-install"
    [[ -d apps/desktop/node_modules ]] || die "node_modules is missing; run without --no-install"
    ;;
esac

# ── ports ─────────────────────────────────────────────────────────────────
# Vite is configured with strictPort, so a busy web port aborts rather than
# silently moving; check both up front and say which process holds it.
# `lsof` and `ss` exit nonzero when they find nothing, which under `pipefail`
# would make "the port is free" look like a script error. Absorbed here.
port_holder() {
  if command -v lsof >/dev/null 2>&1; then
    { lsof -nP -iTCP:"$1" -sTCP:LISTEN -F c 2>/dev/null || true; } | sed -n 's/^c//p' | head -1
  elif command -v ss >/dev/null 2>&1; then
    { ss -ltnHp "sport = :$1" 2>/dev/null || true; } | sed -n 's/.*users:(("\([^"]*\)".*/\1/p' | head -1
  fi
}
for spec in "$API_PORT:service" "$WEB_PORT:panel"; do
  port="${spec%%:*}"; what="${spec##*:}"
  holder="$(port_holder "$port")"
  if [[ -n "$holder" ]]; then
    die "port $port ($what) is already in use by '$holder'"
  fi
done

# ── processes ─────────────────────────────────────────────────────────────
SERVICE_PID=""
WEB_PID=""

# Job control, so each server below starts as its own process-group leader.
# Neither server is one process: `uv run` spawns the interpreter beneath it and
# `pnpm exec` spawns node. Signalling only the child this script knows about
# leaves the grandchild alive and still holding the port — the next run then
# fails the port check against a server nobody can see.
set -m

# Signal the whole group, falling back to the single process if it turned out
# not to lead one.
stop_group() {
  local pid="$1"
  [[ -n "$pid" ]] || return 0
  kill "-$2" -- "-$pid" 2>/dev/null || kill "-$2" "$pid" 2>/dev/null || true
}

alive() {
  local pid="$1"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

shutdown() {
  trap - INT TERM EXIT
  echo ""
  echo "→ stopping"
  stop_group "$WEB_PID" TERM
  stop_group "$SERVICE_PID" TERM

  # A moment to close listeners and flush, then insist. Without the second
  # pass a server that ignores TERM would keep the port for the next run.
  local waited=0
  while { alive "$WEB_PID" || alive "$SERVICE_PID"; } && [[ $waited -lt 20 ]]; do
    sleep 0.25
    waited=$((waited + 1))
  done
  stop_group "$WEB_PID" KILL
  stop_group "$SERVICE_PID" KILL
  wait 2>/dev/null || true
}
trap shutdown INT TERM EXIT

echo "→ service tier on ${HOST}:${API_PORT}"
service_args=(uv run uvicorn app.main:app --host "$HOST" --port "$API_PORT")
if [[ "$RELOAD" == 1 ]]; then service_args+=(--reload); fi
(cd apps/service && exec "${service_args[@]}") &
SERVICE_PID=$!

# Wait for the service before starting the UI, so the first page load does not
# race the proxy target. FastAPI always serves the schema, so that is the
# readiness probe — there is no dedicated health route.
probe="http://127.0.0.1:${API_PORT}/openapi.json"
for _ in $(seq 1 60); do
  if command -v curl >/dev/null 2>&1; then
    curl -fsS -o /dev/null "$probe" 2>/dev/null && break
  else
    node -e "fetch('$probe').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))" && break
  fi
  kill -0 "$SERVICE_PID" 2>/dev/null || die "the service exited during startup (see the log above)"
  sleep 0.5
done

# The UI talks to the service through the proxy on its own origin. A bare "/"
# is the same-origin base URL: the generated client trims the trailing slash
# before joining the path.
# ── where to point a browser ──────────────────────────────────────────────
lan_addresses() {
  if command -v ip >/dev/null 2>&1; then
    ip -4 -o addr show scope global 2>/dev/null | awk '{print $4}' | cut -d/ -f1
  elif command -v ifconfig >/dev/null 2>&1; then
    { ifconfig 2>/dev/null || true; } | awk '/inet /{print $2}' | grep -v '^127\.' || true
  fi
}

export VITE_SERVICE_BASE_URL=/
export ELICTA_SERVICE_URL="http://127.0.0.1:${API_PORT}"

SCHEME=http
if [[ "$HTTPS" == 1 ]]; then
  command -v openssl >/dev/null 2>&1 || die "--https needs openssl on PATH"
  CERT_DIR=".certs"
  CERT="${CERT_DIR}/panel.crt"
  KEY="${CERT_DIR}/panel.key"
  mkdir -p "$CERT_DIR"
  # Regenerated when missing or expired. The SAN list carries every address
  # this machine answers on, because a browser matches the certificate against
  # the address in the bar — a certificate for `localhost` alone is rejected
  # on the LAN address, which is exactly the case this flag exists for.
  if ! openssl x509 -checkend 86400 -noout -in "$CERT" >/dev/null 2>&1; then
    echo "→ generating a self-signed certificate in ${CERT_DIR}/"
    sans="DNS:localhost,IP:127.0.0.1,IP:::1"
    while read -r addr; do
      [[ -n "$addr" ]] && sans="${sans},IP:${addr}"
    done < <(lan_addresses)
    openssl req -x509 -newkey rsa:2048 -nodes -days 365 \
      -keyout "$KEY" -out "$CERT" -subj "/CN=Elicta local" \
      -addext "subjectAltName=${sans}" >/dev/null 2>&1 ||
      die "openssl could not generate a certificate"
  fi
  export ELICTA_HTTPS_CERT="$PWD/$CERT"
  export ELICTA_HTTPS_KEY="$PWD/$KEY"
  SCHEME=https
fi

if [[ "$MODE" == prod ]]; then
  echo "→ building the panel bundle"
  pnpm --filter elicta-desktop build
  echo "→ panel (production bundle) on ${HOST}:${WEB_PORT}"
  pnpm --filter elicta-desktop exec vite preview --host "$HOST" --port "$WEB_PORT" --strictPort &
else
  echo "→ panel (dev server) on ${HOST}:${WEB_PORT}"
  pnpm --filter elicta-desktop exec vite --host "$HOST" --port "$WEB_PORT" --strictPort &
fi
WEB_PID=$!

sleep 1
echo ""
echo "  Elicta is up."
echo "    on this machine   ${SCHEME}://localhost:${WEB_PORT}"
if [[ "$HOST" == "0.0.0.0" || "$HOST" == "::" ]]; then
  while read -r addr; do
    if [[ -n "$addr" ]]; then
      echo "    on the network    ${SCHEME}://${addr}:${WEB_PORT}"
    fi
  done < <(lan_addresses)
fi
echo "    service, direct   http://localhost:${API_PORT}/docs"
echo ""
echo "  Anything the panel needs from the model runs on credentials entered in"
echo "  the app's Settings screen; without them the API still serves, and the"
echo "  stages that need a model report what is missing."
echo "  Ctrl-C stops both processes."
echo ""

# Exit as soon as either process does, rather than leaving half a system up.
# Polled rather than `wait -n`, which macOS's bash 3.2 does not have.
while kill -0 "$SERVICE_PID" 2>/dev/null && kill -0 "$WEB_PID" 2>/dev/null; do
  sleep 1
done
