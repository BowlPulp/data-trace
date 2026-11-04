-- Daily revenue by payment method (IST calendar days).
select
    (txn_at at time zone 'Asia/Kolkata')::date                      as revenue_date,
    payment_method,
    sum(case when txn_type = 'payment' then amount else 0 end)      as gross_revenue,
    -sum(case when txn_type = 'refund' then amount else 0 end)      as refunds,
    sum(amount)                                                     as net_revenue,
    count(*) filter (where txn_type = 'payment')                    as payment_count,
    count(*) filter (where txn_type = 'refund')                     as refund_count
from {{ ref('int_transactions') }}
group by 1, 2
