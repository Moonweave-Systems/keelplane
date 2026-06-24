"""V107 toolbelt contract schema and validation.

A toolbelt is the concrete set of tools and MCP servers allocated to a role
for a specific task class and harness. It is the output of the toolbelt compiler.
"""

from __future__ import annotations

from typing import Any

TOOLBELT_SCHEMA_VERSION = "1.0"

REQUIRED_TOOLBELT_FIELDS = [
    "allowed_tools",
    "allowed_mcp",
    "forbidden_tools",
    "context_policy",
    "output_schema",
    "evidence_obligations",
]

VALID_CONTEXT_POLICIES = frozenset(
    {
        "local-code-only",
        "external-docs-only",
        "diff-review-only",
        "qa-surface-only",
        "repair-only",
        "integration-only",
    }
)


def validate_toolbelt(toolbelt: dict[str, Any]) -> list[str]:
    """Validate a toolbelt contract. Returns list of error strings."""
    errors: list[str] = []

    for field in REQUIRED_TOOLBELT_FIELDS:
        if field not in toolbelt:
            errors.append(f"toolbelt missing required field: {field}")

    for field in (
        "allowed_tools",
        "allowed_mcp",
        "forbidden_tools",
        "evidence_obligations",
    ):
        if field in toolbelt and not isinstance(toolbelt[field], list):
            errors.append(f"toolbelt.{field} must be a list")

    if "context_policy" in toolbelt:
        policy = toolbelt["context_policy"]
        if policy not in VALID_CONTEXT_POLICIES:
            errors.append(
                f"toolbelt.context_policy={policy!r} not in {sorted(VALID_CONTEXT_POLICIES)}"
            )

    if "output_schema" in toolbelt and not isinstance(toolbelt["output_schema"], str):
        errors.append("toolbelt.output_schema must be a string")

    return errors


def validate_toolbelt_set(toolbelts: list[dict[str, Any]]) -> list[str]:
    """Validate a list of toolbelts."""
    errors: list[str] = []
    for i, tb in enumerate(toolbelts):
        label = f"toolbelts[{i}]"
        if not isinstance(tb, dict):
            errors.append(f"{label} must be an object")
            continue
        errs = validate_toolbelt(tb)
        for e in errs:
            errors.append(f"{label}: {e}")
    return errors
