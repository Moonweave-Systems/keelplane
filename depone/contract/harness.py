"""V107 harness capability snapshot schema and validation.

A harness capability snapshot records what a target harness supports for
deterministic tool filtering, MCP allocation, and permission control.
"""

from __future__ import annotations

from typing import Any

HARNESS_SCHEMA_VERSION = "1.0"

REQUIRED_HARNESS_FIELDS = [
    "name",
    "version",
    "supports_hard_tool_filtering",
    "supports_per_subagent_allowlist",
    "supports_mcp_filtering",
    "supported_features",
]

OPTIONAL_HARNESS_FIELDS = [
    "unsupported_features",
    "notes",
    "approximations",
]


def validate_harness(harness: dict[str, Any]) -> list[str]:
    """Validate a harness capability snapshot. Returns list of error strings."""
    errors: list[str] = []

    for field in REQUIRED_HARNESS_FIELDS:
        if field not in harness:
            errors.append(f"harness missing required field: {field}")

    for bool_field in (
        "supports_hard_tool_filtering",
        "supports_per_subagent_allowlist",
        "supports_mcp_filtering",
    ):
        if bool_field in harness and not isinstance(harness[bool_field], bool):
            errors.append(f"harness.{bool_field} must be a boolean")

    for list_field in ("supported_features", "unsupported_features", "approximations"):
        if list_field in harness and not isinstance(harness[list_field], list):
            errors.append(f"harness.{list_field} must be a list")

    if "name" in harness and not isinstance(harness["name"], str):
        errors.append("harness.name must be a string")

    if "version" in harness and not isinstance(harness["version"], str):
        errors.append("harness.version must be a string")

    return errors


def validate_harness_set(harnesses: list[dict[str, Any]]) -> list[str]:
    """Validate a list of harness capability snapshots."""
    errors: list[str] = []
    seen_names: set[str] = set()

    if not harnesses:
        errors.append("harness set is empty")
        return errors

    for i, h in enumerate(harnesses):
        label = f"harnesses[{i}]"
        if not isinstance(h, dict):
            errors.append(f"{label} must be an object")
            continue

        errs = validate_harness(h)
        for e in errs:
            errors.append(f"{label}: {e}")

        name = h.get("name")
        if isinstance(name, str):
            if name in seen_names:
                errors.append(f"{label} duplicate harness name: {name!r}")
            seen_names.add(name)

    return errors
