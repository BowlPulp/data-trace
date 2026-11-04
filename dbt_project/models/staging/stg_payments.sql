-- Successful payments, one row per payment_id.
with deduplicated as (
    select
        *,
        row_number() over (partition by payment_id order by _loaded_at) as delivery_rank
    from {{ source('raw', 'raw_payments') }}
)

select
    payment_id,
    order_id,
    provider_txn_id,
    amount,
    payment_method,
    status,
    created_at,
    captured_at,
    _loaded_at
from deduplicated
where delivery_rank = 1
  and status = 'captured'
