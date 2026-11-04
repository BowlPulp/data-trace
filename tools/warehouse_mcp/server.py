#!/usr/bin/env python3
"""
DATA TRACE warehouse MCP server: read-only SQL access for one investigation agent.

    python tools/warehouse_mcp/server.py --role source|pipeline|metrics

Each role connects with its own least-privilege Postgres login (see database/schema/02_roles.sql).
Credentials are read from the project's .env, because Switch Console does not pass the shell
environment to agents. Every query is appended to logs/agent_queries/<role>.jsonl as evidence.

Safety layers: role grants (what tables) -> role default_transaction_read_only (no writes)
-> read-only transaction set here -> single SELECT-style statement check -> row cap -> 30s timeout.
"""
from __future__ import annotations

import argparse
import datetime as dt
import decimal
import json
import re
import uuid
from pathlib import Path
from typing import Any

import psycopg
from mcp.server import MCPServer
from mcp.types import ToolAnnotations

ROOT = Path(__file__).resolve().parents[2]
ROLES = {
    "source": ("agent_source", "AGENT_SOURCE_PASSWORD"),
    "pipeline": ("agent_pipeline", "AGENT_PIPELINE_PASSWORD"),
    "metrics": ("agent_metrics", "AGENT_METRICS_PASSWORD"),
}
MAX_ROWS_CAP = 500
ALLOWED_START = re.compile(r"^\s*(select|with|explain|values|table|show)\b", re.IGNORECASE)
READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)


def load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def jsonable(v: Any) -> Any:
    if isinstance(v, decimal.Decimal):
        return str(v)
    if isinstance(v, (dt.datetime, dt.date, dt.time)):
        return v.isoformat()
    if isinstance(v, (bytes, memoryview)):
        return "<binary>"
    return v


def strip_sql(sql: str) -> str:
    """Remove comments and string literals, for statement checks only."""
    s = re.sub(r"--[^\n]*", " ", sql)
    s = re.sub(r"/\*.*?\*/", " ", s, flags=re.DOTALL)
    s = re.sub(r"'(?:''|[^'])*'", "''", s)
    return s


