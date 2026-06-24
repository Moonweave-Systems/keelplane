"""Tests for surfacing Agent Fabric capture assurance in verification reports."""

from __future__ import annotations

import hashlib
import json
import unittest

from depone.agent_fabric.capture_bridge import build_capture_manifest
from depone.agent_fabric.reference_adapter import build_reference_adapter_fixture
from depone.verify.adapters.base import EvidenceContext, EvidenceFile
from depone.verify.engine import run_verification


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _file(path: str, content: str) -> EvidenceFile:
    return EvidenceFile(path=path, content=content, sha256=_sha(content))


def _plan() -> dict:
    return {
        "schema_version": "0.5",
        "plan_id": "agent-fabric-assurance-test",
        "created_by": "depone",
        "source_prompt": "test",
        "activation": {"decision": "activate", "matched_thresholds": []},
        "phases": [{"id": "phase-1", "title": "Phase 1"}],
        "handoffs": [],
        "risk_gates": [],
        "verification": [],
        "budget": {},
    }


def _base_evidence_files(manifest: dict) -> list[EvidenceFile]:
    contract = json.dumps(
        {
            "schema_version": "v105.verify_wedge",
            "required_evidence": ["run-metadata.json"],
        },
        sort_keys=True,
    )
    metadata = json.dumps({"run_id": "assurance-test-run"}, sort_keys=True)
    manifest_text = json.dumps(manifest, sort_keys=True)
    return [
        _file("evidence-contract.json", contract),
        _file("run-metadata.json", metadata),
        _file("agent-fabric-capture-manifest.json", manifest_text),
    ]


def _fixture() -> dict:
    invocation = {
        "packet_version": "1.0",
        "target_harness": "shell",
        "profile": "self-test-profile",
        "role": "runner",
        "toolbelt": {
            "allowed_tools": ["cat", "python3"],
            "allowed_mcp": [],
            "forbidden_tools": ["write"],
            "context_policy": "local-code-only",
            "output_schema": "runner-result-v1",
            "evidence_obligations": ["command_receipt"],
        },
        "instructions": "Run local checks and report outputs.",
        "evidence_obligations": ["command_receipt"],
        "context_policy": "local-code-only",
    }
    result = {
        "result_version": "1.0",
        "agent_role": "runner",
        "profile": "self-test-profile",
        "status": "success",
        "output_files": ["out/agent/result.txt"],
        "self_reported_claims": ["checks completed"],
        "command_receipts": [],
    }
    return build_reference_adapter_fixture(invocation, self_report=result)


def _a1_manifest() -> dict:
    return build_capture_manifest(
        _fixture(),
        observer_capture={
            "observed_by": "depone-observer",
            "source_fixture_hash": "",
            "diff_summary": {"changed_files": ["depone/example.py"]},
            "touched_files": ["depone/example.py"],
            "test_output": {"status": "passed", "summary": "1 passed"},
            "command_receipts": [
                {"command": ["python3", "test.py"], "exit_code": 0}
            ],
        },
        allowed_touched_files=["depone/example.py"],
    )


class VerificationReportAssuranceTests(unittest.TestCase):
    def test_valid_a1_capture_surfaces_pass_decision_and_a1_assurance(self) -> None:
        evidence = EvidenceContext(
            run_id="assurance-test-run",
            files=_base_evidence_files(_a1_manifest()),
            raw={"metadata": {"run_id": "assurance-test-run"}},
        )

        report = run_verification(_plan(), evidence)

        self.assertEqual(report.verdict, "verified")
        self.assertEqual(report.decision, "pass")
        self.assertEqual(report.assurance, "A1-local-observed")
        self.assertEqual(report.agent_fabric_captures[0].valid, True)

    def test_self_report_only_capture_stays_a0(self) -> None:
        evidence = EvidenceContext(
            run_id="assurance-test-run",
            files=_base_evidence_files(build_capture_manifest(_fixture())),
            raw={"metadata": {"run_id": "assurance-test-run"}},
        )

        report = run_verification(_plan(), evidence)

        self.assertEqual(report.verdict, "verified")
        self.assertEqual(report.decision, "pass")
        self.assertEqual(report.assurance, "A0-claims-only")

    def test_invalid_capture_manifest_refutes_report_without_hiding_errors(self) -> None:
        manifest = _a1_manifest()
        manifest["observer_capture"]["test_output"]["summary"] = "tampered"
        evidence = EvidenceContext(
            run_id="assurance-test-run",
            files=_base_evidence_files(manifest),
            raw={"metadata": {"run_id": "assurance-test-run"}},
        )

        report = run_verification(_plan(), evidence)

        self.assertEqual(report.verdict, "refuted")
        self.assertEqual(report.decision, "fail")
        self.assertEqual(report.agent_fabric_captures[0].valid, False)
        self.assertTrue(report.agent_fabric_captures[0].errors)


if __name__ == "__main__":
    unittest.main()
