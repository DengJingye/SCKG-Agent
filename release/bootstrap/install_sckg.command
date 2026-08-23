#!/bin/zsh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
MANIFEST="$ROOT_DIR/release/control-plane-manifest.json"
SCKG_HOME="${SCKG_HOME:-$HOME/.sckg}"
CONTROL_PREFIX="$SCKG_HOME/control-plane"
DOWNLOAD_DIR="$SCKG_HOME/downloads"
MICROMAMBA_ROOT="$SCKG_HOME/micromamba"

if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then
  print -u2 "BLOCKED: this beta supports Apple Silicon macOS only."
  exit 2
fi

if [[ "${1:-}" != "--accept-reviewed-install" ]]; then
  cat <<EOF
scKG Local Research Workbench control-plane installation

Install home: $SCKG_HOME
Platform: osx-arm64
The reviewed installer downloads pinned Micromamba and Python packages only.
Runtime Packs and user-data execution require separate approvals.

Re-run with:
  SCKG_HOME=\"$SCKG_HOME\" \"$0\" --accept-reviewed-install
EOF
  exit 2
fi

read_manifest() {
  /usr/bin/plutil -extract "$1" raw -o - "$MANIFEST"
}

verify_sha256() {
  local expected="$1"
  local path="$2"
  local actual
  actual="$(/usr/bin/shasum -a 256 "$path" | /usr/bin/awk '{print $1}')"
  if [[ "$actual" != "$expected" ]]; then
    print -u2 "BLOCKED: digest mismatch for ${path:t}."
    exit 3
  fi
}

mkdir -p "$DOWNLOAD_DIR" "$MICROMAMBA_ROOT/bin"

MICROMAMBA_URL="$(read_manifest micromamba.url)"
MICROMAMBA_SHA="$(read_manifest micromamba.sha256)"
MICROMAMBA_VERSION="$(read_manifest micromamba.version)"
MICROMAMBA_ARCHIVE="$DOWNLOAD_DIR/micromamba-$MICROMAMBA_VERSION-osx-arm64.tar.bz2"
MICROMAMBA_BIN="$MICROMAMBA_ROOT/bin/micromamba"

if [[ ! -x "$MICROMAMBA_BIN" ]]; then
  /usr/bin/curl --fail --location --silent --show-error \
    "$MICROMAMBA_URL" --output "$MICROMAMBA_ARCHIVE"
  verify_sha256 "$MICROMAMBA_SHA" "$MICROMAMBA_ARCHIVE"
  TEMP_DIR="$(/usr/bin/mktemp -d "$DOWNLOAD_DIR/micromamba.XXXXXX")"
  trap '/bin/rm -rf "$TEMP_DIR"' EXIT
  /usr/bin/tar -xjf "$MICROMAMBA_ARCHIVE" -C "$TEMP_DIR" bin/micromamba
  /bin/mv "$TEMP_DIR/bin/micromamba" "$MICROMAMBA_BIN"
  /bin/chmod 0755 "$MICROMAMBA_BIN"
fi

CONDA_LOCK="$ROOT_DIR/release/locks/control-plane-osx-arm64.conda-explicit.txt"
PIP_LOCK="$ROOT_DIR/release/locks/control-plane-osx-arm64.requirements.lock"
verify_sha256 "$(read_manifest lock_files.0.sha256)" "$CONDA_LOCK"
verify_sha256 "$(read_manifest lock_files.1.sha256)" "$PIP_LOCK"

if [[ -e "$CONTROL_PREFIX" ]]; then
  print -u2 "BLOCKED: control-plane prefix already exists at $CONTROL_PREFIX"
  exit 4
fi

export MAMBA_ROOT_PREFIX="$MICROMAMBA_ROOT"
export CONDA_PKGS_DIRS="$SCKG_HOME/cache/conda-pkgs"
export PIP_CACHE_DIR="$SCKG_HOME/cache/pip"
export PYTHONNOUSERSITE=1

"$MICROMAMBA_BIN" create --yes --prefix "$CONTROL_PREFIX" --file "$CONDA_LOCK"
"$CONTROL_PREFIX/bin/python" -m pip install \
  --require-hashes --no-deps --requirement "$PIP_LOCK"
"$CONTROL_PREFIX/bin/python" -c \
  'import anndata, cryptography, langgraph, numpy, pandas, pydantic, scipy, sklearn, streamlit'

/bin/cp "$MANIFEST" "$CONTROL_PREFIX/control-plane-manifest.json"
cat <<EOF
READY: scKG control plane installed.
Launch with:
  SCKG_HOME=\"$SCKG_HOME\" \"$ROOT_DIR/release/bootstrap/launch_sckg.command\"
EOF
