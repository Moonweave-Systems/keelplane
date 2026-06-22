from __future__ import annotations

from typing import Any


def validate_embedded_contract(plan: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    activation = plan.get("activation", {})
    activated = isinstance(activation, dict) and activation.get("decision") == "activate"

    if activated and not _non_empty_list(plan.get("assumptions")):
        errors.append("activated plans need assumptions")
    if activated and not _non_empty_list(plan.get("patterns")):
        errors.append("activated plans need patterns")
    if activated and not _non_empty_list(plan.get("phases")):
        errors.append("activated plans need phases")
    if activated and not _non_empty_list(plan.get("workers")):
        errors.append("activated plans need workers")
    if activated and not _non_empty_list(plan.get("handoffs")):
        errors.append("activated plans need handoffs")
    if activated and not _non_empty_list(plan.get("verification")):
        errors.append("activated plans need verification")
    if activated and not _non_empty_list(plan.get("risk_gates")):
        errors.append("activated plans need risk gates")

    _validate_parallelism(plan.get("parallelism"), errors)
    _validate_workers(plan.get("workers", []), errors)
    _validate_handoffs(plan.get("handoffs", []), errors)
    _validate_risk_gates(plan.get("risk_gates", []), errors)
    _validate_resume(plan.get("resume"), activated, errors)
    _validate_execution_path(plan.get("execution_path"), errors)
    return errors


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _non_empty_list(value: Any) -> bool:
    return isinstance(value, list) and bool(value)


def _require_keys(value: dict[str, Any], keys: list[str], label: str, errors: list[str]) -> None:
    for key in keys:
        if key not in value:
            errors.append(f"{label} missing required field: {key}")


def _validate_parallelism(parallelism: Any, errors: list[str]) -> None:
    if not isinstance(parallelism, dict):
        errors.append("parallelism must be an object")
        return
    _require_keys(parallelism, ["shape", "concurrency_cap", "fan_in_rule", "barriers"], "parallelism", errors)
    if "concurrency_cap" in parallelism and not (
        isinstance(parallelism["concurrency_cap"], int) and parallelism["concurrency_cap"] >= 1
    ):
        errors.append("parallelism.concurrency_cap must be a positive integer")
    if "fan_in_rule" in parallelism and not _non_empty_string(parallelism["fan_in_rule"]):
        errors.append("parallelism.fan_in_rule is empty")


def _validate_workers(workers: Any, errors: list[str]) -> None:
    for worker in workers:
        if not isinstance(worker, dict):
            errors.append("worker must be an object")
            continue
        _require_keys(worker, ["id", "role", "tool_permissions", "forbidden_actions", "context_budget", "prompt_contract", "ownership"], "worker", errors)
        contract = worker.get("prompt_contract")
        if isinstance(contract, dict):
            _require_keys(contract, ["inputs", "required_output_schema", "stop_conditions"], "prompt_contract", errors)
            if "inputs" in contract and not _non_empty_list(contract["inputs"]):
                errors.append("prompt_contract.inputs is empty")
        elif "prompt_contract" in worker:
            errors.append("prompt_contract must be an object")


def _validate_handoffs(handoffs: Any, errors: list[str]) -> None:
    for handoff in handoffs:
        if not isinstance(handoff, dict):
            errors.append("handoff must be an object")
            continue
        _require_keys(handoff, ["from_phase", "to_phase", "artifact", "artifact_schema"], "handoff", errors)
        schema = handoff.get("artifact_schema")
        if isinstance(schema, dict):
            _require_keys(schema, ["format", "required_fields", "validation_command"], "artifact_schema", errors)
            if "required_fields" in schema and not _non_empty_list(schema["required_fields"]):
                errors.append("artifact required_fields is empty")
            if "validation_command" in schema and not _non_empty_string(schema["validation_command"]):
                errors.append("validation_command is empty")
        elif "artifact_schema" in handoff:
            errors.append("artifact_schema must be an object")


def _validate_risk_gates(gates: Any, errors: list[str]) -> None:
    for gate in gates:
        if not isinstance(gate, dict):
            errors.append("risk gate must be an object")
            continue
        _require_keys(gate, ["trigger", "safe_default", "requires_user_approval"], "risk_gate", errors)
        if "trigger" in gate and not _non_empty_string(gate["trigger"]):
            errors.append("risk gate trigger is empty")
        if "safe_default" in gate and not _non_empty_string(gate["safe_default"]):
            errors.append("risk gate safe_default is empty")
        if gate.get("requires_user_approval") is not True:
            errors.append("risk gates must require user approval")


def _validate_resume(resume: Any, activated: bool, errors: list[str]) -> None:
    if not isinstance(resume, dict):
        errors.append("resume must be an object")
        return
    _require_keys(resume, ["cacheable_outputs", "invalidators", "restart_points"], "resume", errors)
    if activated and not _non_empty_list(resume.get("cacheable_outputs")):
        errors.append("activated plans need cacheable outputs")
    if activated and not _non_empty_list(resume.get("invalidators")):
        errors.append("activated plans need invalidators")
    if activated and not _non_empty_list(resume.get("restart_points")):
        errors.append("activated plans need restart points")


def _validate_execution_path(execution: Any, errors: list[str]) -> None:
    if not isinstance(execution, dict):
        errors.append("execution_path must be an object")
        return
    _require_keys(execution, ["mode", "first_slice", "consumer"], "execution_path", errors)
    first_slice = execution.get("first_slice")
    if not isinstance(first_slice, dict):
        if "first_slice" in execution:
            errors.append("first_slice must be an object")
        return
    _require_keys(first_slice, ["instruction", "inputs", "expected_output", "completion_check", "forbidden_actions"], "first_slice", errors)
    if "instruction" in first_slice and not _non_empty_string(first_slice["instruction"]):
        errors.append("first_slice.instruction is empty")
    if "inputs" in first_slice and not _non_empty_list(first_slice["inputs"]):
        errors.append("first_slice.inputs must be non-empty")
    if "expected_output" in first_slice and not _non_empty_string(first_slice["expected_output"]):
        errors.append("first_slice.expected_output is empty")
    if "completion_check" in first_slice and not _non_empty_string(first_slice["completion_check"]):
        errors.append("first_slice.completion_check is empty")
    if "forbidden_actions" in first_slice and not _non_empty_list(first_slice["forbidden_actions"]):
        errors.append("first_slice.forbidden_actions must be non-empty")
