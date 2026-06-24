"""Coverage for Agent Fabric controlled capture corpus reports."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


CAPTURE_MANIFEST_PATHS = [
    Path("depone/fixtures/agent_fabric/capture_manifest_shell.json"),
    Path("depone/fixtures/agent_fabric/capture_manifest_shell_docs.json"),
]


def capture_manifests() -> list[dict]:
    return [json.loads(path.read_text()) for path in CAPTURE_MANIFEST_PATHS]


class AgentFabricControlledCaptureTests(unittest.TestCase):
    def test_multiple_capture_manifests_produce_source_only_corpus_report(self) -> None:
        from depone.agent_fabric.controlled_capture import (
            build_controlled_capture_corpus_report,
        )

        report = build_controlled_capture_corpus_report(capture_manifests())

        self.assertEqual(report["kind"], "agent-fabric-controlled-capture-corpus")
        self.assertEqual(
            report["decision"], "controlled-capture-corpus-ready-source-only"
        )
        self.assertEqual(report["summary"]["manifest_count"], 2)
        self.assertEqual(report["summary"]["dogfood_ready_count"], 2)
        self.assertEqual(report["summary"]["invalid_manifest_count"], 0)
        self.assertEqual(report["blockers"], [])
        self.assertFalse(report["boundary"]["executes_commands"])
        self.assertFalse(report["boundary"]["calls_live_models"])
        self.assertFalse(report["boundary"]["approves_public_claim"])
        self.assertFalse(report["boundary"]["trust_upgrade"])

    def test_single_capture_manifest_blocks_as_too_narrow(self) -> None:
        from depone.agent_fabric.controlled_capture import (
            build_controlled_capture_corpus_report,
        )

        report = build_controlled_capture_corpus_report(capture_manifests()[:1])

        self.assertEqual(report["decision"], "blocked-controlled-capture-too-narrow")
        self.assertEqual(
            report["blockers"][0]["code"], "ERR_CAPTURE_CORPUS_TOO_NARROW"
        )

    def test_duplicate_capture_manifests_block_corpus_report(self) -> None:
        from depone.agent_fabric.controlled_capture import (
            build_controlled_capture_corpus_report,
        )

        capture = capture_manifests()[0]

        report = build_controlled_capture_corpus_report([capture, capture])

        self.assertEqual(report["decision"], "blocked-duplicate-controlled-capture")
        self.assertEqual(
            report["blockers"][0]["code"], "ERR_CAPTURE_CORPUS_DUPLICATE"
        )

    def test_invalid_capture_manifest_blocks_corpus_report(self) -> None:
        from depone.agent_fabric.controlled_capture import (
            build_controlled_capture_corpus_report,
        )

        captures = capture_manifests()
        captures[1]["observer_capture_hash"] = "tampered"

        report = build_controlled_capture_corpus_report(captures)

        self.assertEqual(report["decision"], "blocked-invalid-controlled-capture")
        self.assertEqual(report["blockers"][0]["code"], "ERR_CAPTURE_CORPUS_INVALID")
        self.assertEqual(report["summary"]["invalid_manifest_count"], 1)

    def test_cli_writes_controlled_capture_corpus_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "controlled-capture.json"

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "depone",
                    "agent-fabric-controlled-capture",
                    "--capture-manifest",
                    str(CAPTURE_MANIFEST_PATHS[0]),
                    "--capture-manifest",
                    str(CAPTURE_MANIFEST_PATHS[1]),
                    "--out",
                    str(out_path),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(out_path.read_text())
            self.assertEqual(
                report["decision"], "controlled-capture-corpus-ready-source-only"
            )
            self.assertIn("Controlled capture corpus report written", result.stdout)


if __name__ == "__main__":
    unittest.main()
