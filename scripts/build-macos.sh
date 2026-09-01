#!/usr/bin/env bash
# Build the Elicta desktop app on this Mac, without CI.
#
# Default is a host-architecture build, which is what you want for testing on
# your own machine: it is roughly half the work of the universal build CI
# produces, because it compiles the Rust workspace once instead of twice.
# Pass --universal for the shippable arm64+x86_64 bundle, and --no-bump to
# rebuild the current version rather than the next one.
#
# Output lands in apps/desktop/src-tauri/target/<triple>/release/bundle/
# as both Elicta.app and a .dmg.

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

# Scanned rather than read off `$1`: with two flags to pass, checking only the
# first position means `--no-bump --universal` silently builds one
# architecture, which is the kind of thing nobody notices until the bundle is
# on somebody else's Mac.
universal=0
keep_version=0
for arg in "$@"; do
  case "$arg" in
    --universal) universal=1 ;;
    --no-bump|--keep) keep_version=1 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "build-macos: unknown option $arg" >&2; exit 2 ;;
  esac
done

fail() { echo "error: $*" >&2; exit 1; }

# --- preflight -------------------------------------------------------------
# Each check below corresponds to a failure that already happened once, and
# each is far cheaper to catch here than twenty minutes into a compile.

[[ "$(uname -s)" == "Darwin" ]] || fail "macOS only -- a .dmg needs hdiutil, lipo and codesign, which exist only here."

command -v xcrun >/dev/null || fail "Xcode command line tools not found. Install Xcode from the App Store, then: xcode-select --install"

sdk="$(xcrun --sdk macosx --show-sdk-version)"
sdk_major="${sdk%%.*}"
if (( sdk_major < 26 )); then
  fail "macOS SDK ${sdk} is too old. The screencapturekit dependency vendors a Swift
       bridge over Metal 4 (MTLSamplerDescriptor.reductionMode and friends) that
       needs SDK 26 or newer -- SDK 15 compiles most of it and then fails.
       Update Xcode, and if you have several installed point at the new one:
         sudo xcode-select -s /Applications/Xcode.app"
fi

command -v node >/dev/null || fail "Node not found. Node 22.13+ is required (pnpm 11 uses the node:sqlite builtin)."
node_major="$(node -p 'process.versions.node.split(".")[0]')"
(( node_major >= 22 )) || fail "Node $(node -v) is too old -- pnpm 11 needs 22.13+, and fails with ERR_UNKNOWN_BUILTIN_MODULE below that."

command -v pnpm >/dev/null || fail "pnpm not found. Install with: corepack enable && corepack prepare --activate"
command -v cargo >/dev/null || fail "cargo not found. Install from https://rustup.rs"
# The service is frozen with PyInstaller into the bundle; without a Python
# there is no service to ship, and the bundler's own error names a missing
# binary rather than a missing interpreter.
command -v python3 >/dev/null || fail "python3 not found. The bundled service is frozen from it."

if (( universal )); then
  target="universal-apple-darwin"
  for t in aarch64-apple-darwin x86_64-apple-darwin; do
    rustup target list --installed | grep -qx "$t" || {
      echo "adding missing Rust target $t"
      rustup target add "$t"
    }
  done
else
  case "$(uname -m)" in
    arm64) target="aarch64-apple-darwin" ;;
    x86_64) target="x86_64-apple-darwin" ;;
    *) fail "unrecognised architecture: $(uname -m)" ;;
  esac
  rustup target list --installed | grep -qx "$target" || rustup target add "$target"
fi

echo "==> SDK ${sdk}, Node $(node -v), target ${target}"

# --- build -----------------------------------------------------------------
# @tauri-apps/cli is a devDependency, so this uses the same pinned bundler
# version CI does rather than a separately installed cargo-tauri.
pnpm install --frozen-lockfile

# The service ships inside the bundle, so it has to exist before the bundler
# looks for it. Declared in `tauri.conf.json` as an external binary, a missing
# one stops the build outright — which is the right failure, and a confusing
# one to meet without knowing this step exists.
#
# Skipped when the binary is already there and newer than the service, because
# freezing takes minutes and most rebuilds here are of the front end.
# Its own version number, so the artifact on disk says which build it is.
# Every `.dmg` was `Elicta_0.1.0_aarch64.dmg` and a rebuild overwrote the last
# one — and an install from days earlier shadowing a fresh build cost most of
# an afternoon with "which one is this?" having no answer anywhere.
#
# Before the pruner, so the bundles it clears are the ones from the version
# just superseded. `--no-bump` rebuilds the same number, for re-signing or
# after a bundler run that failed.
if (( keep_version )); then
  echo "==> keeping version $(./scripts/bump-version.sh --no-bump)"
else
  ./scripts/bump-version.sh > /dev/null
  echo "==> building version $(./scripts/bump-version.sh --no-bump)"
fi

# Everything a previous build left behind that this one would trip over —
# most of all a frozen service older than something it was built from, which
# is deleted here so the check below refreezes rather than reusing it. The
# predicate lives in the pruner because that is where it can be kept in step
# with what the freeze actually reads: every Python file under `apps/service`
# missed `uv.lock`, which decides which dependency versions go in, and the
# freeze script, which decides the hidden imports and the entry point.
#
# Nothing of the operator's is touched. An install in /Applications and a
# running service are named, with the command to deal with each.
./scripts/prune-stale-builds.sh

sidecar="apps/desktop/src-tauri/binaries/elicta-service-${target}"
if [[ -x "$sidecar" ]]; then
  echo "==> reusing the frozen service at $sidecar"
else
  ./scripts/build-service-sidecar.sh "$target"
fi

pnpm --filter elicta-desktop exec tauri build --target "$target"

bundle_dir="apps/desktop/src-tauri/target/${target}/release/bundle"
app="$(find "$bundle_dir/macos" -maxdepth 1 -name '*.app' | head -n1)"
dmg="$(find "$bundle_dir/dmg" -maxdepth 1 -name '*.dmg' | head -n1)"

# --- verify it can actually be loaded --------------------------------------
# The published 0.1.0 build passed every shape check -- right architectures,
# valid signature -- and still could not start, because it depended on
# @rpath/libswift_Concurrency.dylib with no LC_RPATH to resolve it against and
# dyld gave up before main(). It surfaced only as "Elicta quit unexpectedly".
exe="$app/Contents/MacOS/$(/usr/libexec/PlistBuddy -c 'Print :CFBundleExecutable' "$app/Contents/Info.plist")"
rpaths="$(otool -l "$exe" | grep -c LC_RPATH || true)"
unresolvable="$(otool -L "$exe" | tail -n +2 | awk '{print $1}' | grep '^@rpath/' || true)"
if [[ -n "$unresolvable" && "$rpaths" -eq 0 ]]; then
  echo "error: this bundle cannot be loaded by dyld -- it needs these with no LC_RPATH:" >&2
  echo "$unresolvable" | sed 's/^/    /' >&2
  exit 1
fi

echo
echo "app: $app"
echo "dmg: $dmg"
echo
echo "Run it straight from the build tree -- no quarantine flag, so no Gatekeeper prompt:"
echo "    open \"$app\""
echo
echo "Seeing stderr (a Rust panic prints here, but not into the crash dialog):"
echo "    \"$exe\""
