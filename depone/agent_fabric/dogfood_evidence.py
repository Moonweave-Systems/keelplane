"""Source-only Agent Fabric dogfood evidence report."""

from __future__ import annotations

import json
from typing import Any

from depone.agent_fabric.capture_bridge import validate_capture_manifest
from depone.agent_fabric.claim_gate import canonical_hash

REPORT_KIND = "agent-fabric-dogfood-evidence"
CORPUS_REPORT_KIND = "agent-fabric-dogfood-evidence-corpus"
REPORT_SCHEMA_VERSION = "1.0"
READY_DECISION = "dogfood-evidence-ready-source-only"
CORPUS_READY_DECISION = "dogfood-corpus-ready-source-only"
CORPUS_BLOCKED_DECISION = "blocked-dogfood-corpus-not-ready"


def build_dogfood_evidence_report(capture_manifest: dict[str, Any]) -> dict[str, Any]:
    """Build source-only dogfood evidence from an observed capture manifest."""
    validation_errors = validate_capture_manifest(capture_manifest)
    assurance = capture_manifest.get("assurance")
    capture_decision = capture_manifest.get("decision")
    observer_capture = (
        capture_manifest.get("observer_capture")
        if isinstance(capture_manifest.get("observer_capture"), dict)
        else {}
    )
    test_output = (
        observer_capture.get("test_output")
        if isinstance(observer_capture.get("test_output"), dict)
        else {}
    )
    test_status = test_output.get("status")
    blockers: list[dict[str, Any]] = []

    if validation_errors:
        blockers.append(
            {
                "code": "ERR_CAPTURE_MANIFEST_INVALID",
                "message": "capture manifest failed validation",
                "validation_errors": validation_errors,
            }
        )
        decision = "blocked-invalid-capture-manifest"
    elif assurance != "A1-local-observed" or capture_decision != "observed-local-capture":
        blockers.append(
            {
                "code": "ERR_CAPTURE_NOT_A1_OBSERVED",
                "message": "dogfood evidence requires A1 local observed capture",
                "capture_assurance": assurance,
                "capture_decision": capture_decision,
            }
        )
        decision = "blocked-capture-not-observed"
    elif test_status != "passed":
        blockers.append(
            {
                "code": "ERR_DOGFOOD_TESTS_NOT_PASSED",
                "message": "observed dogfood test output did not pass",
                "test_status": test_status,
            }
        )
        decision = "blocked-dogfood-tests-not-passed"
    else:
        decision = READY_DECISION

    return {
        "kind": REPORT_KIND,
        "schema_version": REPORT_SCHEMA_VERSION,
        "decision": decision,
        "evidence_type": "paired-dogfood",
        "capture_assurance": assurance,
        "capture_decision": capture_decision,
        "test_status": test_status,
        "validation_errors": validation_errors,
        "blockers": blockers,
        "source_hashes": {
            "capture_manifest": canonical_hash(capture_manifest),
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


def build_dogfood_evidence_corpus_report(
    capture_manifests: list[tuple[str, dict[str, Any]]],
) -> dict[str, Any]:
    """Build a source-only readiness summary for multiple capture manifests."""
    entries: list[dict[str, Any]] = []
    ready_count = 0
    blocked_count = 0

    for manifest_id, capture_manifest in capture_manifests:
        report = build_dogfood_evidence_report(capture_manifest)
        if report["decision"] == READY_DECISION:
            ready_count += 1
        else:
            blocked_count += 1
        entries.append(
            {
                "id": manifest_id,
                "decision": report["decision"],
                "capture_assurance": report["capture_assurance"],
                "capture_decision": report["capture_decision"],
                "test_status": report["test_status"],
                "blockers": report["blockers"],
                "source_hashes": report["source_hashes"],
            }
        )

    decision = (
        CORPUS_READY_DECISION
        if capture_manifests and blocked_count == 0
        else CORPUS_BLOCKED_DECISION
    )

    return {
        "kind": CORPUS_REPORT_KIND,
        "schema_version": REPORT_SCHEMA_VERSION,
        "decision": decision,
        "evidence_type": "paired-dogfood-corpus",
        "summary": {
            "total_manifests": len(capture_manifests),
            "ready_manifests": ready_count,
            "blocked_manifests": blocked_count,
        },
        "entries": entries,
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

    capture = json.loads(
        Path("depone/fixtures/agent_fabric/capture_manifest_shell.json").read_text()
    )
    report = build_dogfood_evidence_report(capture)
    if report["decision"] != READY_DECISION:
        raise AssertionError("expected observed capture to produce dogfood evidence")
    a0_capture = dict(capture)
    a0_capture.update(
        {
            "assurance": "A0-claims-only",
            "decision": "claims-only",
            "observer_capture": None,
            "observer_capture_hash": None,
        }
    )
    blocked = build_dogfood_evidence_report(a0_capture)
    if blocked["decision"] != "blocked-capture-not-observed":
        raise AssertionError("expected A0 capture to block dogfood evidence")
