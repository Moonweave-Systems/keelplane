"""Deterministic tool mapping table: abstract labels to harness-specific tools.

Each harness (codex, claude-code, opencode, shell) maps abstract tool labels
to concrete tool names with a status flag: exact, approximated, or
unsupported-critical.
"""

from __future__ import annotations

from typing import Any

# Harness name constants
HARNESS_CODEX = "codex"
HARNESS_CLAUDE_CODE = "claude-code"
HARNESS_OPENCODE = "opencode"
HARNESS_SHELL = "shell"
ALL_HARNESSES = [HARNESS_CODEX, HARNESS_CLAUDE_CODE, HARNESS_OPENCODE, HARNESS_SHELL]

# Abstract tool labels (from packaging/dwm-roles.json)
ABSTRACT_TOOLS = frozenset(
    {
        "read",
        "search",
        "inspect",
        "edit",
        "write",
        "test",
        "render",
        "smoke",
        "status",
        "summarize",
    }
)

# Status constants
STATUS_EXACT = "exact"
STATUS_APPROXIMATED = "approximated"
STATUS_UNSUPPORTED_CRITICAL = "unsupported-critical"

TOOL_MAPPINGS: dict[str, dict[str, dict[str, str]]] = {
    HARNESS_CODEX: {
        "read": {"tool_name": "Read", "status": "exact", "notes": ""},
        "search": {"tool_name": "Grep/Glob", "status": "exact", "notes": ""},
        "inspect": {
            "tool_name": "Read/Glob",
            "status": "exact",
            "notes": "codebase inspection",
        },
        "edit": {"tool_name": "Edit/Write", "status": "exact", "notes": ""},
        "write": {"tool_name": "Write", "status": "exact", "notes": ""},
        "test": {
            "tool_name": "Bash",
            "status": "exact",
            "notes": "run test commands via shell",
        },
        "render": {
            "tool_name": "Bash",
            "status": "approximated",
            "notes": "no dedicated render tool; use shell scripts",
        },
        "smoke": {
            "tool_name": "Bash",
            "status": "approximated",
            "notes": "smoke checks via shell",
        },
        "status": {
            "tool_name": "Bash/Read",
            "status": "approximated",
            "notes": "status via shell commands or file reads",
        },
        "summarize": {
            "tool_name": "Read",
            "status": "approximated",
            "notes": "summarize by reading files",
        },
    },
    HARNESS_CLAUDE_CODE: {
        "read": {"tool_name": "Read", "status": "exact", "notes": ""},
        "search": {"tool_name": "Grep/Glob", "status": "exact", "notes": ""},
        "inspect": {"tool_name": "Read/Glob", "status": "exact", "notes": ""},
        "edit": {"tool_name": "Edit/Write", "status": "exact", "notes": ""},
        "write": {"tool_name": "Write", "status": "exact", "notes": ""},
        "test": {"tool_name": "Bash", "status": "exact", "notes": ""},
        "render": {
            "tool_name": "Bash",
            "status": "approximated",
            "notes": "no dedicated render tool",
        },
        "smoke": {"tool_name": "Bash", "status": "approximated", "notes": ""},
        "status": {"tool_name": "Bash/Read", "status": "approximated", "notes": ""},
        "summarize": {"tool_name": "Read", "status": "approximated", "notes": ""},
    },
    HARNESS_OPENCODE: {
        "read": {"tool_name": "Read/look_at", "status": "exact", "notes": ""},
        "search": {"tool_name": "Grep/Glob/websearch", "status": "exact", "notes": ""},
        "inspect": {"tool_name": "Read/Glob/codegraph", "status": "exact", "notes": ""},
        "edit": {"tool_name": "Edit/Write", "status": "exact", "notes": ""},
        "write": {"tool_name": "Write", "status": "exact", "notes": ""},
        "test": {"tool_name": "Bash", "status": "exact", "notes": ""},
        "render": {
            "tool_name": "Bash",
            "status": "approximated",
            "notes": "via shell scripts",
        },
        "smoke": {
            "tool_name": "Bash/playwright",
            "status": "exact",
            "notes": "browser + shell available",
        },
        "status": {
            "tool_name": "Bash/Read/Grep",
            "status": "exact",
            "notes": "flexible inspection tools",
        },
        "summarize": {"tool_name": "Read/Grep", "status": "exact", "notes": ""},
    },
    HARNESS_SHELL: {
        "read": {"tool_name": "cat/head/tail", "status": "exact", "notes": ""},
        "search": {"tool_name": "rg/grep/find", "status": "exact", "notes": ""},
        "inspect": {"tool_name": "ls/file/stat", "status": "exact", "notes": ""},
        "edit": {"tool_name": "sed/echo>", "status": "exact", "notes": ""},
        "write": {"tool_name": "echo>/tee", "status": "exact", "notes": ""},
        "test": {"tool_name": "pytest/node/uv", "status": "exact", "notes": ""},
        "render": {"tool_name": "python3/rsvg/convert", "status": "exact", "notes": ""},
        "smoke": {"tool_name": "curl/ping", "status": "exact", "notes": ""},
        "status": {"tool_name": "git/ps/df", "status": "exact", "notes": ""},
        "summarize": {"tool_name": "wc/md5sum", "status": "exact", "notes": ""},
    },
}


