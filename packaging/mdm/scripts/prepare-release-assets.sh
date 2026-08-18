#!/usr/bin/env bash
# prepare-release-assets.sh — assemble the NFR-3.6 fallback release bundle
#
# Usage: prepare-release-assets.sh <input-dir> <output-dir>
#
# <input-dir> is searched recursively for build artifacts produced by the
# existing CI pipeline (.github/workflows/build.yml + sign-macos.yml): the
# notarised macOS .dmg and the signed Windows .msi installer(s). MDM push
# (PRD NFR-3.5) is the preferred install path; this script guarantees the
# .dmg and MSI fallback (NFR-3.6) actually exists before anything is
# published, so a broken or partial CI run fails loudly here instead of
# silently shipping a release missing one platform.
#
# On success, <output-dir> contains the located installers plus a
# SHA256SUMS.txt covering them, ready to attach to a GitHub Release.

set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $(basename "$0") <input-dir> <output-dir>" >&2
  exit 2
fi

input_dir="$1"
output_dir="$2"

if [[ ! -d "$input_dir" ]]; then
  echo "error: input directory not found: $input_dir" >&2
  exit 1
fi

mkdir -p "$output_dir"

mapfile -d '' dmg_files < <(find "$input_dir" -type f -name '*.dmg' -print0 | sort -z)
mapfile -d '' msi_files < <(find "$input_dir" -type f -name '*.msi' -print0 | sort -z)

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

for src in "${dmg_files[@]}" "${msi_files[@]}"; do
  cp "$src" "$output_dir/$(basename "$src")"
done

(
  cd "$output_dir"
  sha256sum -- *.dmg *.msi > SHA256SUMS.txt
)

echo "prepared release assets in $output_dir:"
ls -1 "$output_dir"
