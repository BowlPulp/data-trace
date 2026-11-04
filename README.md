# DATA TRACE

> When your data doesn't add up, find out why.

DATA TRACE is a multi-agent data pipeline investigation system built on
[Switch](https://docs.switchagents.ai/) and Claude Code, for the Flip the Switch Hackathon.

## Status

Phase 1 — foundation. Postgres warehouse runs in Docker; sample data, dbt and agents come next.

## Prerequisites (installed system-wide, not by this repo)

- macOS (Apple Silicon), Docker Desktop
- Claude Code CLI, signed in (`claude auth login`)
- Switch Console (desktop app), with its local server and a Discord connection

## Quick start

```sh
cp .env.example .env        # then replace every change-me with a strong random value
./scripts/db-setup.sh       # start Postgres, create schemas + least-privilege logins, load seed data
./scripts/db-check.sh       # prove each agent login can only read what it should
```

Seed data is generated deterministically by `database/seed/generate.py` (stdlib Python).
The CSVs in `database/seed/data/` are committed, so Python is not needed to load them.

### dbt pipeline

```sh
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-dbt.txt
./scripts/pipeline-replay.sh   # month_close build -> late data lands -> nightly build
./scripts/verify.sh            # compare warehouse outputs with ground truth
```

Lineage: `raw_* -> stg_orders / stg_payments / stg_refunds -> int_transactions -> fct_revenue -> monthly_revenue`.
Production schedule is documented in `dbt_project/jobs/schedule.yml`. Each replayed job's
`run_results.json`, `manifest.json` and logs are kept in `pipeline_logs/`.

### Warehouse schemas and who can read them

| Schema | Contents | agent_source | agent_pipeline | agent_metrics |
|---|---|---|---|---|
| `raw` | orders, payments, refunds, customers, products as ingested | read | read | – |
| `provider` | payment provider's transaction export and monthly statement | read | – | read |
| `ops` | ingestion run logs, dead-letter queue | read | read | – |
| `analytics` | dbt models | read | read | read |
| `verification` | ground truth for scoring | – | – | – |

All agent logins are read-only with a 30s statement timeout. `dbt_runner` owns `analytics`.

Connect: `psql "postgresql://$WAREHOUSE_ADMIN_USER@127.0.0.1:55432/datatrace"`

Stop: `docker compose down` · Wipe data: `docker compose down -v`

## Layout

| Path | Purpose |
|---|---|
| `agents/<name>/` | Working directory for each Switch agent (its `CLAUDE.md`, MCP config, Switch settings) |
| `backend/` | FastAPI API, investigation, lineage and remediation services |
| `frontend/` | Next.js UI |
| `database/init/` | SQL run once when the warehouse volume is first created |
| `database/schema/`, `database/seed/` | Source schema and sample data |
| `dbt_project/` | dbt models, tests, macros |
| `lineage/` | Lineage engine artifacts |
| `docs/` | Design notes |

## What lives outside this folder

- Switch Console app, its local database, and the Switch server it runs
- Claude Code CLI and its sign-in
- Docker volume `datatrace_warehouse_data` (inside Docker Desktop's VM)
