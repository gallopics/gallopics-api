#!/usr/bin/env bash
set -euo pipefail

echo "Running database migrations..."
alembic upgrade head

echo "Populating database from external integrations..."
python -m scripts.bootstrap_data
