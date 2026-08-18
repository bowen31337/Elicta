#!/usr/bin/env bash
# prepare-release-assets.sh — assemble the NFR-3.6 fallback release bundle
# and the NFR-3.7 EDR whitelisting record
#
# Usage: prepare-release-assets.sh <input-dir> <output-dir>
#
# <input-dir> is searched recursively for build artifacts produced by the
# existing CI pipeline (.github/workflows/build.yml + sign-macos.yml): the
# notarised macOS .dmg, the notarised macOS .app bundle, and the signed
# Windows .msi / NSIS .exe installer(s). MDM push (PRD NFR-3.5) is the
# preferred install path; this script guarantees:
#
#   - the .dmg and MSI fallback (NFR-3.6) actually exists before anything is
#     published, so a broken or partial CI run fails loudly here instead of
#     silently shipping a release missing one platform.
#   - the binary hashes IT needs to whitelist in EDR/antivirus tooling before
#     pilot (NFR-3.7) are computed and recorded here, rather than left for
#     someone to dig out of a build log after a pilot user gets flagged.
#
# On success, <output-dir> contains:
#   - the located installers (.dmg, .msi)
#   - SHA256SUMS.txt covering those installer packages, for download
#     integrity (NFR-3.6)
#   - EDR-WHITELIST.txt covering the binaries that actually execute after
#     install — the macOS app's Mach-O executable and the Windows installer
#     executable(s) — which is what EDR/antivirus whitelisting policy keys
#     on (NFR-3.7)
#
# ready to attach to a GitHub Release.

set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $(basename "$0") <input-dir> <output-dir>" >&2
  exit 2
fi

input_dir="${1%/}"
output_dir="$2"

if [[ ! -d "$input_dir" ]]; then
  echo "error: input directory not found: $input_dir" >&2
  exit 1
fi

mkdir -p "$output_dir"

mapfile -d '' dmg_files < <(find "$input_dir" -type f -name '*.dmg' -print0 | sort -z)
mapfile -d '' msi_files < <(find "$input_dir" -type f -name '*.msi' -print0 | sort -z)
mapfile -d '' app_bundles < <(find "$input_dir" -type d -name '*.app' -print0 | sort -z)
mapfile -d '' win_exe_files < <(find "$input_dir" -type f -name '*.exe' -print0 | sort -z)

if [[ ${#dmg_files[@]} -eq 0 ]]; then
  echo "error: no .dmg artifact found under $input_dir — macOS fallback distribution (NFR-3.6) is missing" >&2
  exit 1
fi

if [[ ${#dmg_files[@]} -gt 1 ]]; then
  echo "error: expected exactly one .dmg artifact, found ${#dmg_files[@]}:" >&2
  printf '  %s\n' "${dmg_files[@]}" >&2
  exit 1
fi

if [[ ${#msi_files[@]} -eq 0 ]]; then
  echo "error: no .msi artifact found under $input_dir — Windows fallback distribution (NFR-3.6) is missing" >&2
  exit 1
fi

if [[ ${#app_bundles[@]} -eq 0 ]]; then
  echo "error: no .app bundle found under $input_dir — cannot record the macOS binary hash needed for EDR whitelisting (NFR-3.7)" >&2
  exit 1
fi

if [[ ${#app_bundles[@]} -gt 1 ]]; then
  echo "error: expected exactly one .app bundle, found ${#app_bundles[@]}:" >&2
  printf '  %s\n' "${app_bundles[@]}" >&2
  exit 1
fi

if [[ ${#win_exe_files[@]} -eq 0 ]]; then
  echo "error: no Windows installer .exe found under $input_dir — cannot record the Windows binary hash needed for EDR whitelisting (NFR-3.7)" >&2
  exit 1
fi

app_bundle="${app_bundles[0]}"
app_name="$(basename "$app_bundle" .app)"
app_binary="$app_bundle/Contents/MacOS/$app_name"

if [[ ! -f "$app_binary" ]]; then
  echo "error: expected macOS executable not found at $app_binary" >&2
  exit 1
fi

for src in "${dmg_files[@]}" "${msi_files[@]}"; do
  cp "$src" "$output_dir/$(basename "$src")"
done

(
  cd "$output_dir"
  sha256sum -- *.dmg *.msi > SHA256SUMS.txt
)

edr_record="$output_dir/EDR-WHITELIST.txt"
{
  echo "# EDR / endpoint-detection whitelisting record (PRD NFR-3.7)"
  echo "#"
  echo "# An unknown binary opening a microphone or loopback audio stream is"
  echo "# exactly the kind of behaviour EDR/antivirus tooling flags. Submit"
  echo "# the SHA-256 hashes below to your EDR console (Jamf Protect,"
  echo "# CrowdStrike Falcon, Microsoft Defender for Endpoint, etc.) and"
  echo "# confirm whitelisting with IT on both platforms before pilot."
  echo "#"
  echo "# These are the binaries that actually execute after install, which"
  echo "# is what EDR policy keys on — distinct from SHA256SUMS.txt, which"
  echo "# covers installer package integrity (NFR-3.6) for direct downloads."
  echo "#"
  echo "## macOS"
  echo "path: ${app_binary#"$input_dir"/}"
  echo "sha256: $(sha256sum "$app_binary" | awk '{print $1}')"
  echo
  echo "## Windows"
  for exe in "${win_exe_files[@]}"; do
    echo "path: ${exe#"$input_dir"/}"
    echo "sha256: $(sha256sum "$exe" | awk '{print $1}')"
  done
} > "$edr_record"

echo "prepared release assets in $output_dir:"
ls -1 "$output_dir"
