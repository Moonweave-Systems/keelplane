"""Coverage for source-only Agent Fabric adapter smoke reports."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from depone.agent_fabric.harness_snapshot import build_harness_snapshot


FIXTURE_PATH = Path("depone/fixtures/agent_fabric/reference_adapter_shell.json")


class AgentFabricAdapterSmokeTests(unittest.TestCase):
    def test_report_accepts_shell_fixture_when_snapshot_contains_harness(self) -> None:
        from depone.agent_fabric.adapter_smoke import build_adapter_smoke_report

        fixture = json.loads(FIXTURE_PATH.read_text())
        snapshot = build_harness_snapshot(["shell"])

        report = build_adapter_smoke_report(fixture, snapshot)

        self.assertEqual(report["kind"], "agent-fabric-adapter-smoke-report")
        self.assertEqual(report["decision"], "ready-source-only")
        self.assertEqual(report["harness"], "shell")
        self.assertEqual(report["adapter_mode"], "fixture-only")
        self.assertFalse(report["executes_commands"])
        self.assertEqual(report["trust_level"], "A0-claims-only")
        self.assertEqual(report["harness_status"], "exact")
        self.assertEqual(report["blockers"], [])
        self.assertIn("adapter_fixture", report["source_hashes"])
        self.assertIn("harness_snapshot", report["source_hashes"])

    def test_report_blocks_when_snapshot_does_not_include_adapter_harness(self) -> None:
        from depone.agent_fabric.adapter_smoke import build_adapter_smoke_report

        fixture = json.loads(FIXTURE_PATH.read_text())
        snapshot = build_harness_snapshot(["codex"])

        report = build_adapter_smoke_report(fixture, snapshot)

        self.assertEqual(report["decision"], "blocked-harness-not-in-snapshot")
        self.assertEqual(report["harness"], "shell")
        self.assertEqual(
            report["blockers"][0]["code"],
            "ERR_ADAPTER_HARNESS_NOT_SNAPSHOTTED",
        )

    def test_report_blocks_invalid_adapter_fixture_without_hiding_errors(self) -> None:
        from depone.agent_fabric.adapter_smoke import build_adapter_smoke_report

        fixture = json.loads(FIXTURE_PATH.read_text())
        fixture["adapter"]["executes_commands"] = True
        snapshot = build_harness_snapshot(["shell"])

        report = build_adapter_smoke_report(fixture, snapshot)

        self.assertEqual(report["decision"], "blocked-invalid-adapter-fixture")
        self.assertTrue(report["validation_errors"])
        self.assertEqual(report["blockers"][0]["code"], "ERR_ADAPTER_FIXTURE_INVALID")

    def test_cli_writes_adapter_smoke_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot_path = root / "harness-snapshot.json"
            out_path = root / "adapter-smoke.json"
            snapshot_path.write_text(json.dumps(build_harness_snapshot(["shell"])))

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "depone",
                    "agent-fabric-adapter-smoke",
                    "--adapter-fixture",
                    str(FIXTURE_PATH),
                    "--harness-snapshot",
                    str(snapshot_path),
                    "--out",
                    str(out_path),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(out_path.read_text())
            self.assertEqual(report["decision"], "ready-source-only")
            self.assertIn("Adapter smoke report written", result.stdout)


if __name__ == "__main__":
    unittest.main()
