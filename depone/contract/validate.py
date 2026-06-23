"""V107 combined contract validator.

Enforces cross-cutting rules:
- Reviewer write tools are blocked
- Undeclared MCP tools are blocked
- Missing evidence obligations are blocked
- Unsupported critical controls mislabeled as safe are blocked
- Agents writing observer-owned evidence paths are blocked
"""

from __future__ import annotations

from typing import Any

from depone.contract.role import validate_role_set
from depone.contract.toolbelt import validate_toolbelt, validate_toolbelt_set
from depone.contract.harness import validate_harness_set
from depone.contract.profile import validate_profile_set
from depone.contract.compile_report import validate_compile_report
from depone.contract.invocation import validate_invocation, validate_result

# Role IDs that are read-only reviewers
READER_ROLES = frozenset(
    {
        "code-reviewer",
        "security-reviewer",
        "adversarial-reviewer",
        "test-verifier",
    }
)

# Observer-owned evidence path prefixes (agents must not write these)
OBSERVER_EVIDENCE_PATHS = frozenset(
    {
        ".depone/",
        "evidence/",
        "verification-report.json",
        "compile-report.json",
    }
)


def validate_agent_fabric_contract(
    roles: list[dict[str, Any]] | None = None,
    toolbelts: list[dict[str, Any]] | None = None,
    harnesses: list[dict[str, Any]] | None = None,
    compile_report: dict[str, Any] | None = None,
    invocation: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
) -> list[str]:
    """Validate a complete V107 contract set across all schema types.

    Returns list of error strings, empty if fully valid.
    """
    errors: list[str] = []

    # Validate each domain
    if roles is not None:
        errors.extend(validate_role_set(roles))
        _check_reviewer_write(roles, errors)

    if toolbelts is not None:
        errors.extend(validate_toolbelt_set(toolbelts))
        for tb in toolbelts:
            if isinstance(tb, dict):
                _check_missing_obligations(tb, errors)
        if roles is not None:
            _check_undeclared_mcp(roles, toolbelts, errors)

    if harnesses is not None:
        errors.extend(validate_harness_set(harnesses))

    if compile_report is not None:
        errors.extend(validate_compile_report(compile_report))
        _check_mislabeled_unsupported(compile_report, errors)

    if invocation is not None:
        errors.extend(validate_invocation(invocation))

    if result is not None:
        errors.extend(validate_result(result))
        _check_observer_owned_outputs(result, errors)

    return errors


def _check_reviewer_write(roles: list[dict[str, Any]], errors: list[str]) -> None:
    """Reviewer roles must not have write tools."""
    for i, role in enumerate(roles):
        if not isinstance(role, dict):
            continue
        rid = role.get("id", f"roles[{i}]")
        if rid not in READER_ROLES:
            continue

        forbidden = role.get("forbidden_tools", [])
        if isinstance(forbidden, list) and "write" not in forbidden:
            errors.append(f"{rid}: reader role must have 'write' in forbidden_tools")

        allowed = role.get("allowed_tools", [])
        if isinstance(allowed, list):
            write_tools = {
                t
                for t in allowed
                if t in ("edit", "write", "apply_patch", "create", "delete")
            }
            if write_tools:
                errors.append(
                    f"{rid}: reader role allows write-capable tools: {sorted(write_tools)}"
                )


def _check_missing_obligations(toolbelt: dict[str, Any], errors: list[str]) -> None:
    """Toolbelt must define evidence obligations."""
    obligations = toolbelt.get("evidence_obligations", [])
    if not isinstance(obligations, list) or not obligations:
        errors.append(
            f"toolbelt for context_policy={toolbelt.get('context_policy')!r} "
            "has no evidence_obligations"
        )


def _check_undeclared_mcp(
    roles: list[dict[str, Any]],
    toolbelts: list[dict[str, Any]],
    errors: list[str],
) -> None:
    """Toolbelts must not allocate MCP servers undeclared by the role contracts."""
    declared: set[str] = set()
    for role in roles:
        if not isinstance(role, dict):
            continue
        allowed = role.get("allowed_mcp_servers", [])
        if isinstance(allowed, list):
            declared.update(item for item in allowed if isinstance(item, str))

    for i, toolbelt in enumerate(toolbelts):
        if not isinstance(toolbelt, dict):
            continue
        allowed_mcp = toolbelt.get("allowed_mcp", [])
        if not isinstance(allowed_mcp, list):
            continue
        undeclared = sorted(
            item
            for item in allowed_mcp
            if isinstance(item, str) and item not in declared
        )
        if undeclared:
            errors.append(
                f"toolbelts[{i}]: undeclared MCP servers allocated: {undeclared}"
            )


