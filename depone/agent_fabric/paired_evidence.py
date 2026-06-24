"""Source-only Agent Fabric paired dogfood evidence report."""

from __future__ import annotations

import json
from typing import Any

from depone.agent_fabric.claim_gate import canonical_hash

REPORT_KIND = "agent-fabric-paired-evidence-report"
REPORT_SCHEMA_VERSION = "1.0"
DEFAULT_CLAIM_SCOPE = "public-benefit"
READY_DECISION = "paired-evidence-ready-source-only"
READY_DOGFOOD_DECISION = "dogfood-evidence-ready-source-only"


def build_paired_evidence_report(
    adapter_smoke_report: dict[str, Any],
    dogfood_evidence: dict[str, Any],
    claim_scope: str = DEFAULT_CLAIM_SCOPE,
) -> dict[str, Any]:
    """Bind adapter smoke and dogfood evidence without executing anything."""
    adapter_decision = adapter_smoke_report.get("decision")
    dogfood_decision = dogfood_evidence.get("decision")
    blockers: list[dict[str, Any]] = []

    if adapter_decision != "ready-source-only":
        blockers.append(
            {
                "code": "ERR_ADAPTER_SMOKE_NOT_READY",
                "message": "adapter smoke report is not ready-source-only",
                "adapter_smoke_decision": adapter_decision,
            }
        )
        decision = "blocked-adapter-smoke-not-ready"
    else:
        _append_dogfood_blockers(dogfood_evidence, blockers)
        decision = (
            "blocked-dogfood-evidence-not-ready" if blockers else READY_DECISION
        )

    return {
        "kind": REPORT_KIND,
        "schema_version": REPORT_SCHEMA_VERSION,
        "decision": decision,
        "evidence_type": "paired-dogfood",
        "claim_scope": claim_scope,
        "adapter_smoke_decision": adapter_decision,
        "dogfood_evidence_decision": dogfood_decision,
        "blockers": blockers,
        "source_hashes": {
            "adapter_smoke_report": canonical_hash(adapter_smoke_report),
            "dogfood_evidence": canonical_hash(dogfood_evidence),
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


def _append_dogfood_blockers(
    dogfood_evidence: dict[str, Any], blockers: list[dict[str, Any]]
) -> None:
    dogfood_decision = dogfood_evidence.get("decision")
    if dogfood_decision != READY_DOGFOOD_DECISION:
        blockers.append(
            {
                "code": "ERR_DOGFOOD_EVIDENCE_NOT_READY",
                "message": "dogfood evidence is not source-ready",
                "dogfood_evidence_decision": dogfood_decision,
            }
        )

    boundary = (
        dogfood_evidence.get("boundary")
        if isinstance(dogfood_evidence.get("boundary"), dict)
        else {}
    )
    if boundary.get("approves_public_claim") is not False:
        blockers.append(
            {
                "code": "ERR_DOGFOOD_EVIDENCE_PUBLIC_CLAIM_APPROVAL",
                "message": "dogfood evidence must not approve public claims",
            }
        )
    if boundary.get("executes_commands") is not False:
        blockers.append(
            {
                "code": "ERR_DOGFOOD_EVIDENCE_EXECUTES_COMMANDS",
                "message": "dogfood evidence for this gate must be source-only",
            }
        )
    if boundary.get("calls_live_models") is not False:
        blockers.append(
            {
                "code": "ERR_DOGFOOD_EVIDENCE_CALLS_LIVE_MODELS",
                "message": "dogfood evidence for this gate must not call live models",
            }
        )


def _self_test() -> None:
    from pathlib import Path

    from depone.agent_fabric.adapter_smoke import build_adapter_smoke_report
    from depone.agent_fabric.harness_snapshot import build_harness_snapshot

    fixture = json.loads(
        Path("depone/fixtures/agent_fabric/reference_adapter_shell.json").read_text()
    )
    smoke = build_adapter_smoke_report(fixture, build_harness_snapshot(["shell"]))
    dogfood = {
        "kind": "agent-fabric-dogfood-evidence",
        "decision": READY_DOGFOOD_DECISION,
        "evidence_type": "paired-dogfood",
        "boundary": {
            "executes_commands": False,
            "calls_live_models": False,
            "approves_public_claim": False,
        },
    }
    report = build_paired_evidence_report(smoke, dogfood)
    if report["decision"] != READY_DECISION:
        raise AssertionError("expected ready paired source-only evidence")
    blocked_smoke = dict(smoke)
    blocked_smoke["decision"] = "blocked-harness-not-in-snapshot"
    blocked = build_paired_evidence_report(blocked_smoke, dogfood)
    if blocked["decision"] != "blocked-adapter-smoke-not-ready":
        raise AssertionError("expected blocked adapter smoke to block paired evidence")
    overclaim = dict(dogfood)
    overclaim["boundary"] = dict(dogfood["boundary"])
    overclaim["boundary"]["approves_public_claim"] = True
    blocked_dogfood = build_paired_evidence_report(smoke, overclaim)
    if blocked_dogfood["decision"] != "blocked-dogfood-evidence-not-ready":
        raise AssertionError("expected overclaiming dogfood evidence to block")
