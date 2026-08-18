#!/usr/bin/env bash
# test-prepare-release-assets.sh — smoke tests for prepare-release-assets.sh
#
# Runs entirely against temp directories; makes no network calls and touches
# no real build output. Usage: ./test-prepare-release-assets.sh

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
under_test="$script_dir/prepare-release-assets.sh"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

failures=0

assert_success() {
  local desc="$1"; shift
  if "$@" >"$work/last-stdout" 2>"$work/last-stderr"; then
    echo "ok - $desc"
  else
    echo "FAIL - $desc (exit $?)" >&2
    cat "$work/last-stderr" >&2
    failures=$((failures + 1))
  fi
}

assert_failure() {
  local desc="$1"; shift
  if "$@" >"$work/last-stdout" 2>"$work/last-stderr"; then
    echo "FAIL - $desc (expected non-zero exit, got 0)" >&2
    failures=$((failures + 1))
  else
    echo "ok - $desc"
  fi
}

# --- happy path: one dmg, two msi (x64 + arm64), app bundle + exes --------
happy_in="$work/happy/in"
happy_out="$work/happy/out"
mkdir -p "$happy_in/elicta-macos-notarized/Elicta.app/Contents/MacOS" \
  "$happy_in/elicta-windows-x64" "$happy_in/elicta-windows-arm64"
echo "dmg-bytes" > "$happy_in/elicta-macos-notarized/Elicta_1.0.0_universal.dmg"
echo "macho-bytes" > "$happy_in/elicta-macos-notarized/Elicta.app/Contents/MacOS/Elicta"
echo "msi-x64-bytes" > "$happy_in/elicta-windows-x64/Elicta_1.0.0_x64.msi"
echo "nsis-x64-bytes" > "$happy_in/elicta-windows-x64/Elicta_1.0.0_x64-setup.exe"
echo "msi-arm64-bytes" > "$happy_in/elicta-windows-arm64/Elicta_1.0.0_arm64.msi"
echo "nsis-arm64-bytes" > "$happy_in/elicta-windows-arm64/Elicta_1.0.0_arm64-setup.exe"

assert_success "succeeds when dmg, both msi arches, app bundle and exes are present" \
  "$under_test" "$happy_in" "$happy_out"

for expected in Elicta_1.0.0_universal.dmg Elicta_1.0.0_x64.msi Elicta_1.0.0_arm64.msi SHA256SUMS.txt EDR-WHITELIST.txt; do
  if [[ ! -f "$happy_out/$expected" ]]; then
    echo "FAIL - expected output file missing: $expected" >&2
    failures=$((failures + 1))
  fi
done

if [[ -f "$happy_out/SHA256SUMS.txt" ]] && ! (cd "$happy_out" && sha256sum -c SHA256SUMS.txt >/dev/null 2>&1); then
  echo "FAIL - SHA256SUMS.txt does not verify against the copied artifacts" >&2
  failures=$((failures + 1))
fi

if [[ -f "$happy_out/EDR-WHITELIST.txt" ]]; then
  grep -q "NFR-3.7" "$happy_out/EDR-WHITELIST.txt" || {
    echo "FAIL - EDR-WHITELIST.txt does not reference NFR-3.7" >&2
    failures=$((failures + 1))
  }

  expected_app_hash="$(sha256sum "$happy_in/elicta-macos-notarized/Elicta.app/Contents/MacOS/Elicta" | awk '{print $1}')"
  grep -q "$expected_app_hash" "$happy_out/EDR-WHITELIST.txt" || {
    echo "FAIL - EDR-WHITELIST.txt is missing the macOS app binary hash" >&2
    failures=$((failures + 1))
  }

  expected_exe_hash="$(sha256sum "$happy_in/elicta-windows-x64/Elicta_1.0.0_x64-setup.exe" | awk '{print $1}')"
  grep -q "$expected_exe_hash" "$happy_out/EDR-WHITELIST.txt" || {
    echo "FAIL - EDR-WHITELIST.txt is missing the Windows installer exe hash" >&2
    failures=$((failures + 1))
  }
fi

