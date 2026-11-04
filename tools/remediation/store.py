"""
Remediation proposals: storage and validation. Shared by the MCP server (agents propose)
and scripts/remediate.py (humans approve and apply). Pure Python, no database access here.

A proposal is one fix. Two kinds:
  code_patch    full new content for files under dbt_project/models, dbt_project/tests or
                dbt_project/jobs/schedule.yml (the diff against the current file is computed here)
  backfill_sql  one INSERT INTO raw.raw_payments|raw.raw_refunds ... SELECT statement,
                executed only in the sandbox database
"""
from __future__ import annotations

import datetime as dt
import difflib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
STORE = ROOT / "remediation" / "proposals"
AUDIT = ROOT / "remediation" / "audit.jsonl"

ALLOWED_PATH = re.compile(r"^dbt_project/(models/[\w/.-]+\.(sql|yml)|tests/[\w/.-]+\.sql|jobs/schedule\.yml)$")
FORBIDDEN_SQL = re.compile(
    r"\b(insert|update|delete|drop|truncate|alter|grant|revoke|create|copy|vacuum|call|execute|do)\b"
    r"|pre_hook|post_hook|run_query|statement\s*\(|on-run-|\{%-?\s*call\b",
    re.IGNORECASE,
)
BACKFILL_START = re.compile(r"^\s*insert\s+into\s+raw\.raw_(payments|refunds)\b", re.IGNORECASE)
BACKFILL_FORBIDDEN = re.compile(r"\b(update|delete|drop|truncate|alter|grant|revoke|create|copy|call|do)\b", re.IGNORECASE)
STATUSES = ("proposed", "approved", "rejected", "applied")


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def audit(action: str, **fields: Any) -> None:
    AUDIT.parent.mkdir(parents=True, exist_ok=True)
    with AUDIT.open("a") as fh:
        fh.write(json.dumps({"at": now(), "action": action, **fields}, default=str) + "\n")


def strip_sql(sql: str) -> str:
    s = re.sub(r"--[^\n]*", " ", sql)
    s = re.sub(r"/\*.*?\*/", " ", s, flags=re.DOTALL)
    s = re.sub(r"\{#.*?#\}", " ", s, flags=re.DOTALL)
    return re.sub(r"'(?:''|[^'])*'", "''", s)


def validate_file(path: str, content: str) -> str | None:
    if not ALLOWED_PATH.match(path) or ".." in path:
        return f"{path}: only dbt_project/models/**, dbt_project/tests/** and dbt_project/jobs/schedule.yml may be changed"
    if path.endswith(".sql") and (m := FORBIDDEN_SQL.search(strip_sql(content))):
        return f"{path}: forbidden construct '{m.group(0)}' (models must be pure SELECTs, no hooks or statements)"
    if path.endswith("schedule.yml"):
        import yaml
        try:
            jobs = yaml.safe_load(content)["jobs"]
            for j in jobs:
                cmd = j["command"]
                if not re.fullmatch(r"dbt (build|run|test)( [\w+@:.,=/ -]+)?", cmd):
                    return f"schedule.yml: job '{j.get('name')}' command must be a plain dbt build/run/test command"
        except Exception as e:  # noqa: BLE001
            return f"schedule.yml: invalid ({e})"
    return None


def validate_backfill(sql: str) -> str | None:
    body = strip_sql(sql).strip().rstrip(";")
    if ";" in body:
        return "backfill_sql must be a single statement"
    if not BACKFILL_START.match(body):
        return "backfill_sql must be INSERT INTO raw.raw_payments or raw.raw_refunds ... SELECT ..."
    if m := BACKFILL_FORBIDDEN.search(body):
        return f"backfill_sql contains forbidden keyword '{m.group(0)}'"
    if not re.search(r"\bselect\b", body, re.IGNORECASE):
        return "backfill_sql must insert from a SELECT"
    return None


def next_id() -> str:
    STORE.mkdir(parents=True, exist_ok=True)
    nums = [int(p.stem.split("-")[1]) for p in STORE.glob("P-*.json")]
    return f"P-{(max(nums) + 1 if nums else 1):03d}"


def load(pid: str) -> dict[str, Any]:
    p = STORE / f"{pid}.json"
    if not p.exists():
        raise KeyError(f"no proposal {pid}")
    return json.loads(p.read_text())


def save(prop: dict[str, Any]) -> None:
    STORE.mkdir(parents=True, exist_ok=True)
    (STORE / f"{prop['id']}.json").write_text(json.dumps(prop, indent=2) + "\n")


def all_proposals() -> list[dict[str, Any]]:
    return [json.loads(p.read_text()) for p in sorted(STORE.glob("P-*.json"))] if STORE.exists() else []


def create(*, kind: str, title: str, investigation: str, rationale: str, evidence: list[str],
           expected_impact: str, tests: list[str], proposed_by: str,
           files: list[dict[str, str]] | None = None, sql: str | None = None) -> dict[str, Any]:
    if kind not in ("code_patch", "backfill_sql"):
        raise ValueError("kind must be code_patch or backfill_sql")
    if not evidence:
        raise ValueError("evidence is required: cite query_ids and/or file:line")
    changes = []
    if kind == "code_patch":
        if not files:
            raise ValueError("code_patch needs files: [{path, new_content}]")
        for f in files:
            path, new = f["path"].lstrip("./"), f["new_content"]
            if err := validate_file(path, new):
                raise ValueError(err)
            target = ROOT / path
            old = target.read_text() if target.exists() else ""
            if old == new:
                raise ValueError(f"{path}: new_content is identical to the current file")
            diff = "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                                                fromfile=f"a/{path}", tofile=f"b/{path}"))
            changes.append({"path": path, "original": old, "proposed": new, "diff": diff})
    else:
        if not sql or (err := validate_backfill(sql)):
            raise ValueError(err or "backfill_sql needs sql")
    prop = {
        "id": next_id(), "kind": kind, "title": title, "investigation": investigation,
        "status": "proposed", "proposed_by": proposed_by, "proposed_at": now(),
        "rationale": rationale, "evidence": evidence, "expected_impact": expected_impact,
        "tests": tests, "changes": changes, "sql": sql, "history": [{"at": now(), "status": "proposed", "by": proposed_by}],
    }
    save(prop)
    audit("proposed", id=prop["id"], kind=kind, title=title, by=proposed_by)
    return prop


def set_status(pid: str, status: str, by: str, note: str = "") -> dict[str, Any]:
    prop = load(pid)
    prop["status"] = status
    prop["history"].append({"at": now(), "status": status, "by": by, "note": note})
    save(prop)
    audit(status, id=pid, by=by, note=note)
    return prop


def summary(prop: dict[str, Any], with_diff: bool = False) -> dict[str, Any]:
    out = {k: prop[k] for k in ("id", "kind", "title", "status", "investigation", "proposed_by",
                                "expected_impact", "evidence", "tests")}
    out["files"] = [c["path"] for c in prop["changes"]]
    if with_diff:
        out["diff"] = "\n".join(c["diff"] for c in prop["changes"]) or None
        out["sql"] = prop.get("sql")
    if prop.get("result"):
        out["result"] = prop["result"]
    return out
