#!/usr/bin/env bash
set -euo pipefail

FIGURE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

for dot_file in "${FIGURE_DIR}"/*.dot; do
  base="${dot_file%.dot}"
  dot -Tsvg "${dot_file}" -o "${base}.svg"
  dot -Tpdf "${dot_file}" -o "${base}.pdf"
  if command -v rsvg-convert >/dev/null 2>&1; then
    rsvg-convert -w 2400 "${base}.svg" -o "${base}.png"
  fi
done

echo "Rendered figures in ${FIGURE_DIR}"
