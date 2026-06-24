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


def _validate_execution_wave_slice(slice_data: Any, label: str, errors: list[str]) -> None:
    if not isinstance(slice_data, dict):
        errors.append(f"{label} must be an object")
        return
    _require_keys(slice_data, ["id", "instruction", "expected_output", "completion_check", "forbidden_actions"], label, errors)
    if "id" in slice_data and not _non_empty_string(slice_data["id"]):
        errors.append(f"{label}.id is empty")
    if "instruction" in slice_data and not _non_empty_string(slice_data["instruction"]):
        errors.append(f"{label}.instruction is empty")
    if "inputs" in slice_data and not _non_empty_list(slice_data["inputs"]):
        errors.append(f"{label}.inputs must be non-empty")
    if "expected_output" in slice_data and not _non_empty_string(slice_data["expected_output"]):
        errors.append(f"{label}.expected_output is empty")
    if "completion_check" in slice_data and not _non_empty_string(slice_data["completion_check"]):
        errors.append(f"{label}.completion_check is empty")
    if "forbidden_actions" in slice_data and not _non_empty_list(slice_data["forbidden_actions"]):
        errors.append(f"{label}.forbidden_actions must be non-empty")


def _validate_execution_first_wave(first_wave: Any, errors: list[str]) -> str | None:
    if not isinstance(first_wave, dict):
        errors.append("execution_path.first_wave must be an object")
        return None
    _require_keys(first_wave, ["id", "concurrency_cap", "slices", "entry_gate", "exit_gate", "fan_in"], "first_wave", errors)
    if "id" in first_wave and not _non_empty_string(first_wave["id"]):
        errors.append("first_wave.id is empty")
    if "concurrency_cap" in first_wave and not (isinstance(first_wave["concurrency_cap"], int) and first_wave["concurrency_cap"] >= 1):
        errors.append("first_wave.concurrency_cap must be a positive integer")
    if "slices" in first_wave and not _non_empty_list(first_wave["slices"]):
        errors.append("first_wave.slices must be non-empty")
    if "entry_gate" in first_wave and not _non_empty_string(first_wave["entry_gate"]):
        errors.append("first_wave.entry_gate is empty")
    if "exit_gate" in first_wave and not _non_empty_string(first_wave["exit_gate"]):
        errors.append("first_wave.exit_gate is empty")
    if "fan_in" in first_wave and not _non_empty_string(first_wave["fan_in"]):
        errors.append("first_wave.fan_in is empty")
    if isinstance(first_wave.get("slices"), list):
        for index, slice_data in enumerate(first_wave["slices"]):
            _validate_execution_wave_slice(slice_data, f"first_wave.slices[{index}]", errors)
    wave_id = first_wave.get("id")
    return wave_id if _non_empty_string(wave_id) else None


def _validate_execution_waves(waves: Any, errors: list[str], *, first_wave_id: str | None = None) -> None:
    if not isinstance(waves, list):
        errors.append("execution_path.waves must be a list")
        return
    if not waves:
        errors.append("execution_path.waves must be non-empty")
        return
    seen_wave_ids: set[str] = {first_wave_id} if first_wave_id is not None else set()
    depends_on: dict[str, list[str]] = {}
    for index, wave in enumerate(waves):
        label = f"waves[{index}]"
        if not isinstance(wave, dict):
            errors.append(f"{label} must be an object")
            continue
        _require_keys(wave, ["id", "depends_on", "concurrency_cap", "slices", "exit_gate"], label, errors)
        wave_id = wave.get("id")
        if "id" in wave and not _non_empty_string(wave_id):
            errors.append(f"{label}.id is empty")
        elif isinstance(wave_id, str):
            if wave_id in seen_wave_ids:
                errors.append("execution_path.waves contains duplicate ids")
            else:
                seen_wave_ids.add(wave_id)
        if "depends_on" in wave and not isinstance(wave["depends_on"], list):
            errors.append(f"{label}.depends_on must be a list")
        elif isinstance(wave.get("depends_on"), list) and any(not _non_empty_string(dep) for dep in wave["depends_on"]):
            errors.append(f"{label}.depends_on contains an empty id")
        if "concurrency_cap" in wave and not (isinstance(wave["concurrency_cap"], int) and wave["concurrency_cap"] >= 1):
            errors.append(f"{label}.concurrency_cap must be a positive integer")
        if "slices" in wave and not _non_empty_list(wave["slices"]):
            errors.append(f"{label}.slices must be non-empty")
        elif isinstance(wave.get("slices"), list) and any(not _non_empty_string(slice_id) for slice_id in wave["slices"]):
            errors.append(f"{label}.slices contains an empty slice id")
        if "exit_gate" in wave and not _non_empty_string(wave["exit_gate"]):
            errors.append(f"{label}.exit_gate is empty")
        if "entry_gate" in wave and not _non_empty_string(wave["entry_gate"]):
            errors.append(f"{label}.entry_gate is empty")
        depends = wave.get("depends_on") if isinstance(wave.get("depends_on"), list) else []
        if first_wave_id is not None and not depends:
            errors.append(f"{label}.depends_on must reference first_wave or a verified prior wave")
        if depends:
            if "entry_gate" not in wave:
                errors.append(f"{label} missing entry_gate for dependent wave")
            elif _non_empty_string(wave["entry_gate"]):
                lowered_entry_gate = wave["entry_gate"].lower()
                if not any(marker in lowered_entry_gate for marker in ("receipt", "verified", "exit gate")):
                    errors.append(f"{label}.entry_gate must reference prior receipt/verified/exit gate semantics")
        if isinstance(wave_id, str):
            depends_on[wave_id] = depends

    for wave_id, wave_deps in depends_on.items():
        for dep_id in wave_deps:
            if dep_id not in seen_wave_ids:
                errors.append(f"execution_path.waves.{wave_id} depends_on unknown wave id: {dep_id}")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in visited:
            return
        if node_id in visiting:
            errors.append("execution_path.waves contains a dependency cycle")
            return
        visiting.add(node_id)
        for dep_id in depends_on.get(node_id, []):
            if dep_id in depends_on:
                visit(dep_id)
        visiting.remove(node_id)
        visited.add(node_id)

    for wave_id in depends_on:
        visit(wave_id)


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
    if not isinstance(workers, list):
        errors.append("workers must be a list")
        return
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
    if not isinstance(handoffs, list):
        errors.append("handoffs must be a list")
        return
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
    if not isinstance(gates, list):
        errors.append("risk_gates must be a list")
        return
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
    first_wave_id = None
    if "first_wave" in execution:
        first_wave_id = _validate_execution_first_wave(execution["first_wave"], errors)
    if "waves" in execution:
        _validate_execution_waves(execution["waves"], errors, first_wave_id=first_wave_id)
