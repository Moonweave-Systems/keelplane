"""V112 Agent Fabric compile-to-report smoke helper.

This module connects the existing V107-V111 source-only pieces without adding
execution. It compiles invocation packets, wraps the first packet in the V108
fixture shape, builds a V109 capture manifest, runs the V110 verifier over that
manifest, and renders the V111 operator view.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import Any

from depone.agent_fabric.capture_bridge import build_capture_manifest
from depone.agent_fabric.reference_adapter import build_reference_adapter_fixture
from depone.compile.agent_fabric import compile_agent_fabric
from depone.verify.adapters.base import EvidenceContext, EvidenceFile
from depone.verify.engine import run_verification
from depone.verify.operator_view import render_operator_view

SMOKE_KIND = "agent-fabric-compile-to-report-smoke"
SMOKE_VERSION = "1.0"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _evidence_file(path: str, data: dict[str, Any]) -> EvidenceFile:
    content = json.dumps(data, sort_keys=True)
    return EvidenceFile(path=path, content=content, sha256=_sha(content))


def _evidence_context(manifest: dict[str, Any]) -> EvidenceContext:
    metadata = {"run_id": "agent-fabric-lifecycle-smoke"}
    contract = {
        "schema_version": "v105.verify_wedge",
        "required_evidence": ["run-metadata.json"],
    }
    return EvidenceContext(
        run_id="agent-fabric-lifecycle-smoke",
        files=[
            _evidence_file("evidence-contract.json", contract),
            _evidence_file("run-metadata.json", metadata),
            _evidence_file("agent-fabric-capture-manifest.json", manifest),
        ],
        raw={"metadata": metadata},
    )


def _overall_decision(compile_decision: str, report_decision: str) -> str:
    if compile_decision == "blocked-unsupported-critical":
        return "blocked-compile"
    if report_decision != "pass":
        return "blocked-report"
    if compile_decision == "compile-with-approximations":
        return "ready-with-approximations"
    return "ready-for-operator-review"


def build_compile_to_report_smoke(
    profile: dict[str, Any],
    harness_name: str,
    role_contracts: list[dict[str, Any]],
    plan: dict[str, Any],
    *,
    observer_capture: dict[str, Any] | None = None,
    allowed_touched_files: list[str] | None = None,
) -> dict[str, Any]:
    """Build a deterministic smoke summary for the Agent Fabric source path."""

    bundle = compile_agent_fabric(profile, harness_name, role_contracts)
    invocations = bundle["invocations"]
    first_invocation = invocations[0] if invocations else {}
    fixture = build_reference_adapter_fixture(first_invocation)
    manifest = build_capture_manifest(
        fixture,
        observer_capture=observer_capture,
        allowed_touched_files=allowed_touched_files,
    )
    report = run_verification(plan, _evidence_context(manifest))
    report_data = asdict(report)
    compile_decision = str(bundle["compile_report"]["decision"])
    report_decision = str(report_data["decision"])

    return {
        "schema_version": SMOKE_VERSION,
        "kind": SMOKE_KIND,
        "compile_decision": compile_decision,
        "invocation_count": len(invocations),
        "first_invocation_instructions": str(first_invocation.get("instructions", "")),
        "capture_assurance": str(manifest.get("assurance", "A0-claims-only")),
        "report_decision": report_decision,
        "report_assurance": str(report_data["assurance"]),
        "overall_decision": _overall_decision(compile_decision, report_decision),
        "operator_view": render_operator_view(report),
    }
