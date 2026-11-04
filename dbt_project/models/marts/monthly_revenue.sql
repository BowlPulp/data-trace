-- Monthly revenue. Source of the finance revenue dashboard.
select
    date_trunc('month', revenue_date)::date as revenue_month,
    sum(gross_revenue)                      as gross_revenue,
    sum(refunds)                            as refunds,
    sum(net_revenue)                        as net_revenue,
    sum(payment_count)                      as payment_count,
    sum(refund_count)                       as refund_count,
    current_timestamp                       as built_at
from {{ ref('fct_revenue') }}
group by 1
