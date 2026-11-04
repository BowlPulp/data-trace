#!/usr/bin/env python3
"""Starts the MCP server for each role over stdio and checks what it can and cannot do."""
import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

SERVER = Path(__file__).with_name("server.py")
CASES = [
    ("source", "select count(*) as n from raw.raw_payments", "ok"),
    ("source", "select * from verification.expected_metrics", "error"),
    ("source", "delete from raw.raw_payments", "error"),
    ("source", "select 1; drop table raw.raw_orders", "error"),
    ("pipeline", "select status, count(*) from ops.ingestion_runs group by 1 order by 1", "ok"),
    ("pipeline", "select * from provider.monthly_statement", "error"),
    ("metrics", "select revenue_month, net_revenue, built_at from analytics.monthly_revenue order by 1", "ok"),
    ("metrics", "select count(*) from raw.raw_payments", "error"),
]


def payload(res):
    structured = getattr(res, "structured_content", None)
    if structured:
        return structured
    return json.loads(res.content[0].text)


async def run_role(role, cases):
    params = StdioServerParameters(command=sys.executable, args=[str(SERVER), "--role", role])
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = [t.name for t in (await s.list_tools()).tools]
            tables = payload(await s.call_tool("list_tables", {}))["tables"]
            print(f"\n[{role}] tools={tools} readable_tables={len(tables)} "
                  f"schemas={sorted({t['table_schema'] for t in tables})}")
            ok = True
            for sql, expect in cases:
                p = payload(await s.call_tool("run_query", {"sql": sql, "max_rows": 5}))
                got = "error" if "error" in p else "ok"
                ok &= got == expect
                detail = p.get("error") or p.get("rows")
                print(f"  {'PASS' if got == expect else 'FAIL'} expect={expect:<5} {sql[:60]:<60} -> {str(detail)[:90]}")
            return ok


async def main():
    results = []
    for role in ("source", "pipeline", "metrics"):
        results.append(await run_role(role, [(s, e) for r, s, e in CASES if r == role]))
    print("\nALL PASS" if all(results) else "\nSOME CHECKS FAILED")
    sys.exit(0 if all(results) else 1)


asyncio.run(main())
