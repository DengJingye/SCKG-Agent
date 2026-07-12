#!/usr/bin/env bash
set -euo pipefail

FIGURE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-/opt/anaconda3/bin/python}"

if [ ! -x "${PYTHON_BIN}" ]; then
  PYTHON_BIN="python3"
fi

export MPLCONFIGDIR="${MPLCONFIGDIR:-/private/tmp/mplconfig}"
export XDG_CACHE_HOME="${XDG_CACHE_HOME:-/private/tmp/xdg-cache}"
export FONTCONFIG_CACHE="${FONTCONFIG_CACHE:-/private/tmp/fontconfig-cache}"

mkdir -p "${MPLCONFIGDIR}" "${XDG_CACHE_HOME}" "${FONTCONFIG_CACHE}"
"${PYTHON_BIN}" "${FIGURE_DIR}/render_publication_figures.py"
