#!/usr/bin/env python3
"""
DATA TRACE remediation MCP server.

    --mode propose   (pipeline-investigator) propose_fix, list_proposals, get_proposal, get_latest_run
    --mode read      (other agents)          list_proposals, get_proposal, get_latest_run

Agents can PROPOSE fixes; they cannot approve or apply them. Approval and application are
human-only, via scripts/remediate.py, and run against an isolated sandbox.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from mcp.server import MCPServer  # noqa: E402
from mcp.types import ToolAnnotations  # noqa: E402

from tools.remediation import store  # noqa: E402

RO = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
RUNS = store.ROOT / "remediation" / "runs"


def build(mode: str, agent: str) -> MCPServer:
    server = MCPServer(
        name="datatrace-remediation",
        instructions="Fix proposals for DATA TRACE. Proposing never changes code or data; a human must approve "
                     "and apply each fix in an isolated sandbox. Check get_latest_run for verification results.",
    )

    @server.tool(annotations=RO)
    def list_proposals(investigation: str | None = None) -> dict[str, Any]:
        """List fix proposals and their status (proposed / approved / rejected / applied)."""
        props = [store.summary(p) for p in store.all_proposals()
                 if not investigation or p["investigation"] == investigation]
        return {"proposals": props}

    @server.tool(annotations=RO)
    def get_proposal(proposal_id: str) -> dict[str, Any]:
        """One proposal in full, including its diff or SQL and any verification result."""
        try:
            return store.summary(store.load(proposal_id), with_diff=True)
        except KeyError as e:
            return {"error": str(e)}

    @server.tool(annotations=RO)
    def get_latest_run() -> dict[str, Any]:
        """Result of the most recent sandbox remediation run (which fixes, dbt results, metric checks, verdict)."""
        runs = sorted(RUNS.glob("R-*/result.json")) if RUNS.exists() else []
        if not runs:
            return {"error": "no remediation run yet"}
        return json.loads(runs[-1].read_text())

    if mode == "propose":
        @server.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False,
                                                 idempotent_hint=False, open_world_hint=False))
        def propose_fix(title: str, investigation: str, kind: str, rationale: str, evidence: list[str],
                        expected_impact: str, tests: list[str] | None = None,
                        files: list[dict[str, str]] | None = None, sql: str | None = None) -> dict[str, Any]:
            """Record a proposed fix for human review. Does NOT change any code or data.

            kind="code_patch": files = [{"path": "dbt_project/models/...sql", "new_content": "<entire new file>"}].
              Allowed paths: dbt_project/models/**, dbt_project/tests/**, dbt_project/jobs/schedule.yml.
              Give the COMPLETE new file content; the diff is computed for you.
            kind="backfill_sql": sql = one "INSERT INTO raw.raw_payments|raw.raw_refunds (...) SELECT ..." statement.
              It will only ever run in the sandbox copy of the warehouse.
            evidence: query_ids and/or file:line references that justify the fix (required).
            tests: dbt tests that should pass (or be added) once the fix is applied.
            """
            try:
                p = store.create(kind=kind, title=title, investigation=investigation, rationale=rationale,
                                 evidence=evidence, expected_impact=expected_impact, tests=tests or [],
                                 proposed_by=agent, files=files, sql=sql)
            except (ValueError, KeyError) as e:
                store.audit("proposal_rejected_by_validation", by=agent, title=title, error=str(e))
                return {"error": f"proposal rejected by validation: {e}"}
            return {"proposal": store.summary(p, with_diff=True),
                    "next": "A human must review and approve this. Ask for approval in the room, citing the proposal id."}

    return server


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["propose", "read"], required=True)
    ap.add_argument("--agent", required=True)
    a = ap.parse_args()
    build(a.mode, a.agent).run("stdio")


if __name__ == "__main__":
    main()
