"""Tests for the V109 Agent Fabric capture bridge."""

from __future__ import annotations

import unittest

from depone.agent_fabric.capture_bridge import (
    build_capture_manifest,
    validate_capture_manifest,
)
from depone.agent_fabric.reference_adapter import build_reference_adapter_fixture
from depone.cli.validate_contracts import _validate_contract_dispatch


def _invocation() -> dict:
    return {
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


def _self_report() -> dict:
    return {
        "result_version": "1.0",
        "agent_role": "runner",
        "profile": "self-test-profile",
        "status": "success",
        "output_files": ["out/agent/result.txt"],
        "self_reported_claims": ["checks completed"],
        "command_receipts": [],
    }


def _fixture() -> dict:
    return build_reference_adapter_fixture(_invocation(), self_report=_self_report())


def _observer_capture(**overrides: object) -> dict:
    capture = {
        "observed_by": "depone-observer",
        "source_fixture_hash": "",
        "diff_summary": {"changed_files": ["depone/example.py"]},
        "touched_files": ["depone/example.py"],
        "test_output": {"status": "passed", "summary": "1 passed"},
        "command_receipts": [
            {
                "command": ["python3", "tests/test_example.py"],
                "exit_code": 0,
                "log_path": "logs/test-example.txt",
            }
        ],
    }
    capture.update(overrides)
    return capture


class CaptureBridgeTests(unittest.TestCase):
    def test_observer_capture_reaches_a1_local_observed(self) -> None:
        manifest = build_capture_manifest(
            _fixture(),
            observer_capture=_observer_capture(),
            allowed_touched_files=["depone/example.py"],
        )

        self.assertEqual(manifest["kind"], "agent-fabric-capture-manifest")
        self.assertEqual(manifest["assurance"], "A1-local-observed")
        self.assertEqual(validate_capture_manifest(manifest), [])
        self.assertEqual(_validate_contract_dispatch(manifest), [])

    def test_self_report_without_observer_remains_a0_claims_only(self) -> None:
        manifest = build_capture_manifest(_fixture())

        self.assertEqual(manifest["assurance"], "A0-claims-only")
        self.assertEqual(manifest["decision"], "claims-only")
        self.assertEqual(validate_capture_manifest(manifest), [])


    def test_rejects_new_assurance_level(self) -> None:
        manifest = build_capture_manifest(_fixture())
        manifest["assurance"] = "A2-live-observed"
        manifest["decision"] = "trusted-live-capture"

        errors = validate_capture_manifest(manifest)

        self.assertTrue(
            any(
                "assurance must be 'A0-claims-only' or 'A1-local-observed'" in e
                for e in errors
            ),
            errors,
        )

    def test_rejects_live_source_fixture_even_with_observer_capture(self) -> None:
        fixture = _fixture()
        fixture["adapter"]["executes_commands"] = True
        manifest = build_capture_manifest(
            fixture,
            observer_capture=_observer_capture(),
            allowed_touched_files=["depone/example.py"],
        )

        errors = validate_capture_manifest(manifest)

        self.assertTrue(
            any("adapter.executes_commands must be false" in e for e in errors),
            errors,
        )

    def test_tampered_observer_capture_fails_closed(self) -> None:
        manifest = build_capture_manifest(
            _fixture(),
            observer_capture=_observer_capture(),
            allowed_touched_files=["depone/example.py"],
        )
        manifest["observer_capture"]["test_output"]["summary"] = "tampered"

        errors = validate_capture_manifest(manifest)

        self.assertTrue(any("observer_capture_hash mismatch" in e for e in errors), errors)

    def test_stale_observer_capture_fails_closed(self) -> None:
        manifest = build_capture_manifest(
            _fixture(),
            observer_capture=_observer_capture(source_fixture_hash="stale"),
            allowed_touched_files=["depone/example.py"],
        )

        errors = validate_capture_manifest(manifest)

        self.assertTrue(any("source_fixture_hash is stale" in e for e in errors), errors)

    def test_extra_touched_file_fails_closed(self) -> None:
        manifest = build_capture_manifest(
            _fixture(),
            observer_capture=_observer_capture(
                touched_files=["depone/example.py", "README.md"],
                diff_summary={"changed_files": ["depone/example.py", "README.md"]},
            ),
            allowed_touched_files=["depone/example.py"],
        )

        errors = validate_capture_manifest(manifest)

        self.assertTrue(any("unexpected touched files" in e for e in errors), errors)


if __name__ == "__main__":
    unittest.main()
