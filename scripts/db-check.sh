#!/usr/bin/env bash
# Proves the agent logins are least-privilege. Each line should match its EXPECT note.
set -uo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
q() { # role password sql expect
  printf '%-15s %-58s expect %-7s -> ' "$1" "$3" "$4"
  docker compose exec -T -e PGPASSWORD="$2" warehouse \
    psql -X -q -t -A -h 127.0.0.1 -U "$1" -d "$WAREHOUSE_DB" -c "$3" 2>&1 | head -1
}
q agent_source   "$AGENT_SOURCE_PASSWORD"   "select count(*) from raw.raw_payments"              ok
q agent_source   "$AGENT_SOURCE_PASSWORD"   "select count(*) from verification.expected_metrics" denied
q agent_source   "$AGENT_SOURCE_PASSWORD"   "delete from raw.raw_payments"                       denied
q agent_pipeline "$AGENT_PIPELINE_PASSWORD" "select count(*) from ops.ingestion_runs"            ok
q agent_pipeline "$AGENT_PIPELINE_PASSWORD" "select count(*) from provider.monthly_statement"    denied
q agent_metrics  "$AGENT_METRICS_PASSWORD"  "select net_collections from provider.monthly_statement where statement_month='2026-10-01'" ok
q agent_metrics  "$AGENT_METRICS_PASSWORD"  "select count(*) from raw.raw_payments"              denied
q agent_metrics  "$AGENT_METRICS_PASSWORD"  "create table analytics.x(a int)"                    denied
