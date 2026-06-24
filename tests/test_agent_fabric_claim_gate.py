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
