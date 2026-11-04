#!/usr/bin/env bash
# Recreates the production pipeline history for the demo, in real time order:
#   1. reload the warehouse as it stood at month close
#   2. month_close job:  dbt build                      (builds everything, incl. monthly_revenue)
#   3. late data lands:  Oct 31 payments backfill + later refunds
#   4. nightly job:      dbt build --select +fct_revenue
# Each job's dbt artifacts and logs are kept in pipeline_logs/ for the Pipeline Investigator.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$(pwd)
set -a; . ./.env; set +a
DBT="$ROOT/.venv/bin/dbt"
[ -x "$DBT" ] || { echo "dbt not found. Run: python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dbt.txt"; exit 1; }

run_job() {  # name, dbt args...
  local name=$1; shift
  local dir="$ROOT/pipeline_logs/$(date -u +%Y%m%dT%H%M%SZ)_$name"
  mkdir -p "$dir"
  echo "== job $name: dbt $*"
  ( cd dbt_project && "$DBT" "$@" --log-path "$dir" ) | tee "$dir/console.txt" || true
  cp dbt_project/target/run_results.json dbt_project/target/manifest.json "$dir/" 2>/dev/null || true
}

./scripts/db-setup.sh >/dev/null
echo "== warehouse reset to month-close state"

run_job month_close build
sleep 2

docker compose exec -T warehouse psql -X -q -v ON_ERROR_STOP=1 \
  -U "$WAREHOUSE_ADMIN_USER" -d "$WAREHOUSE_DB" -f /database/seed/load_late.sql
echo "== late data loaded (Oct 31 backfill, later refunds)"
sleep 2

run_job nightly build --select +fct_revenue
( cd dbt_project && "$DBT" docs generate --log-path "$ROOT/pipeline_logs" >/dev/null ) || true
echo "== done. Artifacts in pipeline_logs/ and dbt_project/target/"
