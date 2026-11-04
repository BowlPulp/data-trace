#!/usr/bin/env bash
# Compares warehouse outputs with the ground truth in the verification schema (admin only).
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
docker compose exec -T warehouse psql -X -v ON_ERROR_STOP=1 -U "$WAREHOUSE_ADMIN_USER" -d "$WAREHOUSE_DB" <<'SQL'
with actual as (
  select revenue_month as month, 'net_revenue_reported_monthly_model' as metric, net_revenue as value
  from analytics.monthly_revenue
  union all
  select date_trunc('month', revenue_date)::date, 'net_revenue_fct_current', sum(net_revenue)
  from analytics.fct_revenue group by 1
)
select e.month, e.metric, e.value as expected, a.value as actual,
       case when a.value = e.value then 'MATCH' else 'DIFF' end as check
from verification.expected_metrics e
left join actual a using (month, metric)
order by e.month, e.metric;

select statement_month, net_collections as provider_net,
       (select net_revenue from analytics.monthly_revenue where revenue_month = statement_month) as dashboard_net,
       net_collections - (select net_revenue from analytics.monthly_revenue where revenue_month = statement_month) as gap
from provider.monthly_statement order by 1;
SQL
