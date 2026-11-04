#!/usr/bin/env python3
"""
Human-only remediation CLI for DATA TRACE. Production is never modified.

  remediate.py list                         all proposals and their status
  remediate.py show P-001                   rationale, evidence and the exact diff / SQL
  remediate.py approve P-001 [P-002 ...]    record your approval (name from git config, or --by)
  remediate.py reject P-003 --note "why"
  remediate.py apply [P-001 ...]            apply approved proposals in an isolated sandbox and verify
                                            (default: every approved, not-yet-applied proposal)

apply:
  1. creates git branch remediation/<run> in a separate worktree (remediation/runs/<run>/workspace)
  2. rebuilds database datatrace_sandbox from a copy of production (verification schema excluded)
  3. applies the code patches in the worktree and commits them on the branch
  4. dbt parse (validation), then backfill SQL in the sandbox, as login remediation_runner,
     which cannot connect to the production database
  5. runs the NIGHTLY job command from the patched jobs/schedule.yml against the sandbox
  6. verifies: dbt has no errors or test failures, and monthly_revenue.net_revenue equals the
     provider's net_collections for every statement month
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.remediation import store  # noqa: E402

RUNS = ROOT / "remediation" / "runs"
DBT = ROOT / ".venv" / "bin" / "dbt"


def env() -> dict[str, str]:
    e = {}
    for line in (ROOT / ".env").read_text().splitlines():
        if line.strip() and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            e[k.strip()] = v.strip()
    return e


def sh(cmd: list[str], *, cwd: Path = ROOT, input: str | None = None, extra_env: dict | None = None,
       check: bool = True) -> subprocess.CompletedProcess:
    import os
    full_env = {**os.environ, **(extra_env or {})}
    r = subprocess.run(cmd, cwd=cwd, input=input, text=True, capture_output=True, env=full_env)
    if check and r.returncode != 0:
        raise SystemExit(f"command failed: {' '.join(cmd)}\n{r.stdout[-2000:]}\n{r.stderr[-2000:]}")
    return r


def psql(db: str, user: str, sql: str, *, tuples: bool = False) -> str:
    args = ["docker", "compose", "exec", "-T", "warehouse", "psql", "-X", "-q", "-v", "ON_ERROR_STOP=1",
            "-U", user, "-d", db]
    if tuples:
        args += ["-t", "-A", "-F", "|"]
    return sh(args, input=sql).stdout


def who(args) -> str:
    if args.by:
        return args.by
    r = sh(["git", "config", "user.name"], check=False)
    return r.stdout.strip() or "unknown-human"


def cmd_list(args):
    props = store.all_proposals()
    if not props:
        print("no proposals yet")
    for p in props:
        print(f"{p['id']}  {p['status']:<9} {p['kind']:<12} {p['title']}  (by {p['proposed_by']})")


def cmd_show(args):
    p = store.load(args.id)
    print(f"{p['id']}  [{p['status']}]  {p['title']}\nkind: {p['kind']}   proposed by {p['proposed_by']} at {p['proposed_at']}")
    print(f"investigation: {p['investigation']}\n\nRationale:\n  {p['rationale']}\n")
    print("Evidence:\n" + "\n".join(f"  - {e}" for e in p["evidence"]))
    print(f"\nExpected impact:\n  {p['expected_impact']}\n\nTests:\n" + ("\n".join(f"  - {t}" for t in p["tests"]) or "  (none)"))
    for c in p["changes"]:
        print(f"\n--- diff: {c['path']}\n{c['diff']}")
    if p.get("sql"):
        print(f"\n--- backfill SQL (sandbox only):\n{p['sql']}")
    for h in p["history"]:
        print(f"  {h['at']}  {h['status']:<9} by {h['by']}  {h.get('note', '')}")


def cmd_approve(args):
    by = who(args)
    for pid in args.ids:
        p = store.load(pid)
        if p["status"] != "proposed":
            print(f"{pid}: is {p['status']}, not proposed; skipped")
            continue
        store.set_status(pid, "approved", by, args.note or "")
        print(f"{pid}: approved by {by}")


def cmd_reject(args):
    by = who(args)
    for pid in args.ids:
        store.set_status(pid, "rejected", by, args.note or "")
        print(f"{pid}: rejected by {by}")


def cmd_apply(args):
    e = env()
    props = [store.load(i) for i in args.ids] if args.ids else [p for p in store.all_proposals() if p["status"] == "approved"]
    if not props:
        raise SystemExit("nothing to apply: no approved proposals")
    for p in props:
        if p["status"] != "approved":
            raise SystemExit(f"{p['id']} is {p['status']}; only approved proposals can be applied")
        # re-validate at apply time; the stored proposal could have been edited by hand
        for c in p["changes"]:
            if err := store.validate_file(c["path"], c["proposed"]):
                raise SystemExit(f"{p['id']}: {err}")
        if p["kind"] == "backfill_sql" and (err := store.validate_backfill(p["sql"])):
            raise SystemExit(f"{p['id']}: {err}")

    run_id = "R-" + dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = RUNS / run_id
    ws = run_dir / "workspace"
    run_dir.mkdir(parents=True)
    log = []

    def step(msg):
        print(f"[{run_id}] {msg}")
        log.append({"at": store.now(), "step": msg})

    store.audit("apply_started", run=run_id, proposals=[p["id"] for p in props], by=who(args))

    # 1. isolated git worktree on a new branch
    branch = f"remediation/{run_id}"
    sh(["git", "worktree", "add", "-b", branch, str(ws), "HEAD"])
    step(f"worktree {ws.relative_to(ROOT)} on branch {branch}")

    # 2. sandbox database from a copy of production (no verification schema)
    admin, db = e["WAREHOUSE_ADMIN_USER"], e["WAREHOUSE_DB"]
    psql("postgres", admin, "drop database if exists datatrace_sandbox with (force);\n"
                            "create database datatrace_sandbox owner remediation_runner;\n"
                            "revoke connect on database datatrace_sandbox from public;")
    sh(["docker", "compose", "exec", "-T", "warehouse", "sh", "-c",
        f"pg_dump -U {admin} -d {db} --no-owner --no-privileges -n raw -n provider -n ops -n analytics "
        f"| psql -X -q -v ON_ERROR_STOP=1 -U remediation_runner -d datatrace_sandbox"])
    step("sandbox database datatrace_sandbox rebuilt from production copy")

    # 3. apply code patches in the worktree, commit on the branch
    for p in props:
        for c in p["changes"]:
            target = ws / c["path"]
            current = target.read_text() if target.exists() else ""
            if current != c["original"]:
                raise SystemExit(f"{p['id']}: {c['path']} changed since the proposal was made; re-propose")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(c["proposed"])
        if p["changes"]:
            step(f"{p['id']} applied to {', '.join(c['path'] for c in p['changes'])}")
    sh(["git", "add", "-A"], cwd=ws)
    msg = "Remediation " + run_id + "\n\n" + "\n".join(f"{p['id']}: {p['title']}" for p in props)
    sh(["git", "-c", "user.name=DATA TRACE remediation", "-c", "user.email=remediation@datatrace.local",
        "commit", "--allow-empty", "-m", msg], cwd=ws)

    dbt_env = {"REMEDIATION_RUNNER_PASSWORD": e["REMEDIATION_RUNNER_PASSWORD"], "WAREHOUSE_PORT": e.get("WAREHOUSE_PORT", "55432"),
               "DBT_RUNNER_PASSWORD": "unused-in-sandbox"}
    dbt_dir = ws / "dbt_project"

    # 4. validate, then backfills (sandbox only)
    r = sh([str(DBT), "parse", "--target", "sandbox"], cwd=dbt_dir, extra_env=dbt_env, check=False)
    (run_dir / "dbt_parse.txt").write_text(r.stdout + r.stderr)
    if r.returncode != 0:
        return finish(run_id, run_dir, props, log, False, {"error": "dbt parse failed", "output": r.stdout[-1500:]})
    step("dbt parse ok")
    for p in props:
        if p["kind"] == "backfill_sql":
            out = psql("datatrace_sandbox", "remediation_runner", f"begin;\n{p['sql'].rstrip().rstrip(';')};\ncommit;")
            step(f"{p['id']} backfill executed in sandbox")

    # 5a. deploy: recreate only the models whose code changed (as a release would), no downstream
    changed = sorted({Path(c["path"]).stem for p in props for c in p["changes"]
                      if c["path"].startswith("dbt_project/models/") and c["path"].endswith(".sql")})
    if changed:
        step(f"deploy changed models: dbt run --select {' '.join(changed)}")
        r = sh([str(DBT), "run", "--select", *changed, "--target", "sandbox"], cwd=dbt_dir, extra_env=dbt_env, check=False)
        (run_dir / "dbt_deploy.txt").write_text(r.stdout + r.stderr)
        if r.returncode != 0:
            return finish(run_id, run_dir, props, log, False, {"error": "deploy of changed models failed", "output": r.stdout[-1500:]})

    # 5b. the next nightly job, using the command from the PATCHED schedule
    import yaml
    jobs = yaml.safe_load((dbt_dir / "jobs" / "schedule.yml").read_text())["jobs"]
    nightly = next(j for j in jobs if j["name"] == "nightly")["command"].split()
    step(f"running nightly job: {' '.join(nightly)} --target sandbox")
    r = sh([str(DBT), *nightly[1:], "--target", "sandbox"], cwd=dbt_dir, extra_env=dbt_env, check=False)
    (run_dir / "dbt_nightly.txt").write_text(r.stdout + r.stderr)
    shutil.copy(dbt_dir / "target" / "run_results.json", run_dir / "run_results.json")
    rr = json.loads((run_dir / "run_results.json").read_text())
    counts = {}
    for x in rr["results"]:
        counts[x["status"]] = counts.get(x["status"], 0) + 1
    built = sorted(x["unique_id"].split(".")[-1] for x in rr["results"] if x["unique_id"].startswith("model."))

    # 6. verify against the provider statement
    rows = psql("datatrace_sandbox", "remediation_runner", """
        select s.statement_month, s.net_collections, m.net_revenue, m.built_at
        from provider.monthly_statement s
        left join analytics.monthly_revenue m on m.revenue_month = s.statement_month
        order by 1;""", tuples=True)
    months = []
    for line in rows.strip().splitlines():
        mth, provider, dash, built_at = line.split("|")
        months.append({"month": mth, "provider_net": provider, "sandbox_dashboard_net": dash or None,
                       "matches": bool(dash) and float(dash) == float(provider), "built_at": built_at})
    dbt_ok = counts.get("error", 0) == 0 and counts.get("fail", 0) == 0
    verified = dbt_ok and all(m["matches"] for m in months)
    return finish(run_id, run_dir, props, log, verified,
                  {"dbt_status_counts": counts, "models_built": built, "months": months,
                   "nightly_command": " ".join(nightly), "branch": branch})


def finish(run_id, run_dir, props, log, verified, details):
    result = {"run_id": run_id, "verified": verified, "proposals": [p["id"] for p in props],
              "finished_at": store.now(), **details, "steps": log,
              "note": "Sandbox only. Production (database datatrace, main branch) was not modified."}
    (run_dir / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    for p in props:
        p = store.load(p["id"])
        p["result"] = {"run_id": run_id, "verified": verified}
        if verified:
            p["status"] = "applied"
            p["history"].append({"at": store.now(), "status": "applied", "by": "remediation-runner", "note": run_id})
        store.save(p)
    store.audit("apply_finished", run=run_id, verified=verified)
    print(json.dumps({k: v for k, v in result.items() if k != "steps"}, indent=2))
    print(f"\n{'VERIFIED' if verified else 'NOT VERIFIED'}: details in {run_dir.relative_to(ROOT)}/")
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list").set_defaults(fn=cmd_list)
    s = sub.add_parser("show"); s.add_argument("id"); s.set_defaults(fn=cmd_show)
    for name, fn in (("approve", cmd_approve), ("reject", cmd_reject)):
        s = sub.add_parser(name); s.add_argument("ids", nargs="+"); s.add_argument("--by"); s.add_argument("--note")
        s.set_defaults(fn=fn)
    s = sub.add_parser("apply"); s.add_argument("ids", nargs="*"); s.add_argument("--by"); s.set_defaults(fn=cmd_apply)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
