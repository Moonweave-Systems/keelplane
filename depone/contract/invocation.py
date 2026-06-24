"""V107 agent invocation packet and agent result schemas.

Invocation packet: the complete context sent to a harness to run one agent role.
Agent result: the self-reported output from a harness execution.
"""

from __future__ import annotations

from typing import Any

INVOCATION_SCHEMA_VERSION = "1.0"
RESULT_SCHEMA_VERSION = "1.0"

REQUIRED_INVOCATION_FIELDS = [
    "packet_version",
    "target_harness",
    "profile",
    "role",
    "toolbelt",
    "instructions",
]

OPTIONAL_INVOCATION_FIELDS = [
    "input_files",
    "evidence_obligations",
    "context_policy",
    "working_directory",
    "timeout_seconds",
]

REQUIRED_RESULT_FIELDS = [
    "result_version",
    "agent_role",
    "profile",
    "status",
]


def validate_invocation(packet: dict[str, Any]) -> list[str]:
    """Validate an agent invocation packet. Returns list of error strings."""
    errors: list[str] = []

    for field in REQUIRED_INVOCATION_FIELDS:
        if field not in packet:
            errors.append(f"invocation missing required field: {field}")

    if (
        "packet_version" in packet
        and packet["packet_version"] != INVOCATION_SCHEMA_VERSION
    ):
        errors.append(
            f"invocation.packet_version expected {INVOCATION_SCHEMA_VERSION!r}, "
            f"got {packet['packet_version']!r}"
        )

    if "target_harness" in packet and not isinstance(packet["target_harness"], str):
        errors.append("invocation.target_harness must be a string")

    if "profile" in packet and not isinstance(packet["profile"], str):
        errors.append("invocation.profile must be a string")

    if "role" in packet and not isinstance(packet["role"], str):
        errors.append("invocation.role must be a string")

    if "toolbelt" in packet and not isinstance(packet["toolbelt"], dict):
        errors.append("invocation.toolbelt must be an object")

    if "instructions" in packet and not isinstance(packet["instructions"], str):
        errors.append("invocation.instructions must be a string")

    if "input_files" in packet and not isinstance(packet["input_files"], list):
        errors.append("invocation.input_files must be a list of strings")

    if "evidence_obligations" in packet and not isinstance(
        packet["evidence_obligations"], list
    ):
        errors.append("invocation.evidence_obligations must be a list")

    return errors


def validate_result(result: dict[str, Any]) -> list[str]:
    """Validate an agent result self-report. Returns list of error strings."""
    errors: list[str] = []

    for field in REQUIRED_RESULT_FIELDS:
        if field not in result:
            errors.append(f"result missing required field: {field}")

    if "result_version" in result and result["result_version"] != RESULT_SCHEMA_VERSION:
        errors.append(
            f"result.result_version expected {RESULT_SCHEMA_VERSION!r}, "
            f"got {result['result_version']!r}"
        )

    VALID_STATUSES = {"success", "failure", "partial"}
    if "status" in result and result["status"] not in VALID_STATUSES:
        errors.append(
            f"result.status={result['status']!r} not in {sorted(VALID_STATUSES)}"
        )

    if "agent_role" in result and not isinstance(result["agent_role"], str):
        errors.append("result.agent_role must be a string")

    if "profile" in result and not isinstance(result["profile"], str):
        errors.append("result.profile must be a string")

    if "output_files" in result and not isinstance(result["output_files"], list):
        errors.append("result.output_files must be a list")

    if "self_reported_claims" in result and not isinstance(
        result["self_reported_claims"], list
    ):
        errors.append("result.self_reported_claims must be a list")

    if "command_receipts" in result and not isinstance(
        result["command_receipts"], list
    ):
        errors.append("result.command_receipts must be a list")

    if "errors" in result and not isinstance(result["errors"], list):
        errors.append("result.errors must be a list")

    return errors
