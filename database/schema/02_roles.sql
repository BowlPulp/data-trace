-- Logins and least-privilege grants. Idempotent. Passwords come from psql variables (from .env).
select format('create role %I login', r)
from (values ('agent_source'), ('agent_pipeline'), ('agent_metrics'), ('dbt_runner')) v(r)
where not exists (select 1 from pg_roles where rolname = r) \gexec

alter role agent_source   password :'agent_source_pw';
alter role agent_pipeline password :'agent_pipeline_pw';
alter role agent_metrics  password :'agent_metrics_pw';
alter role dbt_runner     password :'dbt_runner_pw';

-- Investigation agents: read-only at the session level too, with a query time limit.
alter role agent_source   set default_transaction_read_only = on;
alter role agent_pipeline set default_transaction_read_only = on;
alter role agent_metrics  set default_transaction_read_only = on;
alter role agent_source   set statement_timeout = '30s';
alter role agent_pipeline set statement_timeout = '30s';
alter role agent_metrics  set statement_timeout = '30s';

revoke connect on database :"dbname" from public;
grant connect on database :"dbname" to agent_source, agent_pipeline, agent_metrics, dbt_runner;
revoke all on schema public from public;

-- dbt_runner reads sources and owns the analytics schema.
grant usage on schema raw to dbt_runner;
grant select on all tables in schema raw to dbt_runner;
alter schema analytics owner to dbt_runner;

-- Source Investigator: sources, provider export, ingestion logs, warehouse models.
grant usage on schema raw, provider, ops, analytics to agent_source;
grant select on all tables in schema raw, provider, ops to agent_source;

-- Pipeline Investigator: ingestion/pipeline logs, warehouse models, raw for tracing.
grant usage on schema raw, ops, analytics to agent_pipeline;
grant select on all tables in schema raw, ops to agent_pipeline;

-- Metrics Investigator: warehouse models and the provider's figures to compare against.
grant usage on schema provider, analytics to agent_metrics;
grant select on all tables in schema provider to agent_metrics;

-- Tables dbt creates later in analytics are readable by all three agents.
alter default privileges for role dbt_runner in schema analytics
  grant select on tables to agent_source, agent_pipeline, agent_metrics;
grant select on all tables in schema analytics to agent_source, agent_pipeline, agent_metrics;

-- Ground truth stays private.
revoke all on schema verification from public;
revoke all on all tables in schema verification from public;
