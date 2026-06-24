"""depone validate-contracts — validate Agent Fabric contracts.

Validates role contracts, toolbelt contracts, harness capability snapshots,
compile reports, invocation packets, agent result self-reports, and V108
reference adapter fixtures.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from depone.agent_fabric.capture_bridge import (
    build_capture_manifest,
    validate_capture_manifest,
)
from depone.agent_fabric.reference_adapter import (
    build_reference_adapter_fixture,
    validate_reference_adapter_fixture,
)
from depone.contract import (
    validate_role_set,
    validate_toolbelt_set,
    validate_harness_set,
    validate_profile_set,
    validate_compile_report,
    validate_invocation,
    validate_result,
    validate_agent_fabric_contract,
    validate_self_test,
)


def run(args: argparse.Namespace) -> None:
    if args.self_test:
        _self_test()
        return

    if args.all:
        paths = _all_contract_paths()
        if not paths:
            print(
                "No contract files found under contracts/ or depone/fixtures/",
                file=sys.stderr,
            )
            sys.exit(1)
    elif args.file:
        paths = [Path(args.file)]
    else:
        print(
            "Usage: depone validate-contracts --file <contract.json> [--all] [--self-test]",
            file=sys.stderr,
        )
        sys.exit(1)

    total_errors = 0
    for path in paths:
        if not path.exists():
            print(f"Error: file not found: {path}", file=sys.stderr)
            total_errors += 1
            continue

        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError as e:
            print(f"Error: {path}: invalid JSON: {e}", file=sys.stderr)
            total_errors += 1
            continue

        errors = _validate_contract_dispatch(data)
        if errors:
            print(f"{path}: {len(errors)} error(s)")
            for e in errors:
                print(f"  - {e}")
            total_errors += len(errors)
        else:
            print(f"{path}: valid")

    sys.exit(1 if total_errors else 0)


def _all_contract_paths() -> list[Path]:
    """Return repo-shipped Agent Fabric contract files for batch validation."""
    roots = [
        Path("contracts"),
        Path("depone") / "fixtures" / "capabilities",
        Path("depone") / "fixtures" / "agent_fabric",
    ]
    paths: list[Path] = []
    for root in roots:
        if root.is_dir():
            paths.extend(sorted(root.glob("*.json")))
    return paths


def _validate_contract_dispatch(data: dict) -> list[str]:
    """Dispatch validation based on top-level 'kind' field or content shape."""
    kind = data.get("kind", "unknown")

    if kind == "agent-fabric-contract":
        return validate_agent_fabric_contract(
            roles=data.get("roles"),
            toolbelts=data.get("toolbelts"),
            harnesses=data.get("harnesses"),
            compile_report=data.get("compile_report"),
            invocation=data.get("invocation"),
            result=data.get("result"),
        )
    elif kind == "role-set" or (kind == "unknown" and "roles" in data):
        return validate_role_set(data.get("roles", []))
    elif kind == "toolbelt-set" or (kind == "unknown" and "toolbelts" in data):
        return validate_toolbelt_set(data.get("toolbelts", []))
    elif kind == "harness-set" or (kind == "unknown" and "harnesses" in data):
        return validate_harness_set(data.get("harnesses", []))
    elif kind == "harness" or (
        kind == "unknown" and "supports_hard_tool_filtering" in data
    ):
        return validate_harness_set([data])
    elif kind == "profile-set" or (kind == "unknown" and "profiles" in data):
        return validate_profile_set(data.get("profiles", []))
    elif kind == "compile-report":
        return validate_compile_report(data)
    elif kind == "invocation":
        return validate_invocation(data)
    elif kind == "agent-result":
        return validate_result(data)
    elif kind == "agent-fabric-reference-adapter-fixture":
        return validate_reference_adapter_fixture(data)
    elif kind == "agent-fabric-capture-manifest":
        return validate_capture_manifest(data)
    else:
        return [
            f"Unknown contract kind: {kind!r}. "
            "Use kind='role-set', 'toolbelt-set', 'harness-set', "
            "'profile-set', 'compile-report', 'invocation', "
            "'agent-result', 'agent-fabric-reference-adapter-fixture', "
            "'agent-fabric-capture-manifest', or 'agent-fabric-contract'"
        ]


def _self_test() -> None:
    """Run contract schema self-tests."""
    print("depone validate-contracts --self-test")
    results = validate_self_test()
    results.extend(_dispatch_self_test())
    tests = len(results)
    passed = sum(1 for _, ok in results if ok)

    for name, ok in results:
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {name}")

    print(f"\nSelf-test: {passed}/{tests} passed")
    sys.exit(0 if passed == tests else 1)


def _dispatch_self_test() -> list[tuple[str, bool]]:
    """Run CLI dispatch regression vectors."""
    bad_agent_fabric = {
        "kind": "agent-fabric-contract",
        "roles": [
            {
                "id": "code-reviewer",
                "purpose": "Review code",
                "allowed_tools": ["read", "write"],
                "forbidden_tools": [],
                "context_policy": "diff-review-only",
                "output_schema": "review-v1",
                "evidence_obligations": ["findings"],
                "trust_boundary": "read-only",
                "stop_rules": ["no-edit"],
                "allowed_mcp_servers": [],
            }
        ],
        "toolbelts": [
            {
                "allowed_tools": ["read"],
                "allowed_mcp": ["undeclared-mcp"],
                "forbidden_tools": ["write"],
                "context_policy": "diff-review-only",
                "output_schema": "review-v1",
                "evidence_obligations": [],
            }
        ],
        "result": {
            "result_version": "1.0",
            "agent_role": "code-reviewer",
            "profile": "review",
            "status": "success",
            "output_files": [".depone/observer-ledger.json"],
        },
    }
    agent_fabric_errors = _validate_contract_dispatch(bad_agent_fabric)

    profile_errors = _validate_contract_dispatch(
        {
            "kind": "profile-set",
            "profiles": [
                {
                    "schema_version": "1.0",
                    "id": "empty-profile",
                    "version": "1.0.0",
                    "description": "Invalid empty profile",
                    "activation": {"requires": [], "forbids": []},
                    "limits": {
                        "max_threads": 1,
                        "max_writers": 0,
                        "max_retries_per_role": 0,
                    },
                    "roles": [],
                    "flow": [],
                    "required_evidence": [],
                }
            ],
        }
    )
    harness_errors = _validate_contract_dispatch(
        {
            "name": "shell",
            "version": "1.0.0",
            "supports_hard_tool_filtering": True,
            "supports_per_subagent_allowlist": True,
            "supports_mcp_filtering": True,
            "supported_features": ["shell", "read"],
            "unsupported_features": [],
            "approximations": [],
        }
    )
    dispatch_invocation = {
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
    reference_fixture = build_reference_adapter_fixture(dispatch_invocation)
    reference_fixture_errors = _validate_contract_dispatch(reference_fixture)
    capture_manifest_errors = _validate_contract_dispatch(
        build_capture_manifest(
            reference_fixture,
            observer_capture={
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
            },
            allowed_touched_files=["depone/example.py"],
        )
    )

    return [
        (
            "dispatch-agent-fabric-cross-checks",
            any("reader role allows write-capable tools" in e for e in agent_fabric_errors)
            and any("has no evidence_obligations" in e for e in agent_fabric_errors)
            and any("undeclared MCP" in e for e in agent_fabric_errors)
            and any("observer-owned" in e for e in agent_fabric_errors),
        ),
        (
            "dispatch-profile-set",
            any("profile.roles must be non-empty" in e for e in profile_errors)
            and any("profile.flow must be non-empty" in e for e in profile_errors),
        ),
        ("dispatch-single-harness", not harness_errors),
        ("dispatch-reference-adapter-fixture", not reference_fixture_errors),
        ("dispatch-agent-fabric-capture-manifest", not capture_manifest_errors),
    ]
