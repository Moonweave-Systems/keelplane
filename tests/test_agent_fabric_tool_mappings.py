from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from depone.compile.tool_mappings import (
    HARNESS_CODEX,
    HARNESS_OPENCODE,
    HARNESS_SHELL,
    STATUS_UNSUPPORTED_CRITICAL,
    resolve_toolbelt,
)


def _role(role_id: str) -> dict:
    return {
        "id": role_id,
        "purpose": f"Run {role_id}",
        "allowed_tools": ["read", "search", "inspect", "test"],
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
        "id": "tool-mapping-profile",
        "version": "1.0.0",
        "description": "Tool mapping profile",
        "activation": {"requires": [], "forbids": []},
        "limits": {"max_threads": 1, "max_writers": 0, "max_retries_per_role": 0},
        "roles": [{"role": role_id, "required": True}],
        "flow": [role_id],
        "required_evidence": ["command_receipt"],
    }


def _role_pack() -> list[dict]:
    data = json.loads(Path("packaging/dwm-roles.json").read_text())
    return data["roles"]


class AgentFabricToolMappingTests(unittest.TestCase):
    def test_shell_toolbelt_includes_ls_and_rg_for_codebase_agents(self) -> None:
        toolbelt = resolve_toolbelt(
            HARNESS_SHELL,
            ["read", "search", "inspect"],
            {"output_schema": "report-v1", "evidence_obligations": ["command_receipt"]},
        )

        self.assertEqual(toolbelt["overall_status"], "exact")
        self.assertIn("ls", toolbelt["allowed_tools"])
        self.assertIn("rg", toolbelt["allowed_tools"])

    def test_unknown_abstract_tool_still_blocks_compile(self) -> None:
        toolbelt = resolve_toolbelt(HARNESS_SHELL, ["teleport"])

        self.assertEqual(toolbelt["overall_status"], STATUS_UNSUPPORTED_CRITICAL)

    def test_real_role_pack_explorer_gets_ls_and_rg_on_shell(self) -> None:
        from depone.compile.agent_fabric import compile_agent_fabric

        bundle = compile_agent_fabric(_profile("explorer"), HARNESS_SHELL, _role_pack())

        toolbelt = bundle["invocations"][0]["toolbelt"]
        self.assertEqual(bundle["compile_report"]["decision"], "compile-exact")
        self.assertIn("ls", toolbelt["allowed_tools"])
        self.assertIn("rg", toolbelt["allowed_tools"])

    def test_real_role_pack_planner_gets_rg_without_inspect_tools_on_shell(self) -> None:
        from depone.compile.agent_fabric import compile_agent_fabric

        bundle = compile_agent_fabric(_profile("planner"), HARNESS_SHELL, _role_pack())

        toolbelt = bundle["invocations"][0]["toolbelt"]
        self.assertIn("rg", toolbelt["allowed_tools"])
        self.assertNotIn("ls", toolbelt["allowed_tools"])

    def test_codex_and_opencode_keep_native_search_and_inspect_tools(self) -> None:
        codex = resolve_toolbelt(HARNESS_CODEX, ["read", "search", "inspect"])
        opencode = resolve_toolbelt(HARNESS_OPENCODE, ["read", "search", "inspect"])

        self.assertIn("Grep", codex["allowed_tools"])
        self.assertIn("Glob", codex["allowed_tools"])
        self.assertNotIn("rg", codex["allowed_tools"])
        self.assertIn("Grep", opencode["allowed_tools"])
        self.assertIn("Glob", opencode["allowed_tools"])
        self.assertIn("codegraph", opencode["allowed_tools"])
        self.assertNotIn("rg", opencode["allowed_tools"])

    def test_compile_cli_writes_agent_fabric_bundle_with_shell_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile_path = root / "profile.json"
            role_path = root / "role.json"
            out_path = root / "bundle.json"
            profile_path.write_text(json.dumps(_profile("explorer")))
            role_path.write_text(json.dumps(_role("explorer")))

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "depone",
                    "compile",
                    str(profile_path),
                    "--target",
                    "agent-fabric",
                    "--harness",
                    "shell",
                    "--roles",
                    str(role_path),
                    "--out",
                    str(out_path),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            bundle = json.loads(out_path.read_text())
            toolbelt = bundle["invocations"][0]["toolbelt"]
            self.assertIn("ls", toolbelt["allowed_tools"])
            self.assertIn("rg", toolbelt["allowed_tools"])
            self.assertIn("Agent Fabric bundle written", result.stdout)


if __name__ == "__main__":
    unittest.main()
