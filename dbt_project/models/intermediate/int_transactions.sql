-- Revenue ledger: payments in (+), refunds out (-), each at the time money moved.
with payments as (
    select
        'payment'       as txn_type,
        payment_id      as txn_id,
        payment_id,
        order_id,
        payment_method,
        captured_at     as txn_at,
        amount
    from {{ ref('stg_payments') }}
),

refunds as (
    select
        'refund'        as txn_type,
        r.refund_id     as txn_id,
        p.payment_id,
        r.order_id,
        p.payment_method,
        r.processed_at  as txn_at,
        -r.amount       as amount
    from {{ ref('stg_refunds') }} r
    join {{ ref('stg_payments') }} p
      on p.order_id = r.order_id
)

select * from payments
union all
select * from refunds
