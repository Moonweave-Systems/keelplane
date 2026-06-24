"""Tests for the V108 Agent Fabric reference adapter fixture."""

from __future__ import annotations

import unittest

from depone.cli.validate_contracts import _validate_contract_dispatch
from depone.agent_fabric.reference_adapter import (
    build_reference_adapter_fixture,
    validate_reference_adapter_fixture,
)


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
        "instructions": "Run the local checks and report outputs.",
        "evidence_obligations": ["command_receipt"],
        "context_policy": "local-code-only",
    }


def _result(**overrides: object) -> dict:
    result = {
        "result_version": "1.0",
        "agent_role": "runner",
        "profile": "self-test-profile",
        "status": "success",
        "output_files": ["out/agent/result.txt"],
        "self_reported_claims": ["checks completed"],
        "command_receipts": [],
    }
    result.update(overrides)
    return result


class ReferenceAdapterFixtureTests(unittest.TestCase):
    def test_builds_non_authoritative_fixture_for_valid_invocation(self) -> None:
        fixture = build_reference_adapter_fixture(
            _invocation(),
            self_report=_result(),
            diff_summary={"changed_files": ["depone/example.py"]},
            touched_files=["depone/example.py"],
            test_output={"status": "not-run", "summary": "fixture-only"},
        )

        self.assertEqual(fixture["kind"], "agent-fabric-reference-adapter-fixture")
        self.assertEqual(fixture["capture"]["trust_level"], "A0-claims-only")
        self.assertFalse(fixture["adapter"]["executes_commands"])
        self.assertEqual(validate_reference_adapter_fixture(fixture), [])


    def test_rejects_new_capture_trust_level(self) -> None:
        fixture = build_reference_adapter_fixture(_invocation(), self_report=_result())
        fixture["capture"]["trust_level"] = "A1-local-observed"

        errors = validate_reference_adapter_fixture(fixture)

        self.assertIn("capture.trust_level must be 'A0-claims-only'", errors)

    def test_rejects_live_execution_claim(self) -> None:
        fixture = build_reference_adapter_fixture(_invocation(), self_report=_result())
        fixture["adapter"]["executes_commands"] = True

        errors = validate_reference_adapter_fixture(fixture)

        self.assertIn(
            "adapter.executes_commands must be false for fixture-only adapters",
            errors,
        )

    def test_rejects_observer_owned_agent_outputs(self) -> None:
        fixture = build_reference_adapter_fixture(
            _invocation(),
            self_report=_result(output_files=["evidence/agent-owned.json"]),
        )

        errors = validate_reference_adapter_fixture(fixture)

        self.assertTrue(
            any("observer-owned evidence path" in error for error in errors),
            errors,
        )

    def test_rejects_invalid_invocation(self) -> None:
        bad_invocation = _invocation()
        del bad_invocation["instructions"]
        fixture = build_reference_adapter_fixture(bad_invocation, self_report=_result())

        errors = validate_reference_adapter_fixture(fixture)

        self.assertTrue(
            any(
                "invocation missing required field: instructions" in error
                for error in errors
            ),
            errors,
        )

    def test_validate_contracts_dispatch_accepts_reference_fixture(self) -> None:
        fixture = build_reference_adapter_fixture(_invocation(), self_report=_result())

        self.assertEqual(_validate_contract_dispatch(fixture), [])


if __name__ == "__main__":
    unittest.main()