def build_server(role: str) -> MCPServer:
    user, pw_key = ROLES[role]
    env = load_env(ROOT / ".env")
    conninfo = psycopg.conninfo.make_conninfo(
        host="127.0.0.1", port=env.get("WAREHOUSE_PORT", "55432"),
        dbname=env.get("WAREHOUSE_DB", "datatrace"), user=user, password=env[pw_key],
        application_name=f"datatrace-agent-{role}", connect_timeout=10,
    )
    log_path = ROOT / "logs" / "agent_queries" / f"{role}.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    def audit(entry: dict[str, Any]) -> None:
        with log_path.open("a") as fh:
            fh.write(json.dumps(entry, default=str) + "\n")

    def query(sql: str, params: tuple | None = None, max_rows: int = MAX_ROWS_CAP) -> tuple[list[str], list[list[Any]], bool]:
        with psycopg.connect(conninfo) as conn:
            conn.read_only = True
            with conn.cursor() as cur:
                # params=None: psycopg then leaves '%' alone (agents' LIKE 'x%' must work)
                cur.execute(sql, params or None)
                if cur.description is None:
                    return [], [], False
                cols = [d.name for d in cur.description]
                rows = cur.fetchmany(max_rows + 1)
                truncated = len(rows) > max_rows
                return cols, [[jsonable(v) for v in r] for r in rows[:max_rows]], truncated

    server = MCPServer(
        name=f"datatrace-warehouse-{role}",
        instructions=(
            f"Read-only access to the DATA TRACE Postgres warehouse as `{user}`. "
            "Start with list_tables, then describe_table. Every run_query result includes a query_id; "
            "cite it, together with the SQL, as evidence for any finding."
        ),
    )

    @server.tool(annotations=READ_ONLY)
    def list_tables() -> dict[str, Any]:
        """List every table and view this agent is allowed to read, with its description."""
        try:
            cols, rows, _ = query(
                """
                select n.nspname as table_schema, c.relname as table_name,
                       case c.relkind when 'v' then 'VIEW' when 'm' then 'MATERIALIZED VIEW' else 'TABLE' end as table_type,
                       obj_description(c.oid, 'pg_class') as description
                from pg_catalog.pg_class c
                join pg_catalog.pg_namespace n on n.oid = c.relnamespace
                where c.relkind in ('r', 'v', 'm', 'p')
                  and n.nspname not in ('pg_catalog', 'information_schema')
                  and left(n.nspname, 3) <> 'pg_'
                  and has_schema_privilege(n.oid, 'USAGE')
                  and has_table_privilege(c.oid, 'SELECT')
                order by 1, 2
                """
            )
        except psycopg.Error as e:
            return {"error": (e.diag.message_primary if getattr(e, "diag", None) else None) or str(e)}
        return {"role": user, "tables": [dict(zip(cols, r)) for r in rows]}

    @server.tool(annotations=READ_ONLY)
    def describe_table(schema: str, table: str) -> dict[str, Any]:
        """Columns, types, nullability and exact row count of one table or view."""
        try:
            cols, rows, _ = query(
            """
            select column_name, data_type, is_nullable
            from information_schema.columns
            where table_schema = %s and table_name = %s
            order by ordinal_position
            """,
            (schema, table),
            )
        except psycopg.Error as e:
            return {"error": (e.diag.message_primary if getattr(e, "diag", None) else None) or str(e)}
        if not rows:
            return {"error": f"{schema}.{table} not found or not readable by {user}"}
        try:
            _, cnt, _ = query(
                psycopg.sql.SQL("select count(*) from {}.{}").format(
                    psycopg.sql.Identifier(schema), psycopg.sql.Identifier(table)).as_string(None))
            row_count = cnt[0][0]
        except psycopg.Error as e:
            row_count = f"unavailable: {e.diag.message_primary or e}"
        return {"table": f"{schema}.{table}", "row_count": row_count, "columns": [dict(zip(cols, r)) for r in rows]}

    @server.tool(annotations=READ_ONLY)
    def run_query(sql: str, max_rows: int = 200) -> dict[str, Any]:
        """Run ONE read-only SQL statement (SELECT / WITH / EXPLAIN) and return up to max_rows rows (cap 500).

        Write evidence-quality SQL: explicit columns, filters and time zones (data is IST, Asia/Kolkata).
        """
        qid = "q_" + uuid.uuid4().hex[:10]
        entry: dict[str, Any] = {"query_id": qid, "role": user, "at": dt.datetime.now(dt.timezone.utc).isoformat(), "sql": sql}
        body = strip_sql(sql).strip().rstrip(";")
        if ";" in body:
            entry.update(ok=False, error="multiple statements rejected")
            audit(entry)
            return {"query_id": qid, "error": "Only one SQL statement per call."}
        if not ALLOWED_START.match(body):
            entry.update(ok=False, error="non-read statement rejected")
            audit(entry)
            return {"query_id": qid, "error": "Only read-only statements (SELECT, WITH, EXPLAIN, VALUES, TABLE, SHOW) are allowed."}
        max_rows = max(1, min(int(max_rows), MAX_ROWS_CAP))
        try:
            cols, rows, truncated = query(sql, max_rows=max_rows)
        except psycopg.Error as e:
            msg = (e.diag.message_primary if getattr(e, "diag", None) else None) or str(e)
            entry.update(ok=False, error=msg)
            audit(entry)
            return {"query_id": qid, "error": msg}
        entry.update(ok=True, rows=len(rows), truncated=truncated)
        audit(entry)
        return {"query_id": qid, "columns": cols, "rows": rows, "row_count": len(rows), "truncated": truncated}

    return server


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--role", required=True, choices=sorted(ROLES))
    build_server(ap.parse_args().role).run("stdio")


if __name__ == "__main__":
    main()
