"""Coverage for Agent Fabric claim gates with paired evidence."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from depone.agent_fabric.adapter_smoke import build_adapter_smoke_report
from depone.agent_fabric.claim_gate import canonical_hash
from depone.agent_fabric.harness_snapshot import build_harness_snapshot


FIXTURE_PATH = Path("depone/fixtures/agent_fabric/reference_adapter_shell.json")


def ready_adapter_smoke_report() -> dict:
    fixture = json.loads(FIXTURE_PATH.read_text())
    return build_adapter_smoke_report(fixture, build_harness_snapshot(["shell"]))


def ready_paired_evidence(adapter_smoke: dict) -> dict:
    return {
        "kind": "agent-fabric-paired-evidence-report",
        "decision": "paired-evidence-ready-source-only",
        "evidence_type": "paired-dogfood",
        "claim_scope": "public-benefit",
        "source_hashes": {
            "adapter_smoke_report": canonical_hash(adapter_smoke),
            "dogfood_evidence": "source-only-dogfood-evidence-hash",
        },
        "boundary": {
            "executes_commands": False,
            "calls_live_models": False,
            "approves_public_claim": False,
        },
    }


class AgentFabricClaimGatePairedEvidenceTests(unittest.TestCase):
    def test_ready_paired_evidence_moves_claim_gate_to_review(self) -> None:
        from depone.agent_fabric.claim_gate import build_claim_gate_report

        smoke = ready_adapter_smoke_report()
        report = build_claim_gate_report(
            smoke,
            paired_evidence=ready_paired_evidence(smoke),
        )

        self.assertEqual(report["decision"], "ready-for-public-claim-review")
        self.assertEqual(
            report["paired_evidence_decision"],
            "paired-evidence-ready-source-only",
        )
        self.assertEqual(report["blockers"], [])
        self.assertTrue(report["requires_human_review"])
        self.assertFalse(report["boundary"]["approves_public_claim"])
        self.assertIn("paired_evidence_report", report["source_hashes"])

    def test_mismatched_paired_evidence_hash_blocks_claim_gate(self) -> None:
        from depone.agent_fabric.claim_gate import build_claim_gate_report

        smoke = ready_adapter_smoke_report()
        evidence = ready_paired_evidence(smoke)
        evidence["source_hashes"]["adapter_smoke_report"] = "wrong-hash"

        report = build_claim_gate_report(smoke, paired_evidence=evidence)

        self.assertEqual(report["decision"], "blocked-paired-evidence-not-ready")
        self.assertEqual(
            report["blockers"][0]["code"],
            "ERR_PAIRED_EVIDENCE_HASH_MISMATCH",
        )

    def test_cli_accepts_paired_evidence_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            smoke = ready_adapter_smoke_report()
            smoke_path = root / "adapter-smoke.json"
            evidence_path = root / "paired-evidence.json"
            out_path = root / "claim-gate.json"
            smoke_path.write_text(json.dumps(smoke))
            evidence_path.write_text(json.dumps(ready_paired_evidence(smoke)))

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "depone",
                    "agent-fabric-claim-gate",
                    "--adapter-smoke",
                    str(smoke_path),
                    "--paired-evidence",
                    str(evidence_path),
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


if __name__ == "__main__":
    unittest.main()
