"""Coverage for Agent Fabric harness capability snapshot export."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from depone.contract.harness import validate_harness_set


class AgentFabricHarnessSnapshotTests(unittest.TestCase):
    def test_snapshot_combines_fixtures_with_mapping_coverage(self) -> None:
        from depone.agent_fabric.harness_snapshot import build_harness_snapshot

        snapshot = build_harness_snapshot(["shell", "codex"])

        self.assertEqual(snapshot["kind"], "agent-fabric-harness-capability-snapshot")
        self.assertEqual(snapshot["decision"], "snapshot-with-approximations")
        self.assertEqual(snapshot["requested_harnesses"], ["shell", "codex"])
        self.assertEqual([h["name"] for h in snapshot["harnesses"]], ["shell", "codex"])
        capabilities = [h["capability"] for h in snapshot["harnesses"]]
        self.assertFalse(validate_harness_set(capabilities))

        shell = snapshot["harnesses"][0]
        codex = snapshot["harnesses"][1]
        self.assertEqual(shell["tool_mapping_status_counts"]["exact"], 10)
        self.assertEqual(shell["tool_mapping_status_counts"]["approximated"], 0)
        self.assertIn("render", codex["approximated_tools"])
        self.assertIn("smoke", codex["approximated_tools"])
        self.assertEqual(codex["status"], "approximated")

    def test_unknown_harness_is_exported_as_blocked_not_silently_dropped(self) -> None:
        from depone.agent_fabric.harness_snapshot import build_harness_snapshot

        snapshot = build_harness_snapshot(["missing-harness"])

        self.assertEqual(snapshot["decision"], "blocked-unsupported-critical")
        self.assertEqual(snapshot["harnesses"], [])
        self.assertEqual(snapshot["unknown_harnesses"], ["missing-harness"])
        self.assertIn("unknown harness", snapshot["unsupported_critical"][0])

    def test_cli_writes_snapshot_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "harness-snapshot.json"
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "depone",
                    "agent-fabric-harness-snapshot",
                    "--harness",
                    "shell",
                    "--harness",
                    "codex",
                    "--out",
                    str(out_path),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            snapshot = json.loads(out_path.read_text())
            self.assertEqual(snapshot["decision"], "snapshot-with-approximations")
            self.assertIn("Harness snapshot written", result.stdout)


if __name__ == "__main__":
    unittest.main()
