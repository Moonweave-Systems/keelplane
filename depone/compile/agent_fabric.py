"""V107 Agent Fabric compiler.

Compiles a profile, target harness, and role contracts into invocation packets
plus a compile report that records exact, approximated, or blocked toolbelts.
"""

from __future__ import annotations

from typing import Any

from depone.compile.tool_mappings import (
    STATUS_APPROXIMATED,
    STATUS_EXACT,
    STATUS_UNSUPPORTED_CRITICAL,
    resolve_toolbelt,
)
from depone.contract.compile_report import validate_compile_report
from depone.contract.invocation import validate_invocation
from depone.contract.toolbelt import validate_toolbelt


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _role_contract_by_id(
    role_contracts: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    contracts: dict[str, dict[str, Any]] = {}
    for contract in role_contracts:
        role_id = contract.get("id")
        if isinstance(role_id, str):
            contracts[role_id] = contract
    return contracts


def _missing_role_toolbelt() -> dict[str, Any]:
    return {
        "allowed_tools": [],
        "allowed_mcp": [],
        "forbidden_tools": [],
        "context_policy": "local-code-only",
        "output_schema": "unknown",
        "evidence_obligations": ["missing_role_contract"],
        "mappings": [
            {
                "abstract_label": "role-contract",
                "concrete_name": "unknown",
                "status": STATUS_UNSUPPORTED_CRITICAL,
                "notes": "missing role contract",
            }
        ],
        "overall_status": STATUS_UNSUPPORTED_CRITICAL,
    }


def _complete_toolbelt(harness_name: str, role_contract: dict[str, Any]) -> dict[str, Any]:
    role_context = {
        "output_schema": role_contract.get("output_schema", "unknown"),
        "evidence_obligations": _string_list(role_contract.get("evidence_obligations")),
    }
    toolbelt = resolve_toolbelt(
        harness_name,
        _string_list(role_contract.get("allowed_tools")),
        role_context,
    )
    toolbelt["allowed_mcp"] = _string_list(role_contract.get("allowed_mcp_servers"))
    toolbelt["context_policy"] = role_contract.get("context_policy", "local-code-only")
    return toolbelt


def _mapping_values(toolbelt: dict[str, Any], status: str) -> list[str]:
    values: list[str] = []
    mappings = toolbelt.get("mappings", [])
    if not isinstance(mappings, list):
        return values
    for mapping in mappings:
        if not isinstance(mapping, dict) or mapping.get("status") != status:
            continue
        abstract_label = mapping.get("abstract_label")
        notes = mapping.get("notes")
        if isinstance(notes, str) and notes:
            values.append(f"{abstract_label}: {notes}")
        elif isinstance(abstract_label, str):
            values.append(abstract_label)
    return values


def _role_report(role_id: str, toolbelt: dict[str, Any]) -> dict[str, Any]:
    return {
        "role": role_id,
        "toolbelt_status": toolbelt.get("overall_status", STATUS_EXACT),
        "unsupported_critical": _mapping_values(toolbelt, STATUS_UNSUPPORTED_CRITICAL),
        "approximations": _mapping_values(toolbelt, STATUS_APPROXIMATED),
    }


def _decision(role_reports: list[dict[str, Any]]) -> str:
    if any(report["unsupported_critical"] for report in role_reports):
        return "blocked-unsupported-critical"
    if any(report["approximations"] for report in role_reports):
        return "compile-with-approximations"
    return "compile-exact"


def compile_agent_fabric(
    profile: dict[str, Any],
    harness_name: str,
    role_contracts: list[dict[str, Any]],
) -> dict[str, Any]:
    profile_id = profile.get("id", "unknown")
    profile_label = profile_id if isinstance(profile_id, str) else "unknown"
    contracts = _role_contract_by_id(role_contracts)
    invocations: list[dict[str, Any]] = []
    role_reports: list[dict[str, Any]] = []

    for role_entry in profile.get("roles", []):
        if not isinstance(role_entry, dict):
            continue
        role_id = role_entry.get("role", "unknown")
        role_label = role_id if isinstance(role_id, str) else "unknown"
        role_contract = contracts.get(role_label)

        if role_contract is None:
            toolbelt = _missing_role_toolbelt()
            instructions = f"Role contract missing for {role_label}. Do not execute work."
        else:
            toolbelt = _complete_toolbelt(harness_name, role_contract)
            instructions = str(role_contract.get("purpose", f"Execute role {role_label}."))

        invocations.append(
            {
                "packet_version": "1.0",
                "target_harness": harness_name,
                "profile": profile_label,
                "role": role_label,
                "toolbelt": toolbelt,
                "instructions": instructions,
                "evidence_obligations": toolbelt["evidence_obligations"],
                "context_policy": toolbelt["context_policy"],
            }
        )
        role_reports.append(_role_report(role_label, toolbelt))

    compile_report = {
        "schema_version": "1.0",
        "target": harness_name,
        "profile": profile_label,
        "roles": role_reports,
        "decision": _decision(role_reports),
    }
    return {"invocations": invocations, "compile_report": compile_report}


def _role(role_id: str, allowed_tools: list[str]) -> dict[str, Any]:
    return {
        "id": role_id,
        "purpose": f"Run {role_id}",
        "allowed_tools": allowed_tools,
        "forbidden_tools": ["write"],
        "context_policy": "local-code-only",
        "output_schema": f"{role_id}-result-v1",
        "evidence_obligations": ["command_receipt"],
        "trust_boundary": "local",
        "stop_rules": ["stop-on-complete"],
        "allowed_mcp_servers": ["codegraph"],
    }


def _profile(role_ids: list[str]) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "id": "self-test-profile",
        "version": "1.0.0",
        "description": "Self-test profile",
        "activation": {"requires": [], "forbids": []},
        "limits": {"max_threads": 1, "max_writers": 0, "max_retries_per_role": 0},
        "roles": [{"role": role_id, "required": True} for role_id in role_ids],
        "flow": role_ids,
        "required_evidence": ["command_receipt"],
    }


