"""Source-only Agent Fabric harness capability snapshot export."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from depone.compile.tool_mappings import (
    ABSTRACT_TOOLS,
    ALL_HARNESSES,
    STATUS_APPROXIMATED,
    STATUS_EXACT,
    STATUS_UNSUPPORTED_CRITICAL,
    resolve_tool,
)
from depone.contract.harness import HARNESS_SCHEMA_VERSION, validate_harness

SNAPSHOT_KIND = "agent-fabric-harness-capability-snapshot"
SNAPSHOT_SCHEMA_VERSION = "1.0"


def default_harness_names() -> list[str]:
    """Return harness names covered by the deterministic tool mapping table."""
    return list(ALL_HARNESSES)


def build_harness_snapshot(harness_names: list[str] | None = None) -> dict[str, Any]:
    """Build a source-only capability snapshot for the requested harnesses."""
    requested = list(harness_names or default_harness_names())
    harnesses: list[dict[str, Any]] = []
    unknown_harnesses: list[str] = []
    unsupported_critical: list[str] = []
    saw_approximation = False

    for name in requested:
        capability = _load_capability(name)
        if capability is None:
            unknown_harnesses.append(name)
            unsupported_critical.append(f"unknown harness capability: {name}")
            continue

        entry = _build_harness_entry(name, capability)
        harnesses.append(entry)
        if entry["status"] == STATUS_APPROXIMATED:
            saw_approximation = True
        elif entry["status"] == STATUS_UNSUPPORTED_CRITICAL:
            unsupported_critical.extend(entry["unsupported_critical"])

    if unsupported_critical:
        decision = "blocked-unsupported-critical"
    elif saw_approximation:
        decision = "snapshot-with-approximations"
    else:
        decision = "snapshot-exact"

    return {
        "kind": SNAPSHOT_KIND,
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "harness_schema_version": HARNESS_SCHEMA_VERSION,
        "requested_harnesses": requested,
        "decision": decision,
        "harnesses": harnesses,
        "unknown_harnesses": unknown_harnesses,
        "unsupported_critical": unsupported_critical,
        "summary": _summary(harnesses, unknown_harnesses),
    }


def _capability_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "fixtures" / "capabilities"


def _load_capability(name: str) -> dict[str, Any] | None:
    path = _capability_dir() / f"{name}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        return None
    return data


def _build_harness_entry(name: str, capability: dict[str, Any]) -> dict[str, Any]:
    mappings: list[dict[str, str]] = []
    counts = {
        STATUS_EXACT: 0,
        STATUS_APPROXIMATED: 0,
        STATUS_UNSUPPORTED_CRITICAL: 0,
    }
    exact_tools: list[str] = []
    approximated_tools: list[str] = []
    unsupported_tools: list[str] = []

    for label in sorted(ABSTRACT_TOOLS):
        info = resolve_tool(name, label)
        status = info["status"]
        counts[status] = counts.get(status, 0) + 1
        mappings.append(
            {
                "abstract_label": label,
                "concrete_name": info["tool_name"],
                "status": status,
                "notes": info["notes"],
            }
        )
        if status == STATUS_EXACT:
            exact_tools.append(label)
        elif status == STATUS_APPROXIMATED:
            approximated_tools.append(label)
        elif status == STATUS_UNSUPPORTED_CRITICAL:
            unsupported_tools.append(label)

    validation_errors = validate_harness(capability)
    unsupported_critical = [
        f"{name}: unsupported abstract tool {label}" for label in unsupported_tools
    ]
    unsupported_critical.extend(f"{name}: {err}" for err in validation_errors)

    if unsupported_critical:
        status = STATUS_UNSUPPORTED_CRITICAL
    elif approximated_tools:
        status = STATUS_APPROXIMATED
    else:
        status = STATUS_EXACT

    return {
        "name": name,
        "status": status,
        "capability": capability,
        "tool_mapping_status_counts": counts,
        "exact_tools": exact_tools,
        "approximated_tools": approximated_tools,
        "unsupported_critical_tools": unsupported_tools,
        "unsupported_critical": unsupported_critical,
        "mappings": mappings,
    }


def _summary(
    harnesses: list[dict[str, Any]], unknown_harnesses: list[str]
) -> dict[str, Any]:
    return {
        "harness_count": len(harnesses),
        "unknown_harness_count": len(unknown_harnesses),
        "exact_harnesses": [
            h["name"] for h in harnesses if h["status"] == STATUS_EXACT
        ],
        "approximated_harnesses": [
            h["name"] for h in harnesses if h["status"] == STATUS_APPROXIMATED
        ],
        "unsupported_critical_harnesses": [
            h["name"]
            for h in harnesses
            if h["status"] == STATUS_UNSUPPORTED_CRITICAL
        ],
    }


def _self_test() -> None:
    snapshot = build_harness_snapshot(["shell", "codex"])
    if snapshot["decision"] != "snapshot-with-approximations":
        raise AssertionError("expected shell+codex snapshot to record approximations")
    blocked = build_harness_snapshot(["missing-harness"])
    if blocked["decision"] != "blocked-unsupported-critical":
        raise AssertionError("expected unknown harness to block")
