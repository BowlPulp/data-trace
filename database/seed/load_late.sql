-- Rows that arrived after the month_close dbt job: the Oct 31 payments backfill (after a
-- provider outage), later refunds, and the backfill run logs. Run by scripts/pipeline-replay.sh
-- AFTER the month_close build. Arrival times are stamped with the real load time so every
-- timestamp an investigator sees is consistent with the dbt run history.
begin;
create temp table late_payments (like raw.raw_payments) on commit drop;
create temp table late_refunds  (like raw.raw_refunds)  on commit drop;
create temp table late_runs     (like ops.ingestion_runs) on commit drop;
\copy late_payments from '/database/seed/data/raw_payments_late.csv'       csv header
\copy late_refunds  from '/database/seed/data/raw_refunds_late.csv'        csv header
\copy late_runs     from '/database/seed/data/ops_ingestion_runs_late.csv' csv header

insert into raw.raw_payments select payment_id, order_id, provider_txn_id, amount, currency, payment_method,
  status, upi_vpa, created_at, captured_at, _batch_id, now() from late_payments;
insert into raw.raw_refunds select refund_id, payment_id, order_id, provider_refund_id, amount, reason,
  status, created_at, processed_at, now() from late_refunds;
insert into ops.ingestion_runs select run_id, source, batch_id, window_start, window_end,
  now() - interval '4 minutes', now(), status, rows_received, rows_loaded, rows_rejected, error_summary
  from late_runs;
commit;
