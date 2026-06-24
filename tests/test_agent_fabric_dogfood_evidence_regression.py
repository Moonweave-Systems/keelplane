from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from depone.agent_fabric.claim_gate import canonical_hash


CAPTURE_MANIFEST_PATH = Path("depone/fixtures/agent_fabric/capture_manifest_shell.json")


def observed_capture_manifest() -> dict:
    return json.loads(CAPTURE_MANIFEST_PATH.read_text())


class AgentFabricDogfoodEvidenceRegressionTests(unittest.TestCase):
    def test_corpus_blocks_if_any_capture_manifest_is_not_ready(self) -> None:
        from depone.agent_fabric.capture_bridge import _sha256_json
        from depone.agent_fabric.dogfood_evidence import (
            build_controlled_capture_corpus_report,
        )

        ready_capture = observed_capture_manifest()
        blocked_capture = json.loads(json.dumps(ready_capture))
        blocked_capture["observer_capture"]["test_output"]["status"] = "failed"
        blocked_capture["observer_capture_hash"] = _sha256_json(
            blocked_capture["observer_capture"]
        )

        corpus = build_controlled_capture_corpus_report(
            [ready_capture, blocked_capture]
        )

        self.assertEqual(corpus["decision"], "blocked-insufficient-capture-corpus")
        self.assertEqual(corpus["capture_count"], 2)
        self.assertEqual(corpus["ready_count"], 1)
        self.assertEqual(corpus["blocked_count"], 1)
        self.assertEqual(corpus["entries"][1]["index"], 1)
        self.assertEqual(
            corpus["entries"][1]["blockers"][0]["code"],
            "ERR_DOGFOOD_TESTS_NOT_PASSED",
        )
        self.assertFalse(corpus["boundary"]["executes_commands"])
        self.assertFalse(corpus["boundary"]["calls_live_models"])
        self.assertFalse(corpus["boundary"]["approves_public_claim"])
        self.assertFalse(corpus["boundary"]["trust_upgrade"])

    def test_cli_writes_dogfood_evidence_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            capture_path = root / "capture-manifest.json"
            out_path = root / "dogfood-evidence.json"
            capture = observed_capture_manifest()
            capture_path.write_text(json.dumps(capture))

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "depone",
                    "agent-fabric-dogfood-evidence",
                    "--capture-manifest",
                    str(capture_path),
                    "--out",
                    str(out_path),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(out_path.read_text())
            self.assertEqual(report["decision"], "dogfood-evidence-ready-source-only")
            self.assertEqual(report["source_hashes"]["capture_manifest"], canonical_hash(capture))
            self.assertIn("Dogfood evidence report written", result.stdout)

    def test_cli_repeated_capture_manifest_writes_blocked_corpus_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_path = root / "capture-manifest-a.json"
            second_path = root / "capture-manifest-b.json"
            out_path = root / "dogfood-corpus.json"
            first_path.write_text(json.dumps(observed_capture_manifest()))
            second_path.write_text(json.dumps(observed_capture_manifest()))

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "depone",
                    "agent-fabric-dogfood-evidence",
                    "--capture-manifest",
                    str(first_path),
                    "--capture-manifest",
                    str(second_path),
                    "--out",
                    str(out_path),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(out_path.read_text())
            self.assertEqual(report["kind"], "agent-fabric-controlled-capture-corpus")
            self.assertEqual(report["decision"], "blocked-insufficient-capture-corpus")
            self.assertEqual(
                report["blockers"][-1]["code"],
                "ERR_CONTROLLED_CAPTURE_CORPUS_DUPLICATE",
            )
            self.assertIn("Controlled capture corpus written", result.stdout)


if __name__ == "__main__":
    unittest.main()
