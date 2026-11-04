-- Loads the warehouse as it stood when the monthly dbt job ran (2026-11-01 01:00 IST).
-- Replaces all existing seed data.
begin;
truncate raw.raw_products, raw.raw_customers, raw.raw_orders, raw.raw_payments, raw.raw_refunds,
         provider.payment_report, provider.monthly_statement,
         ops.ingestion_runs, ops.ingestion_dead_letter,
         verification.expected_metrics, verification.planted_issues;
\copy raw.raw_products  from '/database/seed/data/raw_products_initial.csv'  csv header
\copy raw.raw_customers from '/database/seed/data/raw_customers_initial.csv' csv header
\copy raw.raw_orders    from '/database/seed/data/raw_orders_initial.csv'    csv header
\copy raw.raw_payments  from '/database/seed/data/raw_payments_initial.csv'  csv header
\copy raw.raw_refunds   from '/database/seed/data/raw_refunds_initial.csv'   csv header
\copy provider.payment_report    from '/database/seed/data/provider_payment_report.csv'    csv header
\copy provider.monthly_statement from '/database/seed/data/provider_monthly_statement.csv' csv header
\copy ops.ingestion_runs         from '/database/seed/data/ops_ingestion_runs_initial.csv' csv header
\copy ops.ingestion_dead_letter  from '/database/seed/data/ops_ingestion_dead_letter.csv'  csv header
\copy verification.expected_metrics from '/database/seed/data/verification_expected_metrics.csv' csv header
\copy verification.planted_issues   from '/database/seed/data/verification_planted_issues.csv'   csv header
commit;
