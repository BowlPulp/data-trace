#!/usr/bin/env bash
# Start the warehouse and (re)load schema, roles and initial seed data. Safe to re-run.
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose up -d --wait
docker compose exec -T warehouse sh /database/setup.sh
