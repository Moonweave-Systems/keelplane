"""V107 compile report schema and validation.

Every adapter compilation emits a report recording whether toolbelt mappings
are exact, approximated, or have unsupported critical controls.
"""

from __future__ import annotations

from typing import Any

COMPILE_REPORT_SCHEMA_VERSION = "1.0"

VALID_DECISIONS = frozenset(
    {
        "compile-exact",
        "compile-with-approximations",
        "blocked-unsupported-critical",
    }
)

VALID_TOOLBELT_STATUSES = frozenset(
    {
        "exact",
        "approximated",
        "unsupported-critical",
    }
)

REQUIRED_REPORT_FIELDS = [
    "schema_version",
    "target",
    "profile",
    "roles",
    "decision",
]


def validate_compile_report(report: dict[str, Any]) -> list[str]:
    """Validate a compile report. Returns list of error strings."""
    errors: list[str] = []

    for field in REQUIRED_REPORT_FIELDS:
        if field not in report:
            errors.append(f"compile_report missing required field: {field}")

    if (
        "schema_version" in report
        and report["schema_version"] != COMPILE_REPORT_SCHEMA_VERSION
    ):
        errors.append(
            f"compile_report.schema_version expected {COMPILE_REPORT_SCHEMA_VERSION!r}, "
            f"got {report['schema_version']!r}"
        )

    if "target" in report and not isinstance(report["target"], str):
        errors.append("compile_report.target must be a string")

    if "profile" in report and not isinstance(report["profile"], str):
        errors.append("compile_report.profile must be a string")

    if "decision" in report:
        decision = report["decision"]
        if decision not in VALID_DECISIONS:
            errors.append(
                f"compile_report.decision={decision!r} not in {sorted(VALID_DECISIONS)}"
            )

    if "roles" in report:
        if not isinstance(report["roles"], list):
            errors.append("compile_report.roles must be a list")
        else:
            for i, role_entry in enumerate(report["roles"]):
                label = f"compile_report.roles[{i}]"
                if not isinstance(role_entry, dict):
                    errors.append(f"{label} must be an object")
                    continue

                if "role" not in role_entry:
                    errors.append(f"{label} missing required field: role")
                elif not isinstance(role_entry["role"], str):
                    errors.append(f"{label}.role must be a string")

                if "toolbelt_status" in role_entry:
                    status = role_entry["toolbelt_status"]
                    if status not in VALID_TOOLBELT_STATUSES:
                        errors.append(
                            f"{label}.toolbelt_status={status!r} not in "
                            f"{sorted(VALID_TOOLBELT_STATUSES)}"
                        )

                for list_field in ("unsupported_critical", "approximations"):
                    if list_field in role_entry and not isinstance(
                        role_entry[list_field], list
                    ):
                        errors.append(f"{label}.{list_field} must be a list")

    # Decision consistency check
    if "decision" in report and "roles" in report:
        decision = report["decision"]
        roles = report["roles"]
        if isinstance(roles, list):
            block_statuses = {
                r.get("toolbelt_status") for r in roles if isinstance(r, dict)
            }
            if decision == "compile-exact" and "unsupported-critical" in block_statuses:
                errors.append(
                    "decision is compile-exact but some roles have unsupported-critical status"
                )
            if decision != "blocked-unsupported-critical" and block_statuses == {
                "unsupported-critical"
            }:
                errors.append(
                    "all roles are unsupported-critical but decision is not blocked-unsupported-critical"
                )

    return errors


def validate_compile_report_set(reports: list[dict[str, Any]]) -> list[str]:
    """Validate a list of compile reports."""
    errors: list[str] = []
    for i, r in enumerate(reports):
        label = f"compile_reports[{i}]"
        if not isinstance(r, dict):
            errors.append(f"{label} must be an object")
            continue
        errs = validate_compile_report(r)
        for e in errs:
            errors.append(f"{label}: {e}")
    return errors
