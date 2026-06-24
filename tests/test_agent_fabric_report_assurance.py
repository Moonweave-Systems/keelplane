"""Tests for surfacing Agent Fabric capture assurance in verification reports."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from depone.agent_fabric.capture_bridge import build_capture_manifest
from depone.agent_fabric.reference_adapter import build_reference_adapter_fixture
from depone.verify.adapters.base import EvidenceContext, EvidenceFile
from depone.verify import run as run_verify
from depone.verify.engine import run_verification
from depone.verify.operator_view import render_operator_view


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


    def test_a1_capture_cannot_bypass_missing_evidence_contract(self) -> None:
        files = [
            evidence_file
            for evidence_file in _base_evidence_files(_a1_manifest())
            if evidence_file.path != "evidence-contract.json"
        ]
        evidence = EvidenceContext(
            run_id="assurance-test-run",
            files=files,
            raw={"metadata": {"run_id": "assurance-test-run"}},
        )

        report = run_verification(_plan(), evidence)

        self.assertEqual(report.verdict, "refuted")
        self.assertEqual(report.decision, "fail")
        self.assertEqual(report.assurance, "A1-local-observed")
        self.assertTrue(
            any(
                entry.code == "ERR_EVIDENCE_CONTRACT_MISSING"
                for entry in report.evidence_contract
            ),
            report.evidence_contract,
        )

    def test_a1_capture_cannot_bypass_invalid_evidence_contract(self) -> None:
        files = _base_evidence_files(_a1_manifest())
        files = [
            _file("evidence-contract.json", "{}")
            if evidence_file.path == "evidence-contract.json"
            else evidence_file
            for evidence_file in files
        ]
        evidence = EvidenceContext(
            run_id="assurance-test-run",
            files=files,
            raw={"metadata": {"run_id": "assurance-test-run"}},
        )

        report = run_verification(_plan(), evidence)

        self.assertEqual(report.verdict, "refuted")
        self.assertEqual(report.decision, "fail")
        self.assertEqual(report.assurance, "A1-local-observed")
        self.assertTrue(
            any(
                entry.code == "ERR_EVIDENCE_CONTRACT_INVALID"
                for entry in report.evidence_contract
            ),
            report.evidence_contract,
        )

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

    def test_operator_view_renders_v110_report_fields(self) -> None:
        evidence = EvidenceContext(
            run_id="assurance-test-run",
            files=_base_evidence_files(_a1_manifest()),
            raw={"metadata": {"run_id": "assurance-test-run"}},
        )

        view = render_operator_view(run_verification(_plan(), evidence))

        self.assertIn("- Decision: pass", view)
        self.assertIn("- Assurance: A1-local-observed", view)
        self.assertIn("- Agent Fabric captures: 1", view)
        self.assertIn("`agent-fabric-capture-manifest.json`", view)
        self.assertIn("   - Valid: yes", view)

    def test_operator_view_renders_empty_capture_list(self) -> None:
        evidence = EvidenceContext(
            run_id="assurance-test-run",
            files=_base_evidence_files({}),
            raw={"metadata": {"run_id": "assurance-test-run"}},
        )

        view = render_operator_view(run_verification(_plan(), evidence))

        self.assertIn("- Decision: pass", view)
        self.assertIn("- Assurance: A0-claims-only", view)
        self.assertIn("- Agent Fabric captures: 0", view)
        self.assertIn("- None", view)

    def test_operator_view_renders_invalid_capture_errors(self) -> None:
        manifest = _a1_manifest()
        manifest["observer_capture"]["test_output"]["summary"] = "tampered"
        evidence = EvidenceContext(
            run_id="assurance-test-run",
            files=_base_evidence_files(manifest),
            raw={"metadata": {"run_id": "assurance-test-run"}},
        )

        view = render_operator_view(run_verification(_plan(), evidence))

        self.assertIn("- Decision: fail", view)
        self.assertIn("   - Valid: no", view)
        self.assertIn("   - Errors:", view)
        self.assertIn("observer_capture_hash mismatch", view)

    def test_verify_cli_writes_operator_view_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path = root / "plan.json"
            evidence_dir = root / "evidence"
            report_path = root / "verification-report.json"
            view_path = root / "operator-view.md"
            evidence_dir.mkdir()
            plan_path.write_text(json.dumps(_plan()), encoding="utf-8")
            for evidence_file in _base_evidence_files(_a1_manifest()):
                target = evidence_dir / evidence_file.path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(evidence_file.content, encoding="utf-8")

            run_verify(
                argparse.Namespace(
                    self_test=False,
                    plan=str(plan_path),
                    evidence=str(evidence_dir),
                    adapter="generic",
                    out=str(report_path),
                    operator_view_out=str(view_path),
                )
            )

            self.assertTrue(report_path.is_file())
            view = view_path.read_text(encoding="utf-8")
            self.assertIn("# Verification Operator View", view)
            self.assertIn("- Decision: pass", view)
            self.assertIn("- Assurance: A1-local-observed", view)


if __name__ == "__main__":
    unittest.main()
