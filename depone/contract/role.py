"""V107 role contract schema and validation.

Every role defines purpose, tool restrictions, context policy, output schema,
evidence obligations, trust boundary, and stop rules.
"""

from __future__ import annotations

from typing import Any

ROLE_SCHEMA_VERSION = "1.0"

# Role IDs that are read-only — must not have write-capable tools
READER_ROLES = frozenset(
    {
        "code-reviewer",
        "security-reviewer",
        "adversarial-reviewer",
        "test-verifier",
    }
)

WRITE_CAPABLE = frozenset({"edit", "write", "apply_patch", "create", "delete"})

REQUIRED_ROLE_FIELDS = [
    "id",
    "purpose",
    "allowed_tools",
    "forbidden_tools",
    "context_policy",
    "output_schema",
    "evidence_obligations",
    "trust_boundary",
    "stop_rules",
]

OPTIONAL_ROLE_FIELDS = [
    "allowed_mcp_servers",
    "when_to_use",
    "when_not_to_use",
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


def validate_role(role: dict[str, Any]) -> list[str]:
    """Validate a single role contract. Returns list of error strings."""
    errors: list[str] = []

    for field in REQUIRED_ROLE_FIELDS:
        if field not in role:
            errors.append(f"role missing required field: {field}")
            continue

    for field in (
        "allowed_tools",
        "forbidden_tools",
        "evidence_obligations",
        "stop_rules",
    ):
        if field in role and not isinstance(role[field], list):
            errors.append(f"role.{field} must be a list")

    if "allowed_mcp_servers" in role and not isinstance(
        role["allowed_mcp_servers"], list
    ):
        errors.append("role.allowed_mcp_servers must be a list")

    if "context_policy" in role:
        policy = role["context_policy"]
        if policy not in VALID_CONTEXT_POLICIES:
            errors.append(
                f"role.context_policy={policy!r} is not in {sorted(VALID_CONTEXT_POLICIES)}"
            )

    if "output_schema" in role and not isinstance(role["output_schema"], str):
        errors.append("role.output_schema must be a string")

    if "trust_boundary" in role and not isinstance(role["trust_boundary"], str):
        errors.append("role.trust_boundary must be a string")

    return errors


def validate_role_set(roles: list[dict[str, Any]]) -> list[str]:
    """Validate a list of role contracts. Returns list of error strings."""
    errors: list[str] = []
    seen_ids: set[str] = set()

    if not roles:
        errors.append("role set is empty")
        return errors

    for i, role in enumerate(roles):
        label = f"roles[{i}]"
        if not isinstance(role, dict):
            errors.append(f"{label} must be an object")
            continue

        errs = validate_role(role)
        for e in errs:
            errors.append(f"{label}: {e}")

        rid = role.get("id")
        if isinstance(rid, str):
            if rid in seen_ids:
                errors.append(f"{label} duplicate role id: {rid!r}")
            seen_ids.add(rid)

        # Reader roles must forbid write-capable tools
        if isinstance(rid, str) and rid in READER_ROLES:
            forbidden = role.get("forbidden_tools", [])
            if isinstance(forbidden, list) and "write" not in forbidden:
                errors.append(
                    f"{label}({rid}): reader role must have 'write' in forbidden_tools"
                )
            allowed = role.get("allowed_tools", [])
            if isinstance(allowed, list):
                write_tools = WRITE_CAPABLE & set(allowed)
                if write_tools:
                    errors.append(
                        f"{label}({rid}): reader role allows write-capable tools: "
                        f"{sorted(write_tools)}"
                    )

    return errors
