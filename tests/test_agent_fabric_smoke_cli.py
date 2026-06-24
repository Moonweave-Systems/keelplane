"""CLI coverage for the Agent Fabric lifecycle smoke export."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


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
        "id": "v116-cli-smoke-profile",
        "version": "1.0.0",
        "description": "V116 CLI smoke profile",
        "activation": {"requires": [], "forbids": []},
        "limits": {"max_threads": 1, "max_writers": 0, "max_retries_per_role": 0},
        "roles": [{"role": role_id, "required": True}],
        "flow": [role_id],
        "required_evidence": ["command_receipt"],
    }


def _plan() -> dict:
    return {
        "schema_version": "0.5",
        "plan_id": "agent-fabric-cli-smoke",
        "created_by": "depone",
        "source_prompt": "prove CLI smoke path",
        "activation": {"decision": "activate", "matched_thresholds": []},
        "phases": [{"id": "phase-1", "title": "Phase 1"}],
        "handoffs": [],
        "risk_gates": [],
        "verification": [],
        "budget": {},
    }


class AgentFabricSmokeCliTests(unittest.TestCase):
    def test_cli_writes_smoke_summary_and_operator_view(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile_path = root / "profile.json"
            role_path = root / "role.json"
            plan_path = root / "plan.json"
            out_path = root / "smoke.json"
            view_path = root / "operator-view.md"
            profile_path.write_text(json.dumps(_profile("runner")))
            role_path.write_text(json.dumps(_role("runner")))
            plan_path.write_text(json.dumps(_plan()))

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "depone",
                    "agent-fabric-smoke",
                    "--profile",
                    str(profile_path),
                    "--roles",
                    str(role_path),
                    "--plan",
                    str(plan_path),
                    "--harness",
                    "shell",
                    "--out",
                    str(out_path),
                    "--operator-view-out",
                    str(view_path),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            summary = json.loads(out_path.read_text())
            self.assertEqual(summary["kind"], "agent-fabric-compile-to-report-smoke")
            self.assertEqual(summary["compile_decision"], "compile-exact")
            self.assertEqual(summary["overall_decision"], "ready-for-operator-review")
            self.assertIn("- Decision: pass", view_path.read_text())
            self.assertIn("Agent Fabric smoke summary written", result.stdout)

    def test_cli_preserves_blocked_compile_for_missing_role_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile_path = root / "profile.json"
            roles_path = root / "roles.json"
            plan_path = root / "plan.json"
            out_path = root / "smoke.json"
            profile_path.write_text(json.dumps(_profile("missing")))
            roles_path.write_text(json.dumps({"roles": []}))
            plan_path.write_text(json.dumps(_plan()))

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "depone",
                    "agent-fabric-smoke",
                    "--profile",
                    str(profile_path),
                    "--roles",
                    str(roles_path),
                    "--plan",
                    str(plan_path),
                    "--out",
                    str(out_path),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            summary = json.loads(out_path.read_text())
            self.assertEqual(summary["compile_decision"], "blocked-unsupported-critical")
            self.assertEqual(summary["overall_decision"], "blocked-compile")
            self.assertIn("Role contract missing", summary["first_invocation_instructions"])


if __name__ == "__main__":
    unittest.main()
