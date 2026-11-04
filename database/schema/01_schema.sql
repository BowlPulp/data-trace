-- DATA TRACE warehouse schema. Idempotent.
create schema if not exists raw;          -- source systems, append-only as ingested
create schema if not exists provider;     -- payment provider's own export + statement
create schema if not exists ops;          -- ingestion run logs
create schema if not exists analytics;    -- dbt models (owned by dbt_runner)
create schema if not exists verification; -- ground truth; NO agent access

create table if not exists raw.raw_products (
  product_id text primary key, product_name text not null, category text not null,
  list_price numeric(12,2) not null, is_active boolean not null, _loaded_at timestamptz not null);

create table if not exists raw.raw_customers (
  customer_id text primary key, full_name text not null, email text not null, city text,
  signup_at timestamptz not null, _loaded_at timestamptz not null);

create table if not exists raw.raw_orders (
  order_id text primary key, customer_id text not null, product_id text not null,
  quantity int not null, unit_price numeric(12,2) not null, discount_amount numeric(12,2) not null,
  order_total numeric(12,2) not null, order_status text not null,
  ordered_at timestamptz not null, _loaded_at timestamptz not null);

-- Append-only landing table: no primary key, re-delivered batches create duplicate rows.
create table if not exists raw.raw_payments (
  payment_id text not null, order_id text not null, provider_txn_id text not null,
  amount numeric(12,2) not null, currency text not null, payment_method text not null,
  status text not null, upi_vpa text, created_at timestamptz not null, captured_at timestamptz,
  _batch_id text not null, _loaded_at timestamptz not null);

create table if not exists raw.raw_refunds (
  refund_id text not null, payment_id text not null, order_id text not null,
  provider_refund_id text not null, amount numeric(12,2) not null, reason text,
  status text not null, created_at timestamptz not null, processed_at timestamptz,
  _loaded_at timestamptz not null);

create table if not exists provider.payment_report (
  provider_txn_id text primary key, txn_type text not null, merchant_order_ref text not null,
  amount numeric(12,2) not null, currency text not null, method text, status text not null,
  txn_at timestamptz not null);

create table if not exists provider.monthly_statement (
  statement_month date primary key, gross_collections numeric(14,2) not null,
  refunds numeric(14,2) not null, net_collections numeric(14,2) not null,
  successful_payments int not null, refund_count int not null, generated_at timestamptz not null);

create table if not exists ops.ingestion_runs (
  run_id int primary key, source text not null, batch_id text not null,
  window_start timestamptz not null, window_end timestamptz not null,
  started_at timestamptz not null, finished_at timestamptz not null, status text not null,
  rows_received int not null, rows_loaded int not null, rows_rejected int not null, error_summary text);

create table if not exists ops.ingestion_dead_letter (
  batch_id text not null, received_at timestamptz not null, error text not null, payload jsonb not null);

create table if not exists verification.expected_metrics (
  metric text not null, month date not null, value numeric(14,2) not null, note text,
  primary key (metric, month));

create table if not exists verification.planted_issues (
  issue_id text primary key, title text not null, mechanism text not null,
  oct_isolated_impact numeric(14,2) not null);

comment on schema verification is 'Ground truth for scoring investigations. Never grant to agent roles.';