def _check_mislabeled_unsupported(report: dict[str, Any], errors: list[str]) -> None:
    """Unsupported critical controls must not be mislabeled as safe."""
    roles = report.get("roles", [])
    if not isinstance(roles, list):
        return

    decision = report.get("decision", "")
    for i, role_entry in enumerate(roles):
        if not isinstance(role_entry, dict):
            continue
        status = role_entry.get("toolbelt_status")
        unsupported = role_entry.get("unsupported_critical", [])

        if status == "exact" and unsupported:
            errors.append(
                f"roles[{i}]({role_entry.get('role', '?')}): "
                "toolbelt_status is 'exact' but unsupported_critical is non-empty"
            )

        if status == "approximated" and decision == "compile-exact":
            errors.append(
                f"roles[{i}]({role_entry.get('role', '?')}): "
                "toolbelt_status 'approximated' but report decision is 'compile-exact'"
            )


def _check_observer_owned_outputs(result: dict[str, Any], errors: list[str]) -> None:
    """Agent self-reports must not claim writes to observer-owned evidence paths."""
    output_files = result.get("output_files", [])
    if not isinstance(output_files, list):
        return

    for path in output_files:
        if not isinstance(path, str):
            continue
        candidates = (path, path.lstrip("./"))
        if any(
            candidate == prefix.rstrip("/") or candidate.startswith(prefix)
            for candidate in candidates
            for prefix in OBSERVER_EVIDENCE_PATHS
        ):
            errors.append(
                f"result.output_files contains observer-owned evidence path: {path}"
            )


