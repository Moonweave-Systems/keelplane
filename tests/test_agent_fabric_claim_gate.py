"""Coverage for Agent Fabric public-claim evidence gates."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from depone.agent_fabric.adapter_smoke import build_adapter_smoke_report
from depone.agent_fabric.harness_snapshot import build_harness_snapshot


FIXTURE_PATH = Path("depone/fixtures/agent_fabric/reference_adapter_shell.json")


def ready_adapter_smoke_report() -> dict:
    fixture = json.loads(FIXTURE_PATH.read_text())
    return build_adapter_smoke_report(fixture, build_harness_snapshot(["shell"]))


class AgentFabricClaimGateTests(unittest.TestCase):
    def test_source_ready_smoke_blocks_public_benefit_claims(self) -> None:
        from depone.agent_fabric.claim_gate import build_claim_gate_report

        report = build_claim_gate_report(ready_adapter_smoke_report())

        self.assertEqual(report["kind"], "agent-fabric-claim-gate-report")
        self.assertEqual(report["decision"], "blocked-missing-paired-evidence")
        self.assertEqual(report["claim_scope"], "public-benefit")
        self.assertEqual(report["adapter_smoke_decision"], "ready-source-only")
        self.assertEqual(report["blockers"][0]["code"], "ERR_PAIRED_EVIDENCE_REQUIRED")
        self.assertFalse(report["boundary"]["executes_commands"])
        self.assertFalse(report["boundary"]["calls_live_models"])
        self.assertFalse(report["boundary"]["approves_public_claim"])

    def test_blocked_adapter_smoke_blocks_claim_gate_with_source_reason(self) -> None:
        from depone.agent_fabric.claim_gate import build_claim_gate_report

        smoke = ready_adapter_smoke_report()
        smoke["decision"] = "blocked-harness-not-in-snapshot"
        smoke["blockers"] = [{"code": "ERR_ADAPTER_HARNESS_NOT_SNAPSHOTTED"}]

        report = build_claim_gate_report(smoke)

        self.assertEqual(report["decision"], "blocked-adapter-smoke-not-ready")
        self.assertEqual(report["blockers"][0]["code"], "ERR_ADAPTER_SMOKE_NOT_READY")
        self.assertEqual(report["adapter_smoke_blockers"], smoke["blockers"])


    def test_ready_controlled_capture_corpus_moves_claim_gate_to_review(self) -> None:
        from depone.agent_fabric.claim_gate import build_claim_gate_report
        from depone.agent_fabric.dogfood_evidence import (
            build_controlled_capture_corpus_report,
        )

        shell_capture = json.loads(
            Path("depone/fixtures/agent_fabric/capture_manifest_shell.json").read_text()
        )
        docs_capture = json.loads(
            Path(
                "depone/fixtures/agent_fabric/capture_manifest_docs_source_only.json"
            ).read_text()
        )
        corpus = build_controlled_capture_corpus_report([shell_capture, docs_capture])

        report = build_claim_gate_report(
            ready_adapter_smoke_report(),
            controlled_capture_corpus=corpus,
        )

        self.assertEqual(report["decision"], "ready-for-public-claim-review")
        self.assertEqual(
            report["controlled_capture_corpus_decision"],
            "controlled-capture-corpus-ready",
        )
        self.assertTrue(report["requires_human_review"])
        self.assertFalse(report["boundary"]["approves_public_claim"])
        self.assertFalse(report["boundary"]["trust_upgrade"])
        self.assertIn("controlled_capture_corpus_report", report["source_hashes"])

    def test_blocked_controlled_capture_corpus_blocks_claim_gate(self) -> None:
        from depone.agent_fabric.claim_gate import build_claim_gate_report
        from depone.agent_fabric.dogfood_evidence import (
            build_controlled_capture_corpus_report,
        )

        capture = json.loads(
            Path("depone/fixtures/agent_fabric/capture_manifest_shell.json").read_text()
        )
        corpus = build_controlled_capture_corpus_report([capture])

        report = build_claim_gate_report(
            ready_adapter_smoke_report(),
            controlled_capture_corpus=corpus,
        )

        self.assertEqual(report["decision"], "blocked-controlled-capture-corpus-not-ready")
        self.assertEqual(
            report["blockers"][0]["code"],
            "ERR_CONTROLLED_CAPTURE_CORPUS_NOT_READY",
        )

    def test_cli_accepts_controlled_capture_corpus_report(self) -> None:
        from depone.agent_fabric.dogfood_evidence import (
            build_controlled_capture_corpus_report,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            smoke_path = root / "adapter-smoke.json"
            corpus_path = root / "controlled-capture-corpus.json"
            out_path = root / "claim-gate.json"
            smoke_path.write_text(json.dumps(ready_adapter_smoke_report()))
            captures = [
                json.loads(
                    Path("depone/fixtures/agent_fabric/capture_manifest_shell.json").read_text()
                ),
                json.loads(
                    Path(
                        "depone/fixtures/agent_fabric/capture_manifest_docs_source_only.json"
                    ).read_text()
                ),
            ]
            corpus_path.write_text(json.dumps(build_controlled_capture_corpus_report(captures)))

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "depone",
                    "agent-fabric-claim-gate",
                    "--adapter-smoke",
                    str(smoke_path),
                    "--controlled-capture-corpus",
                    str(corpus_path),
                    "--out",
                    str(out_path),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(out_path.read_text())
            self.assertEqual(report["decision"], "ready-for-public-claim-review")
            self.assertIn("Claim gate report written", result.stdout)

    def test_cli_writes_claim_gate_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            smoke_path = root / "adapter-smoke.json"
            out_path = root / "claim-gate.json"
            smoke_path.write_text(json.dumps(ready_adapter_smoke_report()))

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "depone",
                    "agent-fabric-claim-gate",
                    "--adapter-smoke",
                    str(smoke_path),
                    "--out",
                    str(out_path),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(out_path.read_text())
            self.assertEqual(report["decision"], "blocked-missing-paired-evidence")
            self.assertIn("Claim gate report written", result.stdout)


if __name__ == "__main__":
    unittest.main()
