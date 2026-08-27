#!/usr/bin/env bash
# Clear what a previous build left behind, before the next one trips over it.
#
# Two kinds of staleness bit this project in one afternoon, and neither
# announced itself.
#
# A copy of the app installed in /Applications weeks earlier had its service on
# port 8000. The shell starts its own only when nothing is already answering,
# so every rebuild launched from the build tree talked to the old service: a
# panel built minutes ago against an API from another version, with the symptom
# appearing as endpoints answering 404 that answered 200 in-process against the
# same database. The shell refuses to adopt a stranger now, but refusing is not
# clearing -- somebody still has to find the thing and stop it.
#
# And the frozen service is reused unless something it was built from is newer.
# "Something" was every Python file under apps/service, which leaves out the two
# inputs that decide what actually goes into the binary: the locked dependency
# set the freezer verifies the environment against, and the freeze script
# itself. Change either and the build silently ships the previous service.
#
# What this removes and what it only reports is the whole design. Build outputs
# are regenerable and go without asking. An install in /Applications is
# somebody's property and a running process is somebody's session; both are
# named, with the command to deal with them, and left alone unless asked.
#
#   scripts/prune-stale-builds.sh                    # prune outputs, report the rest
#   scripts/prune-stale-builds.sh --stop-running     # also stop foreign services
#   scripts/prune-stale-builds.sh --remove-installed # also delete /Applications/Elicta.app
#   scripts/prune-stale-builds.sh --dry-run          # say what would go, remove nothing
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

STOP_RUNNING=0
REMOVE_INSTALLED=0
DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --stop-running) STOP_RUNNING=1 ;;
    --remove-installed) REMOVE_INSTALLED=1 ;;
    --dry-run) DRY_RUN=1 ;;
    -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
    *) echo "prune: unknown option $arg" >&2; exit 2 ;;
  esac
done

pruned=0
reported=0

remove() {
  # One place that decides whether a removal happens, so --dry-run cannot be
  # honoured in some branches and forgotten in others.
  local what="$1"
  if [ "$DRY_RUN" = "1" ]; then
    echo "    would remove: $what"
  else
    rm -rf "$what"
    echo "    removed: $what"
  fi
  pruned=$((pruned + 1))
}

note() {
  echo "    $1"
  reported=$((reported + 1))
}

# --- the frozen service, against everything it is built from ----------------
# Expressed as pruning rather than as a condition in the build script: a
# sidecar that is out of date is deleted, and the build's own "is there one?"
# check then refreezes. One rule, in one place, instead of a predicate that has
# to be kept in step with what the freeze actually reads.
echo "==> frozen service"
freeze_inputs() {
  # Everything whose change alters the binary. `uv.lock` because the freeze
  # script refuses to build an environment that disagrees with it, so the lock
  # decides which versions are inside; `pyproject.toml` for the same reason;
  # and the freeze script because it chooses the hidden imports, the exclusions
  # and the entry point.
  find apps/service -name '*.py' -not -path '*/.venv/*' -not -path '*/__pycache__/*'
  for extra in apps/service/uv.lock apps/service/pyproject.toml \
               scripts/build-service-sidecar.sh; do
    [ -f "$extra" ] && echo "$extra"
  done
}

shopt -s nullglob
for sidecar in apps/desktop/src-tauri/binaries/elicta-service-*; do
  newer="$(freeze_inputs | while read -r input; do
    [ "$input" -nt "$sidecar" ] && { echo "$input"; break; }
    true
  done)"
  if [ -n "$newer" ]; then
    echo "    out of date (\"$newer\" is newer)"
    remove "$sidecar"
  else
    echo "    current: $sidecar"
  fi
done

# --- bundles from a version that is no longer being built -------------------
# The bundler overwrites the current version's outputs and leaves every other
# version's in place, so these accumulate silently and the newest is not
# obviously the newest.
echo "==> bundles from other versions"
version="$(python3 -c "
import json, pathlib
print(json.loads(pathlib.Path('apps/desktop/src-tauri/tauri.conf.json').read_text())['version'])
" 2>/dev/null || true)"
if [ -z "$version" ]; then
  note "could not read the version from tauri.conf.json; nothing pruned here"
else
  for artifact in apps/desktop/src-tauri/target/*/release/bundle/dmg/*.dmg \
                  apps/desktop/src-tauri/target/*/release/bundle/macos/*.app; do
    case "$(basename "$artifact")" in
      *"$version"*|Elicta.app) : ;;   # the current version, and the .app the bundler always names plainly
      *) remove "$artifact" ;;
    esac
  done
fi

# --- a service on the port that is not this build's -------------------------
# Named rather than killed: a running service belongs to somebody's session,
# and the app it is serving may be in a meeting.
echo "==> running services"
mine="$ROOT/apps/desktop/src-tauri/target"
while read -r pid path; do
  [ -z "$pid" ] && continue
  # Anchored on the executable, not on the word: an unanchored `pgrep -f`
  # matches any command line containing the name — including the shell that
  # was writing this script, which is how the first run reported three hundred
  # "running services".
  case "$path" in
    */elicta-service) : ;;
    *) continue ;;
  esac
  [ "$pid" = "$$" ] && continue
  case "$path" in
    "$mine"/*) echo "    this build's: $path (pid $pid)" ;;
    *)
      if [ "$STOP_RUNNING" = "1" ] && [ "$DRY_RUN" != "1" ]; then
        kill "$pid" 2>/dev/null && echo "    stopped: $path (pid $pid)"
        pruned=$((pruned + 1))
      else
        note "another build's service is running: $path (pid $pid)"
        note "  stop it with: kill $pid    (or re-run with --stop-running)"
      fi
      ;;
  esac
done < <(pgrep -alf '/elicta-service' 2>/dev/null | awk '{print $1, $2}')

# --- an installed copy older than what is being built -----------------------
# Reported, never removed without being asked: this is an install, not a build
# output, and deleting somebody's application behind their back is not pruning.
echo "==> installed copy"
installed="/Applications/Elicta.app"
newest_build="$(find apps/desktop/src-tauri/target -maxdepth 5 -name 'Elicta.app' -print 2>/dev/null | head -n1)"
if [ ! -d "$installed" ]; then
  echo "    none"
elif [ -n "$newest_build" ] && [ "$newest_build" -nt "$installed" ]; then
  if [ "$REMOVE_INSTALLED" = "1" ]; then
    remove "$installed"
  else
    note "$installed is older than the build tree's copy"
    note "  replace it from the .dmg, or re-run with --remove-installed"
  fi
else
  echo "    current: $installed"
fi

echo "==> pruned $pruned, reported $reported"