def validate_self_test() -> list[tuple[str, bool]]:
    """Run contract self-test vectors. Returns [(name, passed)]."""
    results: list[tuple[str, bool]] = []

    # -- Role validation --
    valid_role = {
        "id": "explorer",
        "purpose": "Map codebase",
        "allowed_tools": ["read", "search", "glob"],
        "forbidden_tools": ["edit", "write"],
        "context_policy": "local-code-only",
        "output_schema": "source-map-v1",
        "evidence_obligations": ["files_inspected"],
        "trust_boundary": "read-only",
        "stop_rules": ["no-edit"],
        "allowed_mcp_servers": ["codegraph"],
    }
    results.append(("valid-role", not validate_role_set([valid_role])))

    reviewer_without_forbidden = dict(
        valid_role, id="code-reviewer", forbidden_tools=[]
    )
    errs = validate_role_set([reviewer_without_forbidden])
    results.append(
        (
            "reviewer-no-write-forbidden",
            any("must have 'write' in forbidden_tools" in e for e in errs),
        )
    )

    # -- Toolbelt validation --
    valid_toolbelt = {
        "allowed_tools": ["read", "search"],
        "allowed_mcp": ["codegraph"],
        "forbidden_tools": ["edit", "write"],
        "context_policy": "local-code-only",
        "output_schema": "source-map-v1",
        "evidence_obligations": ["files_inspected"],
    }
    results.append(("valid-toolbelt", not validate_toolbelt(valid_toolbelt)))

    empty_obligations = dict(valid_toolbelt, evidence_obligations=[])
    errs: list[str] = []
    _check_missing_obligations(empty_obligations, errs)
    results.append(("missing-evidence-obligations", bool(errs)))

    # -- Harness validation --
    valid_harness = {
        "name": "codex",
        "version": "1.0.0",
        "supports_hard_tool_filtering": True,
        "supports_per_subagent_allowlist": False,
        "supports_mcp_filtering": False,
        "supported_features": ["shell", "read", "edit"],
        "unsupported_features": ["per-subagent-allowlist"],
        "approximations": ["write restrictions enforced by instruction, not runtime"],
    }
    results.append(("valid-harness", not validate_harness_set([valid_harness])))

    invalid_bool = dict(valid_harness, supports_hard_tool_filtering="yes")
    errs = validate_harness_set([invalid_bool])
    results.append(("harness-bool-type", any("must be a boolean" in e for e in errs)))

    # -- Compile report --
    exact_report = {
        "schema_version": "1.0",
        "target": "codex",
        "profile": "feature-pipeline",
        "roles": [
            {
                "role": "explorer",
                "toolbelt_status": "exact",
                "unsupported_critical": [],
                "approximations": [],
            }
        ],
        "decision": "compile-exact",
    }
    results.append(("valid-compile-report", not validate_compile_report(exact_report)))

    mismatched_report = dict(exact_report, decision="compile-exact")
    mismatched_report["roles"][0] = dict(
        mismatched_report["roles"][0],
        toolbelt_status="unsupported-critical",
        unsupported_critical=["no-sandbox"],
    )
    errs = validate_compile_report(mismatched_report)
    results.append(("compile-report-mismatch", bool(errs)))

    # -- Invocation --
    valid_invocation = {
        "packet_version": "1.0",
        "target_harness": "codex",
        "profile": "feature-pipeline",
        "role": "explorer",
        "toolbelt": valid_toolbelt,
        "instructions": "Map the codebase surface",
        "input_files": ["task.json"],
        "evidence_obligations": ["files_inspected"],
        "context_policy": "local-code-only",
    }
    results.append(("valid-invocation", not validate_invocation(valid_invocation)))

    # -- Agent result --
    valid_result = {
        "result_version": "1.0",
        "agent_role": "explorer",
        "profile": "feature-pipeline",
        "status": "success",
        "output_files": ["source-map.json"],
        "self_reported_claims": ["inspected all modules"],
        "command_receipts": [],
        "errors": [],
    }
    results.append(("valid-result", not validate_result(valid_result)))

    observer_owned_result = dict(valid_result, output_files=[".depone/ledger.json"])
    errs = validate_agent_fabric_contract(result=observer_owned_result)
    results.append(("observer-owned-output-blocked", any("observer-owned" in e for e in errs)))

    undeclared_mcp_toolbelt = dict(valid_toolbelt, allowed_mcp=["undeclared"])
    errs = validate_agent_fabric_contract(
        roles=[valid_role],
        toolbelts=[undeclared_mcp_toolbelt],
    )
    results.append(("undeclared-mcp-blocked", any("undeclared MCP" in e for e in errs)))

    # -- Combined validation --
    combined = validate_agent_fabric_contract(
        roles=[valid_role, valid_role],  # duplicate id on purpose
        toolbelts=[valid_toolbelt],
        harnesses=[valid_harness],
        compile_report=exact_report,
        invocation=valid_invocation,
        result=valid_result,
    )
    results.append(
        ("duplicate-role-id-rejected", any("duplicate" in e for e in combined))
    )

    # -- Profile validation --
    valid_profile = {
        "schema_version": "1.0",
        "id": "feature-pipeline",
        "version": "1.0.0",
        "description": "Feature pipeline with explorer, implementer, test-verifier, code-reviewer",
        "activation": {
            "requires": ["feature-ticket"],
            "forbids": ["rollback-skip"],
        },
        "limits": {
            "max_threads": 4,
            "max_writers": 2,
            "max_retries_per_role": 1,
        },
        "roles": [
            {
                "role": "explorer",
                "required": True,
                "parallel_group": None,
                "trigger": None,
            },
            {
                "role": "implementer",
                "required": True,
                "parallel_group": "writers",
                "trigger": "explorer:done",
            },
            {
                "role": "test-verifier",
                "required": True,
                "parallel_group": "verifiers",
                "trigger": "implementer:done",
            },
            {"role": "code-reviewer", "required": False, "trigger": "implementer:done"},
        ],
        "flow": ["explore", "implement", "verify", "review"],
        "required_evidence": ["test-output", "review-summary"],
    }
    results.append(("valid-profile", not validate_profile_set([valid_profile])))

    empty_roles = dict(valid_profile, roles=[])
    errs = validate_profile_set([empty_roles])
    results.append(("profile-empty-roles", any("non-empty" in e for e in errs)))

    missing_limits = dict(valid_profile)
    del missing_limits["limits"]
    errs = validate_profile_set([missing_limits])
    results.append(
        ("profile-missing-limits", any("missing required field" in e for e in errs))
    )

    dup_profiles = [valid_profile, dict(valid_profile, id=valid_profile["id"])]
    errs = validate_profile_set(dup_profiles)
    results.append(("duplicate-profile-id", any("duplicate" in e for e in errs)))

    return results
