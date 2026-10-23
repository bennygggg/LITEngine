#!/usr/bin/env bash
# One command to check the whole monorepo (there is no CI while GitHub is suspended).
#   scripts/verify.sh          full: backend tests + OpenAPI drift + frontend typecheck/lint/tests/build
#   scripts/verify.sh --fast   skip the frontend production build (used by the pre-push hook)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FAST=0; [ "${1:-}" = "--fast" ] && FAST=1

echo "== backend (Python 3.11, production pins)"
cd "$ROOT/lit-backend"
PY=.venv311/bin/python
if [ ! -x "$PY" ]; then
  echo "Missing .venv311. Create it with:"
  echo "  uv python install 3.11 && uv venv --python 3.11 .venv311 && uv pip install --python .venv311/bin/python -r requirements-dev.txt"
  exit 1
fi
# macOS only: faiss + torch in one process need these or they crash/hang. Harmless on Linux.
export OMP_NUM_THREADS=1 TOKENIZERS_PARALLELISM=false KMP_DUPLICATE_LIB_OK=TRUE
$PY -m pytest -q -m "not slow and not live_server"
$PY scripts/export_openapi.py --check

echo "== frontend"
cd "$ROOT/lit-frontend"
npm run --silent typecheck
npm run --silent lint
npm run --silent test
if [ "$FAST" -eq 0 ]; then npm run --silent build; fi
echo "verify: OK"