def resolve_tool(harness_name: str, abstract_label: str) -> dict[str, str]:
    """Resolve an abstract label to harness-specific tool info.

    Returns dict with keys: tool_name, status, notes.
    """
    harness_map = TOOL_MAPPINGS.get(harness_name)
    if harness_map is None:
        return {
            "tool_name": "unknown",
            "status": STATUS_UNSUPPORTED_CRITICAL,
            "notes": f"unknown harness: {harness_name}",
        }
    result = harness_map.get(abstract_label)
    if result is None:
        return {
            "tool_name": "unknown",
            "status": STATUS_UNSUPPORTED_CRITICAL,
            "notes": f"unknown tool: {abstract_label}",
        }
    return dict(result)


def resolve_toolbelt(
    harness_name: str,
    abstract_tools: list[str],
    role_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve a toolbelt for a role from abstract tool labels.

    Returns dict with:
      - allowed_tools: list of concrete tool names
      - forbidden_tools: list of harness tool names NOT in the required set
      - output_schema: from role_context or "unknown"
      - evidence_obligations: from role_context or []
      - mappings: per-tool resolution details
      - overall_status: exact | approximated | unsupported-critical
    """
    ctx = role_context or {}
    resolved = []
    overall_status = STATUS_EXACT

    for label in abstract_tools:
        info = resolve_tool(harness_name, label)
        resolved.append(
            {
                "abstract_label": label,
                "concrete_name": info["tool_name"],
                "status": info["status"],
                "notes": info["notes"],
            }
        )
        if info["status"] == STATUS_UNSUPPORTED_CRITICAL:
            overall_status = STATUS_UNSUPPORTED_CRITICAL
        elif (
            info["status"] == STATUS_APPROXIMATED
            and overall_status != STATUS_UNSUPPORTED_CRITICAL
        ):
            overall_status = STATUS_APPROXIMATED

    # Allowed tools: concatenate concrete names from resolved mappings
    allowed_tools: list[str] = []
    for m in resolved:
        for part in m["concrete_name"].split("/"):
            stripped = part.strip()
            if stripped and stripped not in allowed_tools:
                allowed_tools.append(stripped)

    # Forbidden: all tools the harness supports minus those in allowed set
    harness_map = TOOL_MAPPINGS.get(harness_name, {})
    supported_labels = set(harness_map.keys())
    required_labels = set(abstract_tools)
    # The "forbidden" abstract labels are those the harness supports but this role doesn't need
    forbidden_labels = supported_labels - required_labels
    forbidden_tools: list[str] = []
    for label in sorted(forbidden_labels):
        info = harness_map.get(label)
        if info:
            for part in info["tool_name"].split("/"):
                stripped = part.strip()
                if stripped and stripped not in forbidden_tools:
                    forbidden_tools.append(stripped)

    return {
        "allowed_tools": allowed_tools,
        "forbidden_tools": forbidden_tools,
        "output_schema": ctx.get("output_schema", "unknown"),
        "evidence_obligations": ctx.get("evidence_obligations", []),
        "mappings": resolved,
        "overall_status": overall_status,
    }


def _self_test() -> None:
    """Run basic self-test to verify all mappings are complete."""
    all_pass = True
    for harness in ALL_HARNESSES:
        print(f"\n=== {harness} ===")
        harness_map = TOOL_MAPPINGS.get(harness, {})
        for label in sorted(ABSTRACT_TOOLS):
            info = harness_map.get(label)
            if info:
                print(f"  {label:15s} -> {info['tool_name']:20s} [{info['status']}]")
            else:
                print(f"  {label:15s} -> MISSING")
                all_pass = False
        has_all = all(label in harness_map for label in ABSTRACT_TOOLS)
        print(f"  ---> {'COMPLETE' if has_all else 'INCOMPLETE'}")

    print(f"\n{'PASS' if all_pass else 'FAIL'}")
