"""Source-only Agent Fabric controlled capture corpus report."""

from __future__ import annotations

import json
from typing import Any

from depone.agent_fabric.capture_bridge import validate_capture_manifest
from depone.agent_fabric.claim_gate import canonical_hash
from depone.agent_fabric.dogfood_evidence import (
    READY_DECISION as READY_DOGFOOD_DECISION,
    build_dogfood_evidence_report,
)

REPORT_KIND = "agent-fabric-controlled-capture-corpus"
REPORT_SCHEMA_VERSION = "1.0"
READY_DECISION = "controlled-capture-corpus-ready-source-only"
DEFAULT_MIN_MANIFESTS = 2


def build_controlled_capture_corpus_report(
    capture_manifests: list[dict[str, Any]],
    *,
    min_manifests: int = DEFAULT_MIN_MANIFESTS,
) -> dict[str, Any]:
    """Summarize multiple controlled capture manifests without executing them."""
    manifest_records: list[dict[str, Any]] = []
    invalid_count = 0
    dogfood_ready_count = 0
    manifest_hashes: list[str] = []

    for index, capture_manifest in enumerate(capture_manifests):
        validation_errors = validate_capture_manifest(capture_manifest)
        dogfood_report = build_dogfood_evidence_report(capture_manifest)
        dogfood_decision = dogfood_report.get("decision")
        manifest_hash = canonical_hash(capture_manifest)
        manifest_hashes.append(manifest_hash)
        if validation_errors:
            invalid_count += 1
        if dogfood_decision == READY_DOGFOOD_DECISION:
            dogfood_ready_count += 1
        manifest_records.append(
            {
                "index": index,
                "capture_assurance": capture_manifest.get("assurance"),
                "capture_decision": capture_manifest.get("decision"),
                "dogfood_evidence_decision": dogfood_decision,
                "validation_errors": validation_errors,
                "source_hash": manifest_hash,
            }
        )

    duplicate_hashes = sorted(
        {
            hash_value
            for hash_value in manifest_hashes
            if manifest_hashes.count(hash_value) > 1
        }
    )

    blockers: list[dict[str, Any]] = []
    if len(capture_manifests) < min_manifests:
        blockers.append(
            {
                "code": "ERR_CAPTURE_CORPUS_TOO_NARROW",
                "message": "controlled capture coverage requires multiple manifests",
                "manifest_count": len(capture_manifests),
                "min_manifests": min_manifests,
            }
        )
        decision = "blocked-controlled-capture-too-narrow"
    elif duplicate_hashes:
        blockers.append(
            {
                "code": "ERR_CAPTURE_CORPUS_DUPLICATE",
                "message": "controlled capture corpus entries must be distinct",
                "duplicate_hashes": duplicate_hashes,
            }
        )
        decision = "blocked-duplicate-controlled-capture"
    elif invalid_count:
        blockers.append(
            {
                "code": "ERR_CAPTURE_CORPUS_INVALID",
                "message": "one or more controlled capture manifests failed validation",
                "invalid_manifest_count": invalid_count,
                "duplicate_manifest_count": len(duplicate_hashes),
            }
        )
        decision = "blocked-invalid-controlled-capture"
    elif dogfood_ready_count != len(capture_manifests):
        blockers.append(
            {
                "code": "ERR_CAPTURE_CORPUS_DOGFOOD_NOT_READY",
                "message": "one or more controlled captures are not dogfood-evidence ready",
                "dogfood_ready_count": dogfood_ready_count,
                "manifest_count": len(capture_manifests),
            }
        )
        decision = "blocked-controlled-capture-dogfood-not-ready"
    else:
        decision = READY_DECISION

    return {
        "kind": REPORT_KIND,
        "schema_version": REPORT_SCHEMA_VERSION,
        "decision": decision,
        "evidence_type": "controlled-capture-corpus",
        "summary": {
            "manifest_count": len(capture_manifests),
            "min_manifests": min_manifests,
            "dogfood_ready_count": dogfood_ready_count,
            "invalid_manifest_count": invalid_count,
            "duplicate_manifest_count": len(duplicate_hashes),
        },
        "manifests": manifest_records,
        "blockers": blockers,
        "source_hashes": {
            "capture_manifests": [
                canonical_hash(capture_manifest)
                for capture_manifest in capture_manifests
            ],
            "corpus": canonical_hash(capture_manifests),
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

    captures = [
        json.loads(
            Path("depone/fixtures/agent_fabric/capture_manifest_shell.json").read_text()
        ),
        json.loads(
            Path("depone/fixtures/agent_fabric/capture_manifest_shell_docs.json").read_text()
        ),
    ]
    report = build_controlled_capture_corpus_report(captures)
    if report["decision"] != READY_DECISION:
        raise AssertionError("expected multiple controlled captures to be ready")
    blocked = build_controlled_capture_corpus_report(captures[:1])
    if blocked["decision"] != "blocked-controlled-capture-too-narrow":
        raise AssertionError("expected single controlled capture to block as too narrow")
