#!/usr/bin/env bash
# Give this build its own version number.
#
# Every `.dmg` was `Elicta_0.1.0_aarch64.dmg`, so a rebuild overwrote the last
# one and no artifact on disk said which build it was. That matters more than
# it looks: an install from days earlier shadowing a fresh build cost most of
# an afternoon, and "which one is this?" had no answer anywhere.
#
# Three files carry the version and have to move together. `tauri.conf.json`
# names the bundle and is what the updater compares; `Cargo.toml` versions the
# shell binary; `package.json` is what `pnpm` reports. Two agreeing and one not
# is a build whose artifact and whose binary disagree about what they are.
#
#   scripts/bump-version.sh              # patch + 1
#   scripts/bump-version.sh --set 0.2.0  # a number you choose
#   scripts/bump-version.sh --no-bump    # print the current one, change nothing
#   scripts/bump-version.sh --minor      # minor + 1, patch to 0
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

TAURI="apps/desktop/src-tauri/tauri.conf.json"
CARGO="apps/desktop/src-tauri/Cargo.toml"
PACKAGE="apps/desktop/package.json"

WANT=""
PART="patch"
BUMP=1
while [ $# -gt 0 ]; do
  case "$1" in
    --set) WANT="${2:-}"; shift 2 ;;
    --minor) PART="minor"; shift ;;
    --major) PART="major"; shift ;;
    --no-bump|--keep) BUMP=0; shift ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "bump-version: unknown option $1" >&2; exit 2 ;;
  esac
done

current="$(python3 -c "
import json, pathlib
print(json.loads(pathlib.Path('$TAURI').read_text())['version'])
")"

if [ "$BUMP" = "0" ] && [ -z "$WANT" ]; then
  echo "$current"
  exit 0
fi

next="$(python3 - "$current" "$WANT" "$PART" <<'PY'
import re
import sys

current, want, part = sys.argv[1], sys.argv[2], sys.argv[3]
if want:
    if not re.fullmatch(r"\d+\.\d+\.\d+", want):
        raise SystemExit(f"bump-version: not a version: {want}")
    print(want)
    raise SystemExit(0)

match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", current)
if match is None:
    # Refused rather than guessed. Inventing a number for a version this
    # cannot read would stamp a bundle with something nobody chose.
    raise SystemExit(f"bump-version: cannot read the current version: {current!r}")

major, minor, patch = (int(part) for part in match.groups())
if part == "major":
    major, minor, patch = major + 1, 0, 0
elif part == "minor":
    minor, patch = minor + 1, 0
else:
    patch += 1
print(f"{major}.{minor}.{patch}")
PY
)"

python3 - "$current" "$next" "$TAURI" "$CARGO" "$PACKAGE" <<'PY'
import json
import pathlib
import re
import sys

current, nxt, tauri_path, cargo_path, package_path = sys.argv[1:6]

# Each file is edited by its own rule rather than by a blanket search and
# replace: `Cargo.toml` has a dependency section full of version strings, and
# rewriting every match of the current version would move those too.
for path in (tauri_path, package_path):
    file = pathlib.Path(path)
    data = json.loads(file.read_text())
    data["version"] = nxt
    # Rewritten rather than dumped whole: `json.dumps` would reformat the file
    # and bury a one-line change in a hundred.
    file.write_text(
        re.sub(
            r'("version"\s*:\s*)"%s"' % re.escape(current),
            r'\g<1>"%s"' % nxt,
            file.read_text(),
            count=1,
        )
    )

cargo = pathlib.Path(cargo_path)
# Anchored to the start of a line and taken once: only the package's own
# `version =` sits at column zero before the first section ends.
cargo.write_text(
    re.sub(
        r'^version\s*=\s*"%s"' % re.escape(current),
        'version = "%s"' % nxt,
        cargo.read_text(),
        count=1,
        flags=re.MULTILINE,
    )
)
PY

echo "==> version $current -> $next"
echo "$next"
