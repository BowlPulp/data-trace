select
    order_id,
    customer_id,
    product_id,
    quantity,
    unit_price,
    discount_amount,
    order_total,
    order_status,
    ordered_at,
    (ordered_at at time zone 'Asia/Kolkata')::date as ordered_date_ist
from {{ source('raw', 'raw_orders') }}
