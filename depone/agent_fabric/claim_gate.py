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
    paired_evidence: dict[str, Any] | None = None,
    controlled_capture_corpus: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Gate public claims on paired or corpus evidence, without executing anything."""
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
    elif paired_evidence is not None:
        decision = _paired_evidence_decision(
            adapter_smoke_report,
            paired_evidence,
            blockers,
        )
    elif controlled_capture_corpus is not None:
        decision = _controlled_capture_corpus_decision(
            controlled_capture_corpus,
            blockers,
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
        "paired_evidence_decision": (
            paired_evidence.get("decision")
            if isinstance(paired_evidence, dict)
            else None
        ),
        "controlled_capture_corpus_decision": (
            controlled_capture_corpus.get("decision")
            if isinstance(controlled_capture_corpus, dict)
            else None
        ),
        "requires_human_review": decision == "ready-for-public-claim-review",
        "blockers": blockers,
        "source_hashes": {
            "adapter_smoke_report": canonical_hash(adapter_smoke_report),
            **(
                {"paired_evidence_report": canonical_hash(paired_evidence)}
                if paired_evidence is not None
                else {}
            ),
            **(
                {
                    "controlled_capture_corpus_report": canonical_hash(
                        controlled_capture_corpus
                    )
                }
                if controlled_capture_corpus is not None
                else {}
            ),
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


def _paired_evidence_decision(
    adapter_smoke_report: dict[str, Any],
    paired_evidence: dict[str, Any],
    blockers: list[dict[str, Any]],
) -> str:
    evidence_hashes = (
        paired_evidence.get("source_hashes")
        if isinstance(paired_evidence.get("source_hashes"), dict)
        else {}
    )
    if paired_evidence.get("decision") != "paired-evidence-ready-source-only":
        blockers.append(
            {
                "code": "ERR_PAIRED_EVIDENCE_NOT_READY",
                "message": "paired evidence is not source-ready",
                "paired_evidence_decision": paired_evidence.get("decision"),
            }
        )
    if evidence_hashes.get("adapter_smoke_report") != canonical_hash(
        adapter_smoke_report
    ):
        blockers.append(
            {
                "code": "ERR_PAIRED_EVIDENCE_HASH_MISMATCH",
                "message": "paired evidence does not bind the adapter smoke report",
            }
        )
    boundary = (
        paired_evidence.get("boundary")
        if isinstance(paired_evidence.get("boundary"), dict)
        else {}
    )
    if boundary.get("approves_public_claim") is not False:
        blockers.append(
            {
                "code": "ERR_PAIRED_EVIDENCE_PUBLIC_CLAIM_APPROVAL",
                "message": "paired evidence must not approve public claims",
            }
        )
    if blockers:
        return "blocked-paired-evidence-not-ready"
    return "ready-for-public-claim-review"


def _controlled_capture_corpus_decision(
    controlled_capture_corpus: dict[str, Any], blockers: list[dict[str, Any]]
) -> str:
    ready_decisions = {
        "controlled-capture-corpus-ready",
        "controlled-capture-corpus-ready-source-only",
    }
    corpus_decision = controlled_capture_corpus.get("decision")
    if corpus_decision not in ready_decisions:
        blockers.append(
            {
                "code": "ERR_CONTROLLED_CAPTURE_CORPUS_NOT_READY",
                "message": "controlled capture corpus is not source-ready",
                "controlled_capture_corpus_decision": corpus_decision,
            }
        )

    boundary = (
        controlled_capture_corpus.get("boundary")
        if isinstance(controlled_capture_corpus.get("boundary"), dict)
        else {}
    )
    if boundary.get("approves_public_claim") is not False:
        blockers.append(
            {
                "code": "ERR_CONTROLLED_CAPTURE_CORPUS_PUBLIC_CLAIM_APPROVAL",
                "message": "controlled capture corpus must not approve public claims",
            }
        )
    if boundary.get("executes_commands") is not False:
        blockers.append(
            {
                "code": "ERR_CONTROLLED_CAPTURE_CORPUS_EXECUTES_COMMANDS",
                "message": "controlled capture corpus for this gate must be source-only",
            }
        )
    if boundary.get("calls_live_models") is not False:
        blockers.append(
            {
                "code": "ERR_CONTROLLED_CAPTURE_CORPUS_CALLS_LIVE_MODELS",
                "message": "controlled capture corpus for this gate must not call live models",
            }
        )
    if boundary.get("trust_upgrade") is not False:
        blockers.append(
            {
                "code": "ERR_CONTROLLED_CAPTURE_CORPUS_TRUST_UPGRADE",
                "message": "controlled capture corpus must not upgrade trust",
            }
        )

    if blockers:
        return "blocked-controlled-capture-corpus-not-ready"
    return "ready-for-public-claim-review"


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
    paired_evidence = {
        "decision": "paired-evidence-ready-source-only",
        "source_hashes": {"adapter_smoke_report": canonical_hash(smoke)},
        "boundary": {"approves_public_claim": False},
    }
    ready = build_claim_gate_report(smoke, paired_evidence=paired_evidence)
    if ready["decision"] != "ready-for-public-claim-review":
        raise AssertionError("expected paired evidence to move claim gate to review")
    corpus = {
        "decision": "controlled-capture-corpus-ready",
        "boundary": {
            "executes_commands": False,
            "calls_live_models": False,
            "approves_public_claim": False,
            "trust_upgrade": False,
        },
    }
    corpus_ready = build_claim_gate_report(smoke, controlled_capture_corpus=corpus)
    if corpus_ready["decision"] != "ready-for-public-claim-review":
        raise AssertionError("expected controlled capture corpus to move claim gate to review")