# --- missing dmg must fail loudly, not silently produce a partial release --
missing_dmg_in="$work/missing-dmg/in"
mkdir -p "$missing_dmg_in/elicta-windows-x64"
echo "msi-bytes" > "$missing_dmg_in/elicta-windows-x64/Elicta_1.0.0_x64.msi"

assert_failure "fails when no .dmg is present" \
  "$under_test" "$missing_dmg_in" "$work/missing-dmg/out"
grep -q "no .dmg artifact found" "$work/last-stderr" || {
  echo "FAIL - missing-dmg error message did not mention the .dmg gap" >&2
  failures=$((failures + 1))
}

# --- missing msi must fail loudly ------------------------------------------
missing_msi_in="$work/missing-msi/in"
mkdir -p "$missing_msi_in/elicta-macos-notarized"
echo "dmg-bytes" > "$missing_msi_in/elicta-macos-notarized/Elicta_1.0.0_universal.dmg"

assert_failure "fails when no .msi is present" \
  "$under_test" "$missing_msi_in" "$work/missing-msi/out"
grep -q "no .msi artifact found" "$work/last-stderr" || {
  echo "FAIL - missing-msi error message did not mention the .msi gap" >&2
  failures=$((failures + 1))
}

# --- more than one dmg is ambiguous and must fail ---------------------------
dup_dmg_in="$work/dup-dmg/in"
mkdir -p "$dup_dmg_in/a" "$dup_dmg_in/b"
echo "dmg-bytes-1" > "$dup_dmg_in/a/Elicta_1.0.0_universal.dmg"
echo "dmg-bytes-2" > "$dup_dmg_in/b/Elicta_1.0.0-old_universal.dmg"
mkdir -p "$dup_dmg_in/c"
echo "msi-bytes" > "$dup_dmg_in/c/Elicta_1.0.0_x64.msi"

assert_failure "fails when more than one .dmg is present" \
  "$under_test" "$dup_dmg_in" "$work/dup-dmg/out"

# --- missing macOS .app bundle must fail loudly (NFR-3.7 needs its hash) ---
missing_app_in="$work/missing-app/in"
mkdir -p "$missing_app_in/elicta-macos-notarized" "$missing_app_in/elicta-windows-x64"
echo "dmg-bytes" > "$missing_app_in/elicta-macos-notarized/Elicta_1.0.0_universal.dmg"
echo "msi-bytes" > "$missing_app_in/elicta-windows-x64/Elicta_1.0.0_x64.msi"
echo "nsis-bytes" > "$missing_app_in/elicta-windows-x64/Elicta_1.0.0_x64-setup.exe"

assert_failure "fails when no .app bundle is present" \
  "$under_test" "$missing_app_in" "$work/missing-app/out"
grep -q "no .app bundle found" "$work/last-stderr" || {
  echo "FAIL - missing-app error message did not mention the .app gap" >&2
  failures=$((failures + 1))
}

# --- missing Windows .exe must fail loudly (NFR-3.7 needs its hash) --------
missing_exe_in="$work/missing-exe/in"
mkdir -p "$missing_exe_in/elicta-macos-notarized/Elicta.app/Contents/MacOS" "$missing_exe_in/elicta-windows-x64"
echo "dmg-bytes" > "$missing_exe_in/elicta-macos-notarized/Elicta_1.0.0_universal.dmg"
echo "macho-bytes" > "$missing_exe_in/elicta-macos-notarized/Elicta.app/Contents/MacOS/Elicta"
echo "msi-bytes" > "$missing_exe_in/elicta-windows-x64/Elicta_1.0.0_x64.msi"

assert_failure "fails when no Windows .exe is present" \
  "$under_test" "$missing_exe_in" "$work/missing-exe/out"
grep -q "no Windows installer .exe found" "$work/last-stderr" || {
  echo "FAIL - missing-exe error message did not mention the .exe gap" >&2
  failures=$((failures + 1))
}

if [[ "$failures" -gt 0 ]]; then
  echo "$failures test(s) failed" >&2
  exit 1
fi

echo "all tests passed"
