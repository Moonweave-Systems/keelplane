"""Coverage for Agent Fabric dogfood evidence report generation."""

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


class AgentFabricDogfoodEvidenceTests(unittest.TestCase):
    def test_observed_capture_produces_source_only_dogfood_evidence(self) -> None:
        from depone.agent_fabric.dogfood_evidence import build_dogfood_evidence_report

        capture = observed_capture_manifest()

        report = build_dogfood_evidence_report(capture)

        self.assertEqual(report["kind"], "agent-fabric-dogfood-evidence")
        self.assertEqual(report["decision"], "dogfood-evidence-ready-source-only")
        self.assertEqual(report["evidence_type"], "paired-dogfood")
        self.assertEqual(report["capture_assurance"], "A1-local-observed")
        self.assertEqual(report["capture_decision"], "observed-local-capture")
        self.assertEqual(report["test_status"], "passed")
        self.assertEqual(report["blockers"], [])
        self.assertEqual(
            report["source_hashes"]["capture_manifest"],
            canonical_hash(capture),
        )
        self.assertFalse(report["boundary"]["executes_commands"])
        self.assertFalse(report["boundary"]["calls_live_models"])
        self.assertFalse(report["boundary"]["approves_public_claim"])
        self.assertFalse(report["boundary"]["trust_upgrade"])

    def test_a0_capture_manifest_blocks_dogfood_evidence(self) -> None:
        from depone.agent_fabric.dogfood_evidence import build_dogfood_evidence_report

        capture = observed_capture_manifest()
        capture["assurance"] = "A0-claims-only"
        capture["decision"] = "claims-only"
        capture["observer_capture"] = None
        capture["observer_capture_hash"] = None

        report = build_dogfood_evidence_report(capture)

        self.assertEqual(report["decision"], "blocked-capture-not-observed")
        self.assertEqual(report["blockers"][0]["code"], "ERR_CAPTURE_NOT_A1_OBSERVED")

    def test_failed_capture_tests_block_dogfood_evidence(self) -> None:
        from depone.agent_fabric.dogfood_evidence import build_dogfood_evidence_report

        capture = observed_capture_manifest()
        capture["observer_capture"]["test_output"]["status"] = "failed"
        # Keep this as a coherent observed payload for the dogfood decision test.
        from depone.agent_fabric.capture_bridge import _sha256_json

        capture["observer_capture_hash"] = _sha256_json(capture["observer_capture"])

        report = build_dogfood_evidence_report(capture)

        self.assertEqual(report["decision"], "blocked-dogfood-tests-not-passed")
        self.assertEqual(report["blockers"][0]["code"], "ERR_DOGFOOD_TESTS_NOT_PASSED")

    def test_invalid_capture_manifest_blocks_dogfood_evidence(self) -> None:
        from depone.agent_fabric.dogfood_evidence import build_dogfood_evidence_report

        capture = observed_capture_manifest()
        capture["observer_capture_hash"] = "tampered"

        report = build_dogfood_evidence_report(capture)

        self.assertEqual(report["decision"], "blocked-invalid-capture-manifest")
        self.assertEqual(report["blockers"][0]["code"], "ERR_CAPTURE_MANIFEST_INVALID")


    def test_corpus_summarizes_multiple_source_only_capture_manifests(self) -> None:
        from depone.agent_fabric.capture_bridge import _sha256_json
        from depone.agent_fabric.dogfood_evidence import (
            build_dogfood_evidence_corpus_report,
        )

        shell_capture = observed_capture_manifest()
        codex_capture = json.loads(json.dumps(shell_capture))
        codex_capture["fixture"]["adapter"]["harness"] = "codex"
        codex_capture["fixture"]["adapter"]["name"] = "codex-reference-fixture"
        codex_capture["fixture"]["invocation"]["target_harness"] = "codex"
        codex_capture["fixture"]["invocation"]["profile"] = "codex-source-only"
        codex_capture["fixture"]["capture"]["self_report"]["profile"] = "codex-source-only"
        codex_capture["source_fixture_hash"] = _sha256_json(codex_capture["fixture"])
        codex_capture["observer_capture"]["source_fixture_hash"] = codex_capture[
            "source_fixture_hash"
        ]
        codex_capture["observer_capture_hash"] = _sha256_json(
            codex_capture["observer_capture"]
        )

        corpus = build_dogfood_evidence_corpus_report(
            [
                ("shell", shell_capture),
                ("codex", codex_capture),
            ]
        )

        self.assertEqual(corpus["kind"], "agent-fabric-dogfood-evidence-corpus")
        self.assertEqual(corpus["decision"], "dogfood-corpus-ready-source-only")
        self.assertEqual(corpus["summary"]["total_manifests"], 2)
        self.assertEqual(corpus["summary"]["ready_manifests"], 2)
        self.assertEqual(corpus["summary"]["blocked_manifests"], 0)
        self.assertEqual([entry["id"] for entry in corpus["entries"]], ["shell", "codex"])
        self.assertEqual(
            [entry["decision"] for entry in corpus["entries"]],
            ["dogfood-evidence-ready-source-only", "dogfood-evidence-ready-source-only"],
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
            capture_path.write_text(json.dumps(observed_capture_manifest()))

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
            self.assertIn("Dogfood evidence report written", result.stdout)


if __name__ == "__main__":
    unittest.main()
