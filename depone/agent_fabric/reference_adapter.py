"""V108 deterministic Agent Fabric reference adapter fixture.

This module models the first adapter boundary without executing commands or
calling live models. It packages an invocation packet with non-authoritative
agent-reported artifacts so downstream evidence code can distinguish claims
from observed verification.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from depone.contract import validate_agent_fabric_contract

REFERENCE_ADAPTER_FIXTURE_VERSION = "1.0"
FIXTURE_KIND = "agent-fabric-reference-adapter-fixture"
FIXTURE_MODE = "fixture-only"
FIXTURE_TRUST_LEVEL = "A0-claims-only"
SUPPORTED_REFERENCE_HARNESS = "shell"
VALID_TEST_OUTPUT_STATUSES = frozenset({"not-run", "passed", "failed", "error"})


def _object(value: dict[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    return deepcopy(value)


def _string_list(value: list[str] | None) -> list[str]:
    if value is None:
        return []
    return [item for item in value if isinstance(item, str)]


def _default_result(invocation: dict[str, Any]) -> dict[str, Any]:
    return {
        "result_version": "1.0",
        "agent_role": str(invocation.get("role", "unknown")),
        "profile": str(invocation.get("profile", "unknown")),
        "status": "partial",
        "output_files": [],
        "self_reported_claims": [],
        "command_receipts": [],
        "errors": ["fixture-only adapter did not execute work"],
    }


def _default_diff_summary() -> dict[str, Any]:
    return {
        "changed_files": [],
        "added_files": [],
        "modified_files": [],
        "deleted_files": [],
        "summary": "fixture-only adapter did not observe a diff",
    }


def _default_test_output() -> dict[str, Any]:
    return {
        "status": "not-run",
        "command": None,
        "summary": "fixture-only adapter did not run tests",
    }


def build_reference_adapter_fixture(
    invocation: dict[str, Any],
    *,
    self_report: dict[str, Any] | None = None,
    diff_summary: dict[str, Any] | None = None,
    touched_files: list[str] | None = None,
    test_output: dict[str, Any] | None = None,
    command_receipts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a deterministic local-shell adapter fixture.

    The returned fixture is intentionally non-executing and non-authoritative.
    It may carry agent self-report material, but its trust label remains
    ``A0-claims-only`` until a separate observer captures real evidence.
    """

    harness = str(invocation.get("target_harness", "unknown"))
    receipts = deepcopy(command_receipts) if command_receipts is not None else []
    report = _object(self_report) or _default_result(invocation)
    if receipts and "command_receipts" not in report:
        report["command_receipts"] = deepcopy(receipts)

    return {
        "schema_version": REFERENCE_ADAPTER_FIXTURE_VERSION,
        "kind": FIXTURE_KIND,
        "adapter": {
            "name": "shell-reference-fixture",
            "harness": harness,
            "mode": FIXTURE_MODE,
            "executes_commands": False,
        },
        "invocation": deepcopy(invocation),
        "capture": {
            "trust_level": FIXTURE_TRUST_LEVEL,
            "self_report": report,
            "diff_summary": _object(diff_summary) or _default_diff_summary(),
            "touched_files": _string_list(touched_files),
            "test_output": _object(test_output) or _default_test_output(),
            "command_receipts": receipts,
        },
    }


def validate_reference_adapter_fixture(fixture: dict[str, Any]) -> list[str]:
    """Validate a V108 reference adapter fixture."""

    errors: list[str] = []
    if not isinstance(fixture, dict):
        return ["fixture must be an object"]

    _check_top_level(fixture, errors)
    adapter = fixture.get("adapter")
    if isinstance(adapter, dict):
        _check_adapter(adapter, errors)
    elif "adapter" in fixture:
        errors.append("adapter must be an object")

    invocation = fixture.get("invocation")
    if isinstance(invocation, dict):
        errors.extend(validate_agent_fabric_contract(invocation=invocation))
    elif "invocation" in fixture:
        errors.append("invocation must be an object")

    capture = fixture.get("capture")
    if isinstance(capture, dict):
        _check_capture(capture, errors)
    elif "capture" in fixture:
        errors.append("capture must be an object")

    if isinstance(adapter, dict) and isinstance(invocation, dict):
        if adapter.get("harness") != invocation.get("target_harness"):
            errors.append("adapter.harness must match invocation.target_harness")

    return errors


def _check_top_level(fixture: dict[str, Any], errors: list[str]) -> None:
    for field in ("schema_version", "kind", "adapter", "invocation", "capture"):
        if field not in fixture:
            errors.append(f"fixture missing required field: {field}")

    if fixture.get("schema_version") != REFERENCE_ADAPTER_FIXTURE_VERSION:
        actual = fixture.get("schema_version")
        errors.append(
            "fixture.schema_version expected "
            f"{REFERENCE_ADAPTER_FIXTURE_VERSION!r}, got {actual!r}"
        )
    if fixture.get("kind") != FIXTURE_KIND:
        errors.append(f"fixture.kind expected {FIXTURE_KIND!r}")


