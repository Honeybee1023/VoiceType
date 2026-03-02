#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

echo "[setup] Project root: $ROOT_DIR"

if [[ ! -d .venv ]]; then
  echo "[setup] Creating Python virtualenv..."
  python3 -m venv .venv
fi

echo "[setup] Installing Python dependencies..."
source .venv/bin/activate
python -m pip install -U pip || true
python -m pip install -r requirements.txt

echo "[setup] Done."
