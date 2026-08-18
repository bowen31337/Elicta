#!/usr/bin/env bash
# test-generate-pppc-profile.sh — smoke tests for generate-pppc-profile.sh
#
# Runs entirely against a temp directory; makes no network calls. Validates
# the rendered profile with Python's plistlib rather than macOS-only
# `plutil`, so it also runs on Linux CI. Usage:
#   ./packaging/mdm/scripts/test-generate-pppc-profile.sh

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
under_test="$script_dir/generate-pppc-profile.sh"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

failures=0

assert_failure() {
  local desc="$1"; shift
  if "$@" >"$work/last-stdout" 2>"$work/last-stderr"; then
    echo "FAIL - $desc (expected non-zero exit, got 0)" >&2
    failures=$((failures + 1))
  else
    echo "ok - $desc"
  fi
}

check() {
  local desc="$1" condition="$2"
  if [[ "$condition" == "true" ]]; then
    echo "ok - $desc"
  else
    echo "FAIL - $desc" >&2
    failures=$((failures + 1))
  fi
}

# --- missing TEAM_ID must fail loudly, not emit an unenforceable profile ---
assert_failure "fails when TEAM_ID is not set" \
  env -u TEAM_ID "$under_test" "$work/should-not-exist.mobileconfig"
grep -q "TEAM_ID must be set" "$work/last-stderr" || {
  echo "FAIL - missing-TEAM_ID error message did not mention TEAM_ID" >&2
  failures=$((failures + 1))
}

# --- happy path: default bundle id, explicit team id -----------------------
happy_out="$work/happy/Elicta-PPPC.mobileconfig"
TEAM_ID="ABCDE12345" PROFILE_UUID="11111111-1111-1111-1111-111111111111" \
  TCC_PAYLOAD_UUID="22222222-2222-2222-2222-222222222222" \
  "$under_test" "$happy_out" >"$work/last-stdout"

check "profile file was created" "$([[ -f "$happy_out" ]] && echo true || echo false)"

report="$(python3 - "$happy_out" <<'PY'
import plistlib
import sys

path = sys.argv[1]
with open(path, "rb") as f:
    profile = plistlib.load(f)

ok = True

def require(cond, msg):
    global ok
    if not cond:
        print(f"CHECK-FAIL: {msg}")
        ok = False

require(profile.get("PayloadType") == "Configuration", "top-level PayloadType must be Configuration")
require(profile.get("PayloadScope") == "System", "PayloadScope must be System (PPPC is ignored otherwise)")
require(profile.get("PayloadUUID") == "11111111-1111-1111-1111-111111111111", "top-level PayloadUUID not applied")
require(profile.get("PayloadIdentifier") == "com.elicta.desktop.pppc", "default bundle id not reflected in PayloadIdentifier")

content = profile.get("PayloadContent") or []
require(len(content) == 1, "expected exactly one PayloadContent entry")
tcc = content[0] if content else {}
require(tcc.get("PayloadType") == "com.apple.TCC.configuration-profile-policy", "nested payload must be a TCC policy payload")
require(tcc.get("PayloadUUID") == "22222222-2222-2222-2222-222222222222", "TCC payload UUID not applied")

services = tcc.get("Services") or {}
for service_key in ("Microphone", "ScreenCapture"):
    entries = services.get(service_key) or []
    require(len(entries) == 1, f"expected exactly one {service_key} entry")
    if entries:
        entry = entries[0]
        require(entry.get("Identifier") == "com.elicta.desktop", f"{service_key} Identifier must be the bundle id")
        require(entry.get("IdentifierType") == "bundleID", f"{service_key} IdentifierType must be bundleID")
        require(entry.get("Allowed") is True, f"{service_key} must be Allowed=true (this is the whole point of NFR-3.5)")
        req = entry.get("CodeRequirement", "")
        require("ABCDE12345" in req, f"{service_key} CodeRequirement must reference TEAM_ID")
        require("com.elicta.desktop" in req, f"{service_key} CodeRequirement must reference the bundle id")

print("PASS" if ok else "FAIL")
PY
)"

echo "$report" | grep -v '^CHECK-FAIL' | grep -q '^PASS$' && plist_ok=true || plist_ok=false
if [[ "$plist_ok" == "false" ]]; then
  echo "$report" >&2
fi
check "rendered plist parses and grants Microphone + ScreenCapture per NFR-3.5" "$plist_ok"

# --- custom bundle id / org name are honored --------------------------------
custom_out="$work/custom/Custom.mobileconfig"
TEAM_ID="ZYXWV98765" BUNDLE_ID="com.example.other" ORG_NAME="Example Corp" \
  "$under_test" "$custom_out" >"$work/last-stdout"

grep -q "com.example.other" "$custom_out" || {
  echo "FAIL - custom BUNDLE_ID was not applied" >&2
  failures=$((failures + 1))
}
grep -q "ZYXWV98765" "$custom_out" || {
  echo "FAIL - custom TEAM_ID was not applied to the code requirement" >&2
  failures=$((failures + 1))
}
grep -q "Example Corp" "$custom_out" || {
  echo "FAIL - custom ORG_NAME was not applied" >&2
  failures=$((failures + 1))
}
python3 -c "import plistlib,sys; plistlib.load(open(sys.argv[1],'rb'))" "$custom_out" || {
  echo "FAIL - custom-bundle-id profile is not a valid plist" >&2
  failures=$((failures + 1))
}

if [[ "$failures" -gt 0 ]]; then
  echo "$failures test(s) failed" >&2
  exit 1
fi

echo "all tests passed"