def _check_adapter(adapter: dict[str, Any], errors: list[str]) -> None:
    for field in ("name", "harness", "mode", "executes_commands"):
        if field not in adapter:
            errors.append(f"adapter missing required field: {field}")

    if adapter.get("mode") != FIXTURE_MODE:
        errors.append("adapter.mode must be 'fixture-only'")
    if adapter.get("executes_commands") is not False:
        errors.append(
            "adapter.executes_commands must be false for fixture-only adapters"
        )
    if adapter.get("harness") != SUPPORTED_REFERENCE_HARNESS:
        errors.append("adapter.harness must be 'shell' for the V108 reference fixture")

    for text_field in ("name", "harness", "mode"):
        if text_field in adapter and not isinstance(adapter[text_field], str):
            errors.append(f"adapter.{text_field} must be a string")


def _check_capture(capture: dict[str, Any], errors: list[str]) -> None:
    for field in (
        "trust_level",
        "self_report",
        "diff_summary",
        "touched_files",
        "test_output",
        "command_receipts",
    ):
        if field not in capture:
            errors.append(f"capture missing required field: {field}")

    if capture.get("trust_level") != FIXTURE_TRUST_LEVEL:
        errors.append("capture.trust_level must be 'A0-claims-only'")

    self_report = capture.get("self_report")
    if isinstance(self_report, dict):
        errors.extend(validate_agent_fabric_contract(result=self_report))
    elif "self_report" in capture:
        errors.append("capture.self_report must be an object")

    diff_summary = capture.get("diff_summary")
    if isinstance(diff_summary, dict):
        changed_files = diff_summary.get("changed_files", [])
        if not isinstance(changed_files, list) or not all(
            isinstance(item, str) for item in changed_files
        ):
            errors.append("capture.diff_summary.changed_files must be a list of strings")
    elif "diff_summary" in capture:
        errors.append("capture.diff_summary must be an object")

    touched_files = capture.get("touched_files")
    if not isinstance(touched_files, list) or not all(
        isinstance(item, str) for item in touched_files
    ):
        errors.append("capture.touched_files must be a list of strings")

    test_output = capture.get("test_output")
    if isinstance(test_output, dict):
        status = test_output.get("status")
        if status not in VALID_TEST_OUTPUT_STATUSES:
            errors.append(
                f"capture.test_output.status={status!r} not in "
                f"{sorted(VALID_TEST_OUTPUT_STATUSES)}"
            )
    elif "test_output" in capture:
        errors.append("capture.test_output must be an object")

    command_receipts = capture.get("command_receipts")
    if not isinstance(command_receipts, list) or not all(
        isinstance(item, dict) for item in command_receipts
    ):
        errors.append("capture.command_receipts must be a list of objects")


def _self_test() -> None:
    print("depone agent_fabric reference_adapter --self-test")

    invocation = {
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
        "instructions": "Run checks and report outputs.",
        "evidence_obligations": ["command_receipt"],
        "context_policy": "local-code-only",
    }
    result = {
        "result_version": "1.0",
        "agent_role": "runner",
        "profile": "self-test-profile",
        "status": "success",
        "output_files": ["out/agent/result.txt"],
        "self_reported_claims": ["checks completed"],
        "command_receipts": [],
    }

    fixture = build_reference_adapter_fixture(invocation, self_report=result)
    assert not validate_reference_adapter_fixture(fixture)
    print("  [PASS] valid non-authoritative fixture")

    live_claim = deepcopy(fixture)
    live_claim["adapter"]["executes_commands"] = True
    assert "adapter.executes_commands must be false for fixture-only adapters" in validate_reference_adapter_fixture(live_claim)
    print("  [PASS] live execution claim rejected")

    observer_write = build_reference_adapter_fixture(
        invocation,
        self_report=dict(result, output_files=["evidence/agent-owned.json"]),
    )
    assert any(
        "observer-owned evidence path" in error
        for error in validate_reference_adapter_fixture(observer_write)
    )
    print("  [PASS] observer-owned output rejected")

    invalid_invocation = deepcopy(invocation)
    del invalid_invocation["instructions"]
    invalid_fixture = build_reference_adapter_fixture(invalid_invocation, self_report=result)
    assert any(
        "invocation missing required field: instructions" in error
        for error in validate_reference_adapter_fixture(invalid_fixture)
    )
    print("  [PASS] invalid invocation rejected")

    print("\nSelf-test: 4/4 passed")


if __name__ == "__main__":
    _self_test()
