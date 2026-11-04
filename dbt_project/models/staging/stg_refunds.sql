select
    refund_id,
    payment_id,
    order_id,
    amount,
    reason,
    processed_at,
    _loaded_at
from {{ source('raw', 'raw_refunds') }}
where status = 'processed'
