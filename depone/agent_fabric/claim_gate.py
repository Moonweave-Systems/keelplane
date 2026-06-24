"""Source-only Agent Fabric public-claim gate."""

from __future__ import annotations

import hashlib
import json
from typing import Any

REPORT_KIND = "agent-fabric-claim-gate-report"
REPORT_SCHEMA_VERSION = "1.0"
DEFAULT_CLAIM_SCOPE = "public-benefit"


def canonical_hash(value: Any) -> str:
    """Return a stable SHA-256 hash for JSON-compatible values."""
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_claim_gate_report(
    adapter_smoke_report: dict[str, Any],
    claim_scope: str = DEFAULT_CLAIM_SCOPE,
) -> dict[str, Any]:
    """Gate public claims on paired evidence, without executing anything."""
    smoke_decision = adapter_smoke_report.get("decision")
    smoke_blockers = adapter_smoke_report.get("blockers")
    if not isinstance(smoke_blockers, list):
        smoke_blockers = []

    blockers: list[dict[str, Any]] = []
    if smoke_decision != "ready-source-only":
        decision = "blocked-adapter-smoke-not-ready"
        blockers.append(
            {
                "code": "ERR_ADAPTER_SMOKE_NOT_READY",
                "message": "adapter smoke report is not ready-source-only",
                "adapter_smoke_decision": smoke_decision,
            }
        )
    else:
        decision = "blocked-missing-paired-evidence"
        blockers.append(
            {
                "code": "ERR_PAIRED_EVIDENCE_REQUIRED",
                "message": (
                    "public claims require paired dogfood or approved "
                    "live adapter-smoke evidence"
                ),
                "adapter_smoke_decision": smoke_decision,
            }
        )

    return {
        "kind": REPORT_KIND,
        "schema_version": REPORT_SCHEMA_VERSION,
        "decision": decision,
        "claim_scope": claim_scope,
        "adapter_smoke_decision": smoke_decision,
        "adapter_smoke_harness": adapter_smoke_report.get("harness"),
        "adapter_smoke_blockers": smoke_blockers,
        "blockers": blockers,
        "source_hashes": {
            "adapter_smoke_report": canonical_hash(adapter_smoke_report),
        },
        "boundary": {
            "executes_commands": False,
            "calls_live_models": False,
            "detects_installed_harness": False,
            "inspects_mcp_runtime": False,
            "approves_public_claim": False,
            "trust_upgrade": False,
        },
    }


def _self_test() -> None:
    from pathlib import Path

    from depone.agent_fabric.adapter_smoke import build_adapter_smoke_report
    from depone.agent_fabric.harness_snapshot import build_harness_snapshot

    fixture_path = Path("depone/fixtures/agent_fabric/reference_adapter_shell.json")
    fixture = json.loads(fixture_path.read_text())
    smoke = build_adapter_smoke_report(fixture, build_harness_snapshot(["shell"]))
    report = build_claim_gate_report(smoke)
    if report["decision"] != "blocked-missing-paired-evidence":
        raise AssertionError("expected source-ready smoke to still block public claims")
    blocked_smoke = dict(smoke)
    blocked_smoke["decision"] = "blocked-harness-not-in-snapshot"
    blocked = build_claim_gate_report(blocked_smoke)
    if blocked["decision"] != "blocked-adapter-smoke-not-ready":
        raise AssertionError("expected blocked adapter smoke to block claim gate")
