-- Finance revenue dashboard: "Net revenue by month" tile.
-- Refreshed by the BI tool every 15 minutes; it does not trigger dbt runs.
select
    revenue_month,
    gross_revenue,
    refunds,
    net_revenue
from analytics.monthly_revenue
order by revenue_month;
