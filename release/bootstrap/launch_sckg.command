#!/bin/zsh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
SCKG_HOME="${SCKG_HOME:-$HOME/.sckg}"
PYTHON="$SCKG_HOME/control-plane/bin/python"

if [[ ! -x "$PYTHON" ]]; then
  print -u2 "BLOCKED: control plane is not installed. Run install_sckg.command first."
  exit 2
fi

export SCKG_HOME
export PYTHONNOUSERSITE=1
cd "$ROOT_DIR"
exec "$PYTHON" -m cli.sckg launch "$@"
