"""Source-only Agent Fabric dogfood evidence report."""

from __future__ import annotations

import json
from typing import Any

from depone.agent_fabric.capture_bridge import validate_capture_manifest
from depone.agent_fabric.claim_gate import canonical_hash

REPORT_KIND = "agent-fabric-dogfood-evidence"
CORPUS_REPORT_KIND = "agent-fabric-controlled-capture-corpus"
REPORT_SCHEMA_VERSION = "1.0"
READY_DECISION = "dogfood-evidence-ready-source-only"
CORPUS_READY_DECISION = "controlled-capture-corpus-ready"


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


def build_controlled_capture_corpus_report(
    capture_manifests: list[dict[str, Any]],
) -> dict[str, Any]:
    """Summarize source-only dogfood readiness across controlled captures."""
    entries: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    capture_hashes: list[str] = []

    for index, capture_manifest in enumerate(capture_manifests):
        report = build_dogfood_evidence_report(capture_manifest)
        capture_hash = canonical_hash(capture_manifest)
        capture_hashes.append(capture_hash)
        entry = {
            "index": index,
            "decision": report["decision"],
            "capture_assurance": report["capture_assurance"],
            "capture_decision": report["capture_decision"],
            "test_status": report["test_status"],
            "source_hash": capture_hash,
            "blockers": report["blockers"],
        }
        entries.append(entry)
        if report["decision"] != READY_DECISION:
            blockers.append(
                {
                    "code": "ERR_CONTROLLED_CAPTURE_NOT_READY",
                    "message": "controlled capture did not produce ready dogfood evidence",
                    "index": index,
                    "decision": report["decision"],
                    "blockers": report["blockers"],
                }
            )

    capture_count = len(capture_manifests)
    ready_count = sum(1 for entry in entries if entry["decision"] == READY_DECISION)
    if capture_count < 2:
        blockers.append(
            {
                "code": "ERR_CONTROLLED_CAPTURE_CORPUS_TOO_SMALL",
                "message": "controlled capture corpus requires at least two manifests",
                "capture_count": capture_count,
            }
        )
    if len(set(capture_hashes)) != len(capture_hashes):
        blockers.append(
            {
                "code": "ERR_CONTROLLED_CAPTURE_CORPUS_DUPLICATE",
                "message": "controlled capture corpus requires distinct manifests",
            }
        )

    if blockers:
        decision = "blocked-insufficient-capture-corpus"
    else:
        decision = CORPUS_READY_DECISION

    return {
        "kind": CORPUS_REPORT_KIND,
        "schema_version": REPORT_SCHEMA_VERSION,
        "decision": decision,
        "capture_count": capture_count,
        "ready_count": ready_count,
        "blocked_count": capture_count - ready_count,
        "entries": entries,
        "blockers": blockers,
        "source_hashes": {
            "capture_manifests": capture_hashes,
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

    capture = json.loads(
        Path("depone/fixtures/agent_fabric/capture_manifest_shell.json").read_text()
    )
    docs_capture = json.loads(
        Path(
            "depone/fixtures/agent_fabric/capture_manifest_docs_source_only.json"
        ).read_text()
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
    corpus = build_controlled_capture_corpus_report([capture, docs_capture])
    if corpus["decision"] != CORPUS_READY_DECISION:
        raise AssertionError("expected two valid captures to produce ready corpus")
