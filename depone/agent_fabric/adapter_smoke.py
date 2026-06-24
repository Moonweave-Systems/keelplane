"""Source-only Agent Fabric adapter smoke report."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from depone.agent_fabric.reference_adapter import validate_reference_adapter_fixture

REPORT_KIND = "agent-fabric-adapter-smoke-report"
REPORT_SCHEMA_VERSION = "1.0"


def canonical_hash(value: Any) -> str:
    """Return a stable SHA-256 hash for JSON-compatible values."""
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_adapter_smoke_report(
    adapter_fixture: dict[str, Any], harness_snapshot: dict[str, Any]
) -> dict[str, Any]:
    """Bind a reference adapter fixture to a source-only harness snapshot."""
    adapter = (
        adapter_fixture.get("adapter") if isinstance(adapter_fixture, dict) else {}
    )
    capture = (
        adapter_fixture.get("capture") if isinstance(adapter_fixture, dict) else {}
    )
    harness = adapter.get("harness") if isinstance(adapter, dict) else None
    adapter_mode = adapter.get("mode") if isinstance(adapter, dict) else None
    executes_commands = (
        adapter.get("executes_commands") if isinstance(adapter, dict) else None
    )
    trust_level = capture.get("trust_level") if isinstance(capture, dict) else None

    validation_errors = validate_reference_adapter_fixture(adapter_fixture)
    blockers: list[dict[str, Any]] = []
    harness_entry = _find_harness_entry(harness_snapshot, harness)

    if validation_errors:
        blockers.append(
            {
                "code": "ERR_ADAPTER_FIXTURE_INVALID",
                "message": "adapter fixture failed validation",
            }
        )
        decision = "blocked-invalid-adapter-fixture"
    elif harness_entry is None:
        blockers.append(
            {
                "code": "ERR_ADAPTER_HARNESS_NOT_SNAPSHOTTED",
                "message": "adapter harness is absent from the harness snapshot",
                "harness": harness,
            }
        )
        decision = "blocked-harness-not-in-snapshot"
    elif harness_entry.get("status") == "unsupported-critical":
        blockers.append(
            {
                "code": "ERR_ADAPTER_HARNESS_UNSUPPORTED_CRITICAL",
                "message": "adapter harness snapshot is unsupported-critical",
                "harness": harness,
            }
        )
        decision = "blocked-unsupported-critical"
    else:
        decision = "ready-source-only"

    return {
        "kind": REPORT_KIND,
        "schema_version": REPORT_SCHEMA_VERSION,
        "decision": decision,
        "harness": harness,
        "harness_status": harness_entry.get("status") if harness_entry else None,
        "adapter_name": adapter.get("name") if isinstance(adapter, dict) else None,
        "adapter_mode": adapter_mode,
        "executes_commands": executes_commands,
        "trust_level": trust_level,
        "validation_errors": validation_errors,
        "blockers": blockers,
        "source_hashes": {
            "adapter_fixture": canonical_hash(adapter_fixture),
            "harness_snapshot": canonical_hash(harness_snapshot),
        },
        "boundary": {
            "executes_commands": False,
            "calls_live_models": False,
            "detects_installed_harness": False,
            "inspects_mcp_runtime": False,
            "trust_upgrade": False,
        },
    }


def _find_harness_entry(
    harness_snapshot: dict[str, Any], harness: Any
) -> dict[str, Any] | None:
    if not isinstance(harness, str):
        return None
    entries = harness_snapshot.get("harnesses", [])
    if not isinstance(entries, list):
        return None
    for entry in entries:
        if isinstance(entry, dict) and entry.get("name") == harness:
            return entry
    return None


def _self_test() -> None:
    from pathlib import Path

    from depone.agent_fabric.harness_snapshot import build_harness_snapshot

    fixture_path = Path("depone/fixtures/agent_fabric/reference_adapter_shell.json")
    fixture = json.loads(fixture_path.read_text())
    report = build_adapter_smoke_report(fixture, build_harness_snapshot(["shell"]))
    if report["decision"] != "ready-source-only":
        raise AssertionError("expected shell reference fixture to be source-ready")
    blocked = build_adapter_smoke_report(fixture, build_harness_snapshot(["codex"]))
    if blocked["decision"] != "blocked-harness-not-in-snapshot":
        raise AssertionError("expected missing harness to block")
