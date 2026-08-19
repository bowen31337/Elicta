#!/usr/bin/env bash
# Rasterise handbook.pdf into page images, for editors that render images
# but not PDFs -- Zed among them. Zed's extension API exposes languages,
# debuggers, themes, icon themes, snippets and MCP servers, and nothing
# that could add a PDF view, so this is the way to read the bound document
# without leaving the editor.
#
#   bash handbook/tools/preview.sh [dpi]
#
# Optional, and deliberately outside the gated pipeline: it needs poppler
# (`pdftoppm`), which the generator itself does not. Output is ignored by
# git -- regenerate it, never commit it.

set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
pdf="$root/handbook/handbook.pdf"
out="$root/handbook/preview"
dpi="${1:-144}"

if ! command -v pdftoppm >/dev/null; then
  echo "pdftoppm not found. Install poppler-utils:" >&2
  echo "  sudo apt-get install -y poppler-utils" >&2
  exit 1
fi

if [ ! -f "$pdf" ]; then
  echo "no $pdf — run: python3 handbook/tools/gen.py build" >&2
  exit 1
fi

rm -rf "$out"
mkdir -p "$out"
pdftoppm -png -r "$dpi" "$pdf" "$out/page"

count=$(find "$out" -name 'page-*.png' | wc -l)
size=$(du -sh "$out" | cut -f1)
echo "wrote $count page images to handbook/preview/ at ${dpi} dpi ($size)"
echo "open handbook/preview/page-01.png in Zed and page through with the file tree"
