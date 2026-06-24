"""V107 profile contract schema and validation.

A profile defines the orchestration structure: which roles participate, in what
order, under what activation conditions, and with what resource limits.
"""

from __future__ import annotations

from typing import Any

PROFILE_SCHEMA_VERSION = "1.0"

REQUIRED_PROFILE_FIELDS = [
    "schema_version",
    "id",
    "version",
    "description",
    "activation",
    "limits",
    "roles",
    "flow",
    "required_evidence",
]

OPTIONAL_PROFILE_FIELDS = [
    "downgrade",
]


def validate_profile(profile: dict[str, Any]) -> list[str]:
    """Validate a single profile contract. Returns list of error strings."""
    errors: list[str] = []

    for field in REQUIRED_PROFILE_FIELDS:
        if field not in profile:
            errors.append(f"profile missing required field: {field}")

    if (
        "schema_version" in profile
        and profile["schema_version"] != PROFILE_SCHEMA_VERSION
    ):
        errors.append(
            f"profile.schema_version expected {PROFILE_SCHEMA_VERSION!r}, "
            f"got {profile['schema_version']!r}"
        )

    if "id" in profile and not isinstance(profile["id"], str):
        errors.append("profile.id must be a string")

    if "id" in profile and isinstance(profile["id"], str) and not profile["id"]:
        errors.append("profile.id must be non-empty")

    if "version" in profile and not isinstance(profile["version"], str):
        errors.append("profile.version must be a string")

    if "description" in profile and not isinstance(profile["description"], str):
        errors.append("profile.description must be a string")

    if (
        "description" in profile
        and isinstance(profile["description"], str)
        and not profile["description"]
    ):
        errors.append("profile.description must be non-empty")

    if "activation" in profile:
        activation = profile["activation"]
        if not isinstance(activation, dict):
            errors.append("profile.activation must be an object")
        else:
            for key in ("requires", "forbids"):
                if key not in activation:
                    errors.append(f"profile.activation missing field: {key}")
                elif not isinstance(activation[key], list):
                    errors.append(f"profile.activation.{key} must be a list")

    if "limits" in profile:
        limits = profile["limits"]
        if not isinstance(limits, dict):
            errors.append("profile.limits must be an object")
        else:
            if "max_threads" in limits:
                if (
                    not isinstance(limits["max_threads"], int)
                    or limits["max_threads"] <= 0
                ):
                    errors.append("profile.limits.max_threads must be a positive int")
            if "max_writers" in limits:
                if (
                    not isinstance(limits["max_writers"], int)
                    or limits["max_writers"] < 0
                ):
                    errors.append(
                        "profile.limits.max_writers must be a non-negative int"
                    )
            if "max_retries_per_role" in limits:
                mt = limits["max_retries_per_role"]
                if not isinstance(mt, int) or mt < 0:
                    errors.append(
                        "profile.limits.max_retries_per_role must be a non-negative int"
                    )

    if "roles" in profile:
        roles = profile["roles"]
        if not isinstance(roles, list):
            errors.append("profile.roles must be a list")
        elif not roles:
            errors.append("profile.roles must be non-empty")
        else:
            for i, entry in enumerate(roles):
                label = f"profile.roles[{i}]"
                if not isinstance(entry, dict):
                    errors.append(f"{label} must be an object")
                    continue
                if "role" not in entry:
                    errors.append(f"{label} missing required field: role")
                elif not isinstance(entry["role"], str):
                    errors.append(f"{label}.role must be a string")

                if "required" in entry and not isinstance(entry["required"], bool):
                    errors.append(f"{label}.required must be a boolean")

                if "parallel_group" in entry and entry["parallel_group"] is not None:
                    if not isinstance(entry["parallel_group"], str):
                        errors.append(
                            f"{label}.parallel_group must be a string or null"
                        )

                if "trigger" in entry and entry["trigger"] is not None:
                    if not isinstance(entry["trigger"], str):
                        errors.append(f"{label}.trigger must be a string or null")

    if "flow" in profile:
        flow = profile["flow"]
        if not isinstance(flow, list):
            errors.append("profile.flow must be a list")
        elif not flow:
            errors.append("profile.flow must be non-empty")
        else:
            for i, step in enumerate(flow):
                if not isinstance(step, str):
                    errors.append(f"profile.flow[{i}] must be a string")

    if "required_evidence" in profile:
        if not isinstance(profile["required_evidence"], list):
            errors.append("profile.required_evidence must be a list")

    if "downgrade" in profile:
        downgrade = profile["downgrade"]
        if not isinstance(downgrade, dict):
            errors.append("profile.downgrade must be an object")
        else:
            if "target" not in downgrade:
                errors.append("profile.downgrade missing field: target")
            elif not isinstance(downgrade["target"], str):
                errors.append("profile.downgrade.target must be a string")
            if "conditions" not in downgrade:
                errors.append("profile.downgrade missing field: conditions")
            elif not isinstance(downgrade["conditions"], list):
                errors.append("profile.downgrade.conditions must be a list")

    return errors


def validate_profile_set(profiles: list[dict[str, Any]]) -> list[str]:
    """Validate a list of profile contracts. Returns list of error strings."""
    errors: list[str] = []

    if not profiles:
        errors.append("profile set is empty")
        return errors

    seen_ids: set[str] = set()
    for i, prof in enumerate(profiles):
        label = f"profiles[{i}]"
        if not isinstance(prof, dict):
            errors.append(f"{label} must be an object")
            continue

        errs = validate_profile(prof)
        for e in errs:
            errors.append(f"{label}: {e}")

        pid = prof.get("id")
        if isinstance(pid, str):
            if pid in seen_ids:
                errors.append(f"{label} duplicate profile id: {pid!r}")
            seen_ids.add(pid)

    return errors
