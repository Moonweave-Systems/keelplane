from __future__ import annotations

from typing import Any


def apply_minimal_contract(plan: dict[str, Any], objective: str) -> None:
    plan["assumptions"] = [
        {
            "claim": "The declared surface contains the material needed for the objective.",
            "verification": "Inspect the repository path before executing the first phase.",
        }
    ]
    plan["workers"] = [
        {
            "id": "worker-1",
            "role": "workflow analyst",
            "tool_permissions": {
                "read": True,
                "write": False,
                "shell": False,
                "network": False,
                "mcp_connectors": [],
                "requires_escalation_for": [],
            },
            "forbidden_actions": ["write", "shell", "network"],
            "context_budget": {
                "max_files": 8,
                "max_tokens": 12000,
                "must_include": ["repository path"],
                "must_exclude": [],
            },
            "prompt_contract": {
                "inputs": [
                    {"name": "original_prompt", "type": "string"},
                    {"name": "repository_path", "type": "string"},
                ],
                "required_output_schema": "markdown report with summary and evidence sections",
                "stop_conditions": ["report artifact is ready for review"],
            },
            "ownership": ["phase-1-report.md"],
        }
    ]
    plan["phases"] = [
        {
            "id": "phase-1",
            "name": "Inspect objective surface",
            "entry_criteria": ["objective and repository path are available"],
            "exit_criteria": ["phase-1-report.md is produced"],
            "depends_on": [],
            "worker_ids": ["worker-1"],
            "outputs": ["phase-1-report.md"],
        },
        {
            "id": "phase-2",
            "name": "Review execution plan",
            "entry_criteria": ["phase-1-report.md is available"],
            "exit_criteria": ["reviewed-plan.md is ready for the downstream consumer"],
            "depends_on": ["phase-1"],
            "worker_ids": ["worker-1"],
            "outputs": ["reviewed-plan.md"],
        },
    ]
    plan["handoffs"] = [
        {
            "from_phase": "phase-1",
            "to_phase": "phase-2",
            "artifact": "phase-1-report.md",
            "artifact_schema": {
                "format": "markdown",
                "required_fields": ["summary", "evidence"],
                "validation_command": "test -s phase-1-report.md",
            },
        }
    ]
    plan["verification"] = [
        {
            "claim_or_output": "phase-1-report.md supports the reviewed plan",
            "falsifier": "report lacks evidence tied to the objective",
            "evidence_required": ["phase-1-report.md"],
        }
    ]
    plan["risk_gates"] = [
        {
            "trigger": "write",
            "safe_default": "stop before write and ask for approval",
            "requires_user_approval": True,
        }
    ]
    plan["resume"] = {
        "cacheable_outputs": ["phase-1-report.md"],
        "invalidators": ["objective changes", "repository path changes"],
        "restart_points": ["phase-2"],
    }
    plan["execution_path"]["first_slice"] = {
        "instruction": f"Inspect the declared surface for: {objective}",
        "inputs": ["original prompt", "repository path"],
        "expected_output": "phase-1-report.md",
        "completion_check": "Confirm phase-1-report.md exists and contains summary and evidence sections.",
        "forbidden_actions": ["write", "shell", "network"],
    }
