#!/usr/bin/env bash
set -euo pipefail

echo "Creating database tables from SQLAlchemy models..."
python -m scripts.create_schema

echo "Populating database from external integrations..."
python -m scripts.bootstrap_data