def _assert_valid_bundle(bundle: dict[str, Any]) -> None:
    for invocation in bundle["invocations"]:
        invocation_errors = validate_invocation(invocation)
        assert not invocation_errors, invocation_errors
        toolbelt_errors = validate_toolbelt(invocation["toolbelt"])
        assert not toolbelt_errors, toolbelt_errors
    report_errors = validate_compile_report(bundle["compile_report"])
    assert not report_errors, report_errors


def _self_test() -> None:
    print("depone compile (agent_fabric) --self-test")

    exact = compile_agent_fabric(
        _profile(["runner"]),
        "shell",
        [_role("runner", ["read", "test"])],
    )
    _assert_valid_bundle(exact)
    assert exact["compile_report"]["decision"] == "compile-exact"
    print("  [PASS] exact shell compile")

    codex = compile_agent_fabric(
        _profile(["renderer"]),
        "codex",
        [_role("renderer", ["render"])],
    )
    _assert_valid_bundle(codex)
    assert codex["compile_report"]["decision"] == "compile-with-approximations"
    print("  [PASS] approximated codex compile")

    opencode = compile_agent_fabric(
        _profile(["renderer"]),
        "opencode",
        [_role("renderer", ["render"])],
    )
    _assert_valid_bundle(opencode)
    assert opencode["compile_report"]["decision"] == "compile-with-approximations"
    print("  [PASS] approximated opencode compile")

    unknown_harness = compile_agent_fabric(
        _profile(["runner"]),
        "unknown",
        [_role("runner", ["read"])],
    )
    _assert_valid_bundle(unknown_harness)
    assert unknown_harness["compile_report"]["decision"] == "blocked-unsupported-critical"
    print("  [PASS] unknown harness is blocked")

    unknown_tool = compile_agent_fabric(
        _profile(["runner"]),
        "shell",
        [_role("runner", ["teleport"])],
    )
    _assert_valid_bundle(unknown_tool)
    assert unknown_tool["compile_report"]["decision"] == "blocked-unsupported-critical"
    print("  [PASS] unknown abstract tool is blocked")

    missing_role = compile_agent_fabric(_profile(["missing"]), "shell", [])
    _assert_valid_bundle(missing_role)
    assert missing_role["compile_report"]["decision"] == "blocked-unsupported-critical"
    print("  [PASS] missing role contract is blocked with valid packet")

    print("\nSelf-test: 6/6 passed")


if __name__ == "__main__":
    _self_test()
