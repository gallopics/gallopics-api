#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${SERVICE_URL:-}" ]]; then
  echo "SERVICE_URL is required, for example: http://82.96.43.103:8081"
  exit 1
fi

curl -fsS -X POST "$SERVICE_URL/api/v1/integrations/equipe/sync"
echo
