#!/usr/bin/env bash
# Sync Equipe events now (the same as the nightly timer). Run on the server.
set -euo pipefail

cd "$(dirname "$0")/.."
"${PYTHON:-.venv/bin/python}" -m scripts.sync_equipe
