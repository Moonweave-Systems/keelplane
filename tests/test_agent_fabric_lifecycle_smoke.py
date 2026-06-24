"""V112 smoke for the Agent Fabric compile-to-report path."""

from __future__ import annotations

import unittest

from depone.agent_fabric.capture_bridge import ASSURANCE_A1
from depone.agent_fabric.lifecycle_smoke import build_compile_to_report_smoke


def _role(role_id: str) -> dict:
    return {
        "id": role_id,
        "purpose": f"Run {role_id}",
        "allowed_tools": ["read", "test"],
        "forbidden_tools": ["write"],
        "context_policy": "local-code-only",
        "output_schema": f"{role_id}-result-v1",
        "evidence_obligations": ["command_receipt"],
        "trust_boundary": "local",
        "stop_rules": ["stop-on-complete"],
        "allowed_mcp_servers": [],
    }


def _profile(role_id: str) -> dict:
    return {
        "schema_version": "1.0",
        "id": "v112-smoke-profile",
        "version": "1.0.0",
        "description": "V112 smoke profile",
        "activation": {"requires": [], "forbids": []},
        "limits": {"max_threads": 1, "max_writers": 0, "max_retries_per_role": 0},
        "roles": [{"role": role_id, "required": True}],
        "flow": [role_id],
        "required_evidence": ["command_receipt"],
    }


def _plan() -> dict:
    return {
        "schema_version": "0.5",
        "plan_id": "agent-fabric-lifecycle-smoke",
        "created_by": "depone",
        "source_prompt": "prove compile-to-report smoke path",
        "activation": {"decision": "activate", "matched_thresholds": []},
        "phases": [{"id": "phase-1", "title": "Phase 1"}],
        "handoffs": [],
        "risk_gates": [],
        "verification": [],
        "budget": {},
    }


def _observer_capture() -> dict:
    return {
        "observed_by": "depone-observer",
        "source_fixture_hash": "",
        "diff_summary": {"changed_files": ["depone/example.py"]},
        "touched_files": ["depone/example.py"],
        "test_output": {"status": "passed", "summary": "1 passed"},
        "command_receipts": [{"command": ["python3", "test.py"], "exit_code": 0}],
    }


class AgentFabricLifecycleSmokeTests(unittest.TestCase):
    def test_exact_compile_flows_to_a1_report_and_operator_view(self) -> None:
        smoke = build_compile_to_report_smoke(
            _profile("runner"),
            "shell",
            [_role("runner")],
            _plan(),
            observer_capture=_observer_capture(),
            allowed_touched_files=["depone/example.py"],
        )

        self.assertEqual(smoke["kind"], "agent-fabric-compile-to-report-smoke")
        self.assertEqual(smoke["compile_decision"], "compile-exact")
        self.assertEqual(smoke["invocation_count"], 1)
        self.assertEqual(smoke["capture_assurance"], ASSURANCE_A1)
        self.assertEqual(smoke["report_decision"], "pass")
        self.assertEqual(smoke["report_assurance"], ASSURANCE_A1)
        self.assertEqual(smoke["overall_decision"], "ready-for-operator-review")
        self.assertIn("- Decision: pass", smoke["operator_view"])
        self.assertIn("- Assurance: A1-local-observed", smoke["operator_view"])

    def test_blocked_compile_cannot_be_marked_ready_by_report_view(self) -> None:
        smoke = build_compile_to_report_smoke(
            _profile("missing"),
            "shell",
            [],
            _plan(),
        )

        self.assertEqual(smoke["compile_decision"], "blocked-unsupported-critical")
        self.assertEqual(smoke["report_decision"], "pass")
        self.assertEqual(smoke["overall_decision"], "blocked-compile")
        self.assertIn("Role contract missing", smoke["first_invocation_instructions"])


if __name__ == "__main__":
    unittest.main()
