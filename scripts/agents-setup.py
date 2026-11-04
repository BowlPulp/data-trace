#!/usr/bin/env python3
"""
Generates each agent's machine-specific Claude Code config inside agents/<name>/:
  .mcp.json               the read-only warehouse MCP server, with that agent's database role
  .claude/settings.json   tool permissions, readable directories, MCP auto-approval

Claude Code reads these because Switch starts each agent's session in its agents/<name>/ directory.
Nothing global is touched. Re-run after moving the project. Outputs are gitignored (absolute paths).
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / ".venv" / "bin" / "python"
SERVER = ROOT / "tools" / "warehouse_mcp" / "server.py"

def abs_rule(tool: str, p: Path, glob: bool = True) -> str:
    return f"{tool}(/{p}{'/**' if glob else ''})"   # "//abs/path" = absolute path in Claude Code rules

# Paths no investigation agent may read: generator + ground truth, secrets, raw audit logs, scripts, git.
FORBIDDEN = [ROOT / "database", ROOT / "logs", ROOT / "scripts", ROOT / ".git", ROOT / "tools"]
FORBIDDEN_FILES = [ROOT / ".env"]

AGENTS = {
    "orchestrator":          {"role": None,       "dirs": []},
    "source-investigator":   {"role": "source",   "dirs": []},
    "pipeline-investigator": {"role": "pipeline", "dirs": [ROOT / "dbt_project", ROOT / "pipeline_logs"]},
    "metrics-investigator":  {"role": "metrics",  "dirs": [ROOT / "metrics"]},
}

for name, cfg in AGENTS.items():
    adir = ROOT / "agents" / name
    (adir / ".claude").mkdir(parents=True, exist_ok=True)

    allow = ["mcp__switch", "mcp__remediation"]
    if cfg["role"]:
        allow.append("mcp__warehouse")
    if cfg["dirs"]:
        allow += ["Read", "Grep", "Glob"]

    deny = ["Bash", "Write", "Edit", "NotebookEdit", "WebFetch", "WebSearch"]
    deny += [abs_rule("Read", p) for p in FORBIDDEN]   # Read rules also govern Grep and Glob
    deny += [abs_rule("Read", f, glob=False) for f in FORBIDDEN_FILES]
    deny += [f"Read(/{ROOT}/.env.*)"]
    # Agents may not read each other's working directories (their .switch tokens live there).
    deny += [abs_rule("Read", ROOT / "agents" / other) for other in AGENTS if other != name]

    settings = {
        "permissions": {
            "allow": allow,
            "deny": deny,
            "additionalDirectories": [str(d) for d in cfg["dirs"]],
        },
        "enabledMcpjsonServers": (["warehouse"] if cfg["role"] else []) + ["remediation"],
    }
    (adir / ".claude" / "settings.json").write_text(json.dumps(settings, indent=2) + "\n")

    mcp = {"mcpServers": {}}
    if cfg["role"]:
        mcp["mcpServers"]["warehouse"] = {
            "type": "stdio",
            "command": str(PY),
            "args": [str(SERVER), "--role", cfg["role"]],
        }
    mcp["mcpServers"]["remediation"] = {
        "type": "stdio",
        "command": str(PY),
        "args": [str(ROOT / "tools" / "remediation" / "mcp_server.py"),
                 "--mode", "propose" if name == "pipeline-investigator" else "read", "--agent", name],
    }
    (adir / ".mcp.json").write_text(json.dumps(mcp, indent=2) + "\n")
    print(f"{name:<22} role={cfg['role'] or '-':<9} extra dirs={[d.name for d in cfg['dirs']] or '-'}")

(ROOT / "pipeline_logs").mkdir(exist_ok=True)
print(f"\nDone. Register each agent in Switch Console with Directory = {ROOT}/agents/<name>")
