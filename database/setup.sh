#!/bin/sh
# Runs INSIDE the warehouse container: schema, roles, initial data. Safe to re-run.
set -eu
: "${POSTGRES_USER:?}" "${POSTGRES_DB:?}"
: "${AGENT_SOURCE_PASSWORD:?}" "${AGENT_PIPELINE_PASSWORD:?}" "${AGENT_METRICS_PASSWORD:?}" "${DBT_RUNNER_PASSWORD:?}"
PSQL="psql -X -q -v ON_ERROR_STOP=1 -U $POSTGRES_USER -d $POSTGRES_DB"

$PSQL -f /database/schema/01_schema.sql
$PSQL -v dbname="$POSTGRES_DB" \
      -v agent_source_pw="$AGENT_SOURCE_PASSWORD" -v agent_pipeline_pw="$AGENT_PIPELINE_PASSWORD" \
      -v agent_metrics_pw="$AGENT_METRICS_PASSWORD" -v dbt_runner_pw="$DBT_RUNNER_PASSWORD" \
      -f /database/schema/02_roles.sql
$PSQL -f /database/seed/load_initial.sql
$PSQL -c "select 'raw_orders' t, count(*) from raw.raw_orders union all
          select 'raw_payments', count(*) from raw.raw_payments union all
          select 'raw_refunds', count(*) from raw.raw_refunds union all
          select 'provider.payment_report', count(*) from provider.payment_report union all
          select 'ops.ingestion_runs', count(*) from ops.ingestion_runs"
echo "warehouse setup complete"
