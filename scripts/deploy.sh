#!/usr/bin/env bash
set -euo pipefail

echo "Applying database migrations..."
alembic upgrade head

echo "Populating database from external integrations..."
python -m scripts.bootstrap_data
