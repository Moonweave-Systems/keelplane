"""Coverage for Agent Fabric paired evidence report generation."""

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


def ready_dogfood_evidence() -> dict:
    return {
        "kind": "agent-fabric-dogfood-evidence",
        "decision": "dogfood-evidence-ready-source-only",
        "evidence_type": "paired-dogfood",
        "boundary": {
            "executes_commands": False,
            "calls_live_models": False,
            "approves_public_claim": False,
        },
    }


class AgentFabricPairedEvidenceTests(unittest.TestCase):
    def test_ready_inputs_produce_hash_bound_paired_evidence(self) -> None:
        from depone.agent_fabric.paired_evidence import build_paired_evidence_report

        adapter_smoke = ready_adapter_smoke_report()
        dogfood = ready_dogfood_evidence()

        report = build_paired_evidence_report(adapter_smoke, dogfood)

        self.assertEqual(report["kind"], "agent-fabric-paired-evidence-report")
        self.assertEqual(report["decision"], "paired-evidence-ready-source-only")
        self.assertEqual(report["evidence_type"], "paired-dogfood")
        self.assertEqual(report["claim_scope"], "public-benefit")
        self.assertEqual(report["adapter_smoke_decision"], "ready-source-only")
        self.assertEqual(
            report["dogfood_evidence_decision"],
            "dogfood-evidence-ready-source-only",
        )
        self.assertEqual(report["blockers"], [])
        self.assertEqual(
            report["source_hashes"]["adapter_smoke_report"],
            canonical_hash(adapter_smoke),
        )
        self.assertEqual(
            report["source_hashes"]["dogfood_evidence"],
            canonical_hash(dogfood),
        )
        self.assertFalse(report["boundary"]["executes_commands"])
        self.assertFalse(report["boundary"]["calls_live_models"])
        self.assertFalse(report["boundary"]["detects_installed_harness"])
        self.assertFalse(report["boundary"]["inspects_mcp_runtime"])
        self.assertFalse(report["boundary"]["approves_public_claim"])
        self.assertFalse(report["boundary"]["trust_upgrade"])

    def test_blocked_adapter_smoke_blocks_paired_evidence(self) -> None:
        from depone.agent_fabric.paired_evidence import build_paired_evidence_report

        adapter_smoke = ready_adapter_smoke_report()
        adapter_smoke["decision"] = "blocked-harness-not-in-snapshot"

        report = build_paired_evidence_report(adapter_smoke, ready_dogfood_evidence())

        self.assertEqual(report["decision"], "blocked-adapter-smoke-not-ready")
        self.assertEqual(report["blockers"][0]["code"], "ERR_ADAPTER_SMOKE_NOT_READY")

    def test_overclaiming_dogfood_evidence_blocks_paired_evidence(self) -> None:
        from depone.agent_fabric.paired_evidence import build_paired_evidence_report

        dogfood = ready_dogfood_evidence()
        dogfood["boundary"]["approves_public_claim"] = True

        report = build_paired_evidence_report(ready_adapter_smoke_report(), dogfood)

        self.assertEqual(report["decision"], "blocked-dogfood-evidence-not-ready")
        self.assertEqual(
            report["blockers"][0]["code"],
            "ERR_DOGFOOD_EVIDENCE_PUBLIC_CLAIM_APPROVAL",
        )

    def test_not_ready_dogfood_evidence_blocks_paired_evidence(self) -> None:
        from depone.agent_fabric.paired_evidence import build_paired_evidence_report

        dogfood = ready_dogfood_evidence()
        dogfood["decision"] = "dogfood-evidence-missing"

        report = build_paired_evidence_report(ready_adapter_smoke_report(), dogfood)

        self.assertEqual(report["decision"], "blocked-dogfood-evidence-not-ready")
        self.assertEqual(
            report["blockers"][0]["code"],
            "ERR_DOGFOOD_EVIDENCE_NOT_READY",
        )

    def test_cli_writes_paired_evidence_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            smoke_path = root / "adapter-smoke.json"
            dogfood_path = root / "dogfood-evidence.json"
            out_path = root / "paired-evidence.json"
            smoke_path.write_text(json.dumps(ready_adapter_smoke_report()))
            dogfood_path.write_text(json.dumps(ready_dogfood_evidence()))

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "depone",
                    "agent-fabric-paired-evidence",
                    "--adapter-smoke",
                    str(smoke_path),
                    "--dogfood-evidence",
                    str(dogfood_path),
                    "--out",
                    str(out_path),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(out_path.read_text())
            self.assertEqual(report["decision"], "paired-evidence-ready-source-only")
            self.assertIn("Paired evidence report written", result.stdout)


if __name__ == "__main__":
    unittest.main()
