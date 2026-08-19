#!/usr/bin/env bash
# Install a pre-commit hook that runs the handbook check.
#
# Opt-in on purpose: a repository should not install git hooks behind your
# back. CI enforces the same check regardless, so this only moves the
# feedback earlier.
#
#   bash handbook/tools/install-git-hooks.sh
#   git commit --no-verify     # to skip it once

set -euo pipefail

root="$(git rev-parse --show-toplevel)"
hooks="$(git rev-parse --git-path hooks)"
target="$hooks/pre-commit"

if [ -e "$target" ] && ! grep -q "handbook/tools/gen.py" "$target"; then
  echo "refusing to overwrite an existing $target" >&2
  echo "add this line to it yourself:" >&2
  echo '  python3 handbook/tools/gen.py check || exit 1' >&2
  exit 1
fi

mkdir -p "$hooks"
cat > "$target" <<'HOOK'
#!/usr/bin/env bash
# Installed by handbook/tools/install-git-hooks.sh
set -euo pipefail
root="$(git rev-parse --show-toplevel)"
if ! python3 "$root/handbook/tools/gen.py" check; then
  echo >&2
  echo "The handbook is stale. Run: python3 handbook/tools/gen.py build" >&2
  echo "Commit anyway with: git commit --no-verify" >&2
  exit 1
fi
HOOK
chmod +x "$target"
echo "installed $target"
