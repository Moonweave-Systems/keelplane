#!/usr/bin/env python3
"""Evaluate V0.5 workflow.plan.json fixtures.

The evaluator is intentionally deterministic and stdlib-only. It validates the
machine-readable contract, checks fixture activation expectations, scores
candidate and baseline records, and regenerates reports under ``out/v0.5``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "0.5"
CREATED_BY = "dynamic-workflow-designer"
METRICS = [
    "activation_discipline",
    "executable_artifact",
    "handoff_clarity",
    "verification_strength",
    "safety_gating",
    "resume_value",
    "downstream_consumer_success",
]
KEEP_KILL_METRICS = [
    "activation_discipline",
    "handoff_clarity",
    "verification_strength",
    "safety_gating",
    "downstream_consumer_success",
]
EXCLUSIVE_THRESHOLDS = {
    "downstream-consumer",
    "resumable-handoffs",
    "multi-surface-fanout",
}
SUPPORTING_THRESHOLDS = {
    "planned-fanout",
    "adversarial-verification",
    "human-gates",
}
DOWNGRADE_TARGETS = {"direct-codex", "workflow-router", "simple-plan"}
SURFACE_KINDS = {
    "repo",
    "package",
    "artifact",
    "api",
    "data-source",
    "web-source",
    "document",
}
ACCESS_MODES = {"read-only", "write-proposed", "write-approved"}
PARALLELISM_SHAPES = {
    "none",
    "pipeline",
    "fan-out-fan-in",
    "judge-panel",
    "hybrid",
}
EXECUTION_MODES = {
    "direct-codex",
    "subagent-plan",
    "plugin",
    "runtime",
    "backlog",
}
CONSUMERS = {"human", "codex-agent", "runtime"}
ARTIFACT_FORMATS = {
    "json",
    "markdown",
    "patch",
    "test-log",
    "rendered-artifact",
    "other",
}


class EvaluationError(ValueError):
    """Raised when a plan or manifest fails the V0.5 contract."""


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise EvaluationError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise EvaluationError(f"{path} must contain a JSON object")
    return data


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise EvaluationError(message)


def non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def non_empty_list(value: Any) -> bool:
    return isinstance(value, list) and bool(value)


def require_keys(data: dict[str, Any], keys: list[str], where: str) -> None:
    missing = [key for key in keys if key not in data]
    require(not missing, f"{where} missing keys: {missing}")


def canonical_patterns() -> set[str]:
    text = (ROOT / "references" / "workflow-patterns.md").read_text()
    return {
        line.removeprefix("## ").strip()
        for line in text.splitlines()
        if line.startswith("## ")
    }


def hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def validate_activation(plan: dict[str, Any], expected: dict[str, Any] | None) -> None:
    activation = plan.get("activation")
    require(isinstance(activation, dict), "activation must be an object")
    require_keys(
        activation,
        ["decision", "matched_thresholds", "downgrade_target", "reason"],
        "activation",
    )
    decision = activation["decision"]
    require(decision in {"activate", "downgrade"}, "activation.decision is invalid")
    require(non_empty_string(activation["reason"]), "activation.reason is empty")
    require(
        isinstance(activation["matched_thresholds"], list),
        "activation.matched_thresholds must be a list",
    )
    thresholds = set(activation["matched_thresholds"])
    require(
        all(non_empty_string(item) for item in activation["matched_thresholds"]),
        "activation.matched_thresholds contains an empty value",
    )

    if decision == "activate":
        require(
            activation["downgrade_target"] is None,
            "activated plans must use null downgrade_target",
        )
        require(
            thresholds & EXCLUSIVE_THRESHOLDS,
            "activated plans need an exclusive threshold",
        )
        require(
            thresholds & SUPPORTING_THRESHOLDS,
            "activated plans need a supporting threshold",
        )
    else:
        require(
            activation["downgrade_target"] in DOWNGRADE_TARGETS,
            "downgrade plans need a valid downgrade_target",
        )

    if expected:
        require(
            decision == expected["activation"],
            f"activation mismatch: expected {expected['activation']}, got {decision}",
        )
        if expected.get("downgrade_target") is not None:
            require(
                activation["downgrade_target"] == expected["downgrade_target"],
                "downgrade target mismatch",
            )
        for threshold in expected.get("required_thresholds", []):
            require(
                threshold in thresholds,
                f"missing required activation threshold: {threshold}",
            )


def validate_surfaces(plan: dict[str, Any]) -> None:
    surfaces = plan["surfaces"]
    require(non_empty_list(surfaces), "surfaces must be a non-empty list")
    for surface in surfaces:
        require(isinstance(surface, dict), "surface must be an object")
        require_keys(surface, ["id", "kind", "locator", "access_mode"], "surface")
        require(non_empty_string(surface["id"]), "surface.id is empty")
        require(surface["kind"] in SURFACE_KINDS, f"invalid surface kind: {surface}")
        require(non_empty_string(surface["locator"]), "surface.locator is empty")
        require(surface["access_mode"] in ACCESS_MODES, "invalid surface access_mode")


def validate_assumptions(plan: dict[str, Any], activated: bool) -> None:
    assumptions = plan["assumptions"]
    require(isinstance(assumptions, list), "assumptions must be a list")
    require(assumptions or not activated, "activated plans need assumptions")
    for item in assumptions:
        require(isinstance(item, dict), "assumption must be an object")
        require_keys(item, ["claim", "verification"], "assumption")
        require(non_empty_string(item["claim"]), "assumption.claim is empty")
        require(non_empty_string(item["verification"]), "assumption.verification is empty")


def validate_patterns(plan: dict[str, Any], expected: dict[str, Any] | None) -> None:
    valid_patterns = canonical_patterns()
    patterns = plan["patterns"]
    require(isinstance(patterns, list), "patterns must be a list")
    for pattern in patterns:
        require(pattern in valid_patterns, f"unknown pattern: {pattern}")
    if expected:
        for pattern in expected.get("required_patterns", []):
            require(pattern in patterns, f"missing required pattern: {pattern}")
        for pattern in expected.get("forbidden_patterns", []):
            require(pattern not in patterns, f"forbidden pattern present: {pattern}")


def validate_phases(plan: dict[str, Any], activated: bool) -> None:
    phases = plan["phases"]
    require(isinstance(phases, list), "phases must be a list")
    require(phases or not activated, "activated plans need phases")
    seen_workers = {worker.get("id") for worker in plan["workers"] if isinstance(worker, dict)}
    for phase in phases:
        require(isinstance(phase, dict), "phase must be an object")
        require_keys(
            phase,
            [
                "id",
                "name",
                "entry_criteria",
                "exit_criteria",
                "depends_on",
                "worker_ids",
                "outputs",
            ],
            "phase",
        )
        for key in ["id", "name"]:
            require(non_empty_string(phase[key]), f"phase.{key} is empty")
        for key in ["entry_criteria", "exit_criteria", "worker_ids", "outputs"]:
            require(non_empty_list(phase[key]), f"phase.{key} must be non-empty")
        require(isinstance(phase["depends_on"], list), "phase.depends_on must be a list")
        for worker_id in phase["worker_ids"]:
            require(worker_id in seen_workers, f"phase references unknown worker: {worker_id}")


def validate_workers(plan: dict[str, Any], activated: bool) -> None:
    workers = plan["workers"]
    require(isinstance(workers, list), "workers must be a list")
    require(workers or not activated, "activated plans need workers")
    if not activated:
        require(len(workers) <= 1, "downgrade artifacts must not emit multi-agent prompts")
    for worker in workers:
        require(isinstance(worker, dict), "worker must be an object")
        require_keys(
            worker,
            [
                "id",
                "role",
                "tool_permissions",
                "forbidden_actions",
                "context_budget",
                "prompt_contract",
                "ownership",
            ],
            "worker",
        )
        require(non_empty_string(worker["id"]), "worker.id is empty")
        require(non_empty_string(worker["role"]), "worker.role is empty")
        require(isinstance(worker["forbidden_actions"], list), "forbidden_actions must be a list")
        require(isinstance(worker["ownership"], list), "ownership must be a list")

        permissions = worker["tool_permissions"]
        require(isinstance(permissions, dict), "tool_permissions must be an object")
        require_keys(
            permissions,
            ["read", "write", "shell", "network", "mcp_connectors", "requires_escalation_for"],
            "tool_permissions",
        )
        for key in ["read", "write", "shell", "network"]:
            require(isinstance(permissions[key], bool), f"tool_permissions.{key} must be boolean")
        require(isinstance(permissions["mcp_connectors"], list), "mcp_connectors must be a list")
        require(
            isinstance(permissions["requires_escalation_for"], list),
            "requires_escalation_for must be a list",
        )

        budget = worker["context_budget"]
        require(isinstance(budget, dict), "context_budget must be an object")
        require_keys(
            budget,
            ["max_files", "max_tokens", "must_include", "must_exclude"],
            "context_budget",
        )
        require(isinstance(budget["max_files"], int) and budget["max_files"] >= 0, "bad max_files")
        require(isinstance(budget["max_tokens"], int) and budget["max_tokens"] > 0, "bad max_tokens")
        require(isinstance(budget["must_include"], list), "must_include must be a list")
        require(isinstance(budget["must_exclude"], list), "must_exclude must be a list")

        contract = worker["prompt_contract"]
        require(isinstance(contract, dict), "prompt_contract must be an object")
        require_keys(
            contract,
            ["inputs", "required_output_schema", "stop_conditions"],
            "prompt_contract",
        )
        require(non_empty_list(contract["inputs"]), "prompt_contract.inputs is empty")
        require(
            non_empty_string(contract["required_output_schema"]),
            "required_output_schema is empty",
        )
        require(non_empty_list(contract["stop_conditions"]), "stop_conditions is empty")


def validate_handoffs(plan: dict[str, Any], activated: bool) -> None:
    handoffs = plan["handoffs"]
    require(isinstance(handoffs, list), "handoffs must be a list")
    require(handoffs or not activated, "activated plans need handoffs")
    for handoff in handoffs:
        require(isinstance(handoff, dict), "handoff must be an object")
        require_keys(handoff, ["from_phase", "to_phase", "artifact", "artifact_schema"], "handoff")
        for key in ["from_phase", "to_phase", "artifact"]:
            require(non_empty_string(handoff[key]), f"handoff.{key} is empty")
        schema = handoff["artifact_schema"]
        require(isinstance(schema, dict), "artifact_schema must be an object")
        require_keys(schema, ["format", "required_fields", "validation_command"], "artifact_schema")
        require(schema["format"] in ARTIFACT_FORMATS, "invalid artifact format")
        require(non_empty_list(schema["required_fields"]), "artifact required_fields is empty")
        require(non_empty_string(schema["validation_command"]), "validation_command is empty")


def validate_parallelism(plan: dict[str, Any], activated: bool) -> None:
    parallelism = plan["parallelism"]
    require(isinstance(parallelism, dict), "parallelism must be an object")
    require_keys(parallelism, ["shape", "concurrency_cap", "fan_in_rule", "barriers"], "parallelism")
    require(parallelism["shape"] in PARALLELISM_SHAPES, "invalid parallelism shape")
    require(
        isinstance(parallelism["concurrency_cap"], int) and parallelism["concurrency_cap"] >= 1,
        "parallelism.concurrency_cap must be a positive integer",
    )
    require(non_empty_string(parallelism["fan_in_rule"]), "parallelism.fan_in_rule is empty")
    require(isinstance(parallelism["barriers"], list), "parallelism.barriers must be a list")
    if not activated:
        require(parallelism["shape"] == "none", "downgrade artifacts must use no parallelism")
        require(parallelism["concurrency_cap"] == 1, "downgrade concurrency cap must be 1")


def validate_verification(plan: dict[str, Any], activated: bool) -> None:
    verification = plan["verification"]
    require(isinstance(verification, list), "verification must be a list")
    require(verification or not activated, "activated plans need verification")
    for item in verification:
        require(isinstance(item, dict), "verification item must be an object")
        require_keys(item, ["claim_or_output", "falsifier", "evidence_required"], "verification")
        require(non_empty_string(item["claim_or_output"]), "claim_or_output is empty")
        require(non_empty_string(item["falsifier"]), "falsifier is empty")
        require(non_empty_list(item["evidence_required"]), "evidence_required is empty")


def validate_risk_gates(plan: dict[str, Any], expected: dict[str, Any] | None) -> None:
    gates = plan["risk_gates"]
    require(isinstance(gates, list), "risk_gates must be a list")
    triggers = []
    for gate in gates:
        require(isinstance(gate, dict), "risk gate must be an object")
        require_keys(gate, ["trigger", "safe_default", "requires_user_approval"], "risk_gate")
        require(non_empty_string(gate["trigger"]), "risk gate trigger is empty")
        require(non_empty_string(gate["safe_default"]), "risk gate safe_default is empty")
        require(isinstance(gate["requires_user_approval"], bool), "requires_user_approval must be bool")
        triggers.append(gate["trigger"].lower())
    if expected:
        joined = " ".join(triggers)
        for required in expected.get("required_risk_gates", []):
            require(required.lower() in joined, f"missing required risk gate: {required}")


def validate_budget_resume_execution(plan: dict[str, Any], activated: bool) -> None:
    budget = plan["budget"]
    require(isinstance(budget, dict), "budget must be an object")
    require_keys(
        budget,
        ["max_agents", "max_rounds", "max_retries", "time_box", "file_touch_limit"],
        "budget",
    )
    for key in ["max_agents", "max_rounds", "max_retries"]:
        require(isinstance(budget[key], int) and budget[key] >= 0, f"budget.{key} is invalid")
    require(non_empty_string(budget["time_box"]), "budget.time_box is empty")
    require(non_empty_string(budget["file_touch_limit"]), "budget.file_touch_limit is empty")
    if not activated:
        require(budget["max_agents"] <= 1, "downgrade artifacts must not allocate multiple agents")

    resume = plan["resume"]
    require(isinstance(resume, dict), "resume must be an object")
    require_keys(resume, ["cacheable_outputs", "invalidators", "restart_points"], "resume")
    for key in ["cacheable_outputs", "invalidators", "restart_points"]:
        require(isinstance(resume[key], list), f"resume.{key} must be a list")
    require(resume["cacheable_outputs"] or not activated, "activated plans need cacheable outputs")
    require(resume["restart_points"] or not activated, "activated plans need restart points")

    execution = plan["execution_path"]
    require(isinstance(execution, dict), "execution_path must be an object")
    require_keys(execution, ["mode", "first_slice", "consumer"], "execution_path")
    require(execution["mode"] in EXECUTION_MODES, "invalid execution mode")
    require(execution["consumer"] in CONSUMERS, "invalid consumer")
    first_slice = execution["first_slice"]
    require(isinstance(first_slice, dict), "first_slice must be an object")
    require_keys(
        first_slice,
        ["instruction", "inputs", "expected_output", "completion_check", "forbidden_actions"],
        "first_slice",
    )
    require(non_empty_string(first_slice["instruction"]), "first_slice.instruction is empty")
    require(isinstance(first_slice["inputs"], list), "first_slice.inputs must be a list")
    require(non_empty_string(first_slice["expected_output"]), "first_slice.expected_output is empty")
    require(non_empty_string(first_slice["completion_check"]), "first_slice.completion_check is empty")
    require(isinstance(first_slice["forbidden_actions"], list), "first_slice.forbidden_actions must be a list")


def validate_plan(
    plan: dict[str, Any],
    expected: dict[str, Any] | None = None,
    *,
    require_dynamic_created_by: bool = True,
) -> None:
    require_keys(
        plan,
        [
            "schema_version",
            "plan_id",
            "created_by",
            "source_prompt",
            "activation",
            "objective",
            "surfaces",
            "assumptions",
            "patterns",
            "phases",
            "workers",
            "handoffs",
            "parallelism",
            "verification",
            "risk_gates",
            "budget",
            "resume",
            "execution_path",
        ],
        "plan",
    )
    require(plan["schema_version"] == SCHEMA_VERSION, "unsupported schema_version")
    require(non_empty_string(plan["plan_id"]), "plan_id is empty")
    require(non_empty_string(plan["created_by"]), "created_by is empty")
    require(non_empty_string(plan["source_prompt"]), "source_prompt is empty")
    require(non_empty_string(plan["objective"]), "objective is empty")
    validate_activation(plan, expected)
    activated = plan["activation"]["decision"] == "activate"
    if require_dynamic_created_by:
        require(plan["created_by"] == CREATED_BY, "candidate created_by mismatch")
    validate_surfaces(plan)
    validate_assumptions(plan, activated)
    validate_patterns(plan, expected)
    validate_workers(plan, activated)
    validate_phases(plan, activated)
    validate_handoffs(plan, activated)
    validate_parallelism(plan, activated)
    validate_verification(plan, activated)
    validate_risk_gates(plan, expected)
    validate_budget_resume_execution(plan, activated)


def render_blueprint(plan: dict[str, Any]) -> str:
    lines = [
        f"# {plan['plan_id']}",
        "",
        f"Objective: {plan['objective']}",
        f"Activation: {plan['activation']['decision']} ({plan['activation']['reason']})",
        f"Patterns: {', '.join(plan['patterns']) if plan['patterns'] else 'none'}",
        "",
        "## First Slice",
        "",
        plan["execution_path"]["first_slice"]["instruction"],
        "",
        f"Completion check: {plan['execution_path']['first_slice']['completion_check']}",
        "",
        "## Risk Gates",
        "",
    ]
    if plan["risk_gates"]:
        for gate in plan["risk_gates"]:
            lines.append(f"- {gate['trigger']}: {gate['safe_default']}")
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def candidate_scores(
    plan: dict[str, Any],
    expected: dict[str, Any],
    downstream_consumer_success: int,
) -> dict[str, int]:
    decision_ok = plan["activation"]["decision"] == expected["activation"]
    gates_ok = all(
        required.lower() in " ".join(g["trigger"].lower() for g in plan["risk_gates"])
        for required in expected.get("required_risk_gates", [])
    )
    is_activate = plan["activation"]["decision"] == "activate"
    return {
        "activation_discipline": 2 if decision_ok else 0,
        "executable_artifact": 2,
        "handoff_clarity": 2 if (plan["handoffs"] or not is_activate) else 1,
        "verification_strength": 2 if plan["verification"] else (1 if not is_activate else 0),
        "safety_gating": 2 if gates_ok else 1,
        "resume_value": 2 if plan["resume"]["restart_points"] else (1 if not is_activate else 0),
        "downstream_consumer_success": downstream_consumer_success,
    }


def validate_scores(scores: dict[str, Any], where: str) -> dict[str, int]:
    require_keys(scores, METRICS, where)
    clean: dict[str, int] = {}
    for metric in METRICS:
        value = scores[metric]
        require(isinstance(value, int) and 0 <= value <= 2, f"{where}.{metric} must be 0..2")
        clean[metric] = value
    return clean


def load_baseline(
    entry: dict[str, Any],
    fixture_id: str,
    prompt_text: str,
    expected: dict[str, Any],
) -> dict[str, Any]:
    name = entry["name"]
    source_path = ROOT / entry["source_path"]
    require(source_path.exists(), f"baseline source not found: {entry['source_path']}")
    fixture_records = entry.get("fixture_records")
    require(isinstance(fixture_records, dict), f"baseline {name} must use fixture_records")
    require(fixture_id in fixture_records, f"baseline {name} missing fixture record for {fixture_id}")
    record = fixture_records[fixture_id]
    if record.get("normalized_plan"):
        plan_path = ROOT / record["normalized_plan"]
        plan = read_json(plan_path)
        validate_plan(plan, expected, require_dynamic_created_by=False)
        scores = candidate_scores(plan, expected, downstream_consumer_success=1)
        return {
            "name": name,
            "normalized": True,
            "artifact_path": record["normalized_plan"],
            "normalization_failure": None,
            "scores": scores,
        }
    if record.get("normalization_failure"):
        failure_path = ROOT / record["normalization_failure"]
        failure = read_json(failure_path)
        require(failure.get("baseline") == name, f"{failure_path} baseline mismatch")
        require(failure.get("fixture_id") == fixture_id, f"{failure_path} fixture mismatch")
        require(failure.get("prompt") == prompt_text, f"{failure_path} prompt mismatch")
        scores = validate_scores(failure["scores"], f"{name}.scores")
        return {
            "name": name,
            "normalized": False,
            "artifact_path": None,
            "normalization_failure": rel(failure_path),
            "reason": failure.get("reason", ""),
            "scores": scores,
        }
    raise EvaluationError(f"baseline {name} lacks normalized_plan or normalization_failure for {fixture_id}")


def validate_raw_output(raw_path: Path, plan_path: Path, plan: dict[str, Any], fixture_id: str) -> str:
    raw_text = raw_path.read_text()
    plan_text = plan_path.read_text()
    require(raw_text != plan_text, f"{fixture_id} raw output duplicates parsed plan")
    raw = read_json(raw_path)
    require(raw.get("fixture_id") == fixture_id, f"{fixture_id} raw output fixture mismatch")
    require(raw.get("raw_kind") == "workflow-output", f"{fixture_id} raw output has wrong kind")
    require(raw.get("workflow_plan") == plan, f"{fixture_id} raw output does not contain parsed plan")
    require(non_empty_string(raw.get("rendered_blueprint")), f"{fixture_id} raw output missing rendered blueprint")
    return raw_text


def validate_consumer_report(
    report_path: Path,
    plan: dict[str, Any],
    expected: dict[str, Any],
) -> int:
    report = read_json(report_path)
    require(report.get("fixture_id") == plan["plan_id"], f"{report_path} fixture mismatch")
    require(report.get("consumer_verdict") == "pass", f"{report_path} consumer did not pass")
    require(report.get("received_spec_or_expected_answer") is False, f"{report_path} is not blinded")
    first_slice = plan["execution_path"]["first_slice"]
    require(report.get("first_slice") == first_slice["instruction"], f"{report_path} first slice mismatch")
    require(non_empty_list(report.get("inputs_needed")), f"{report_path} missing inputs")
    require(report.get("expected_output") == first_slice["expected_output"], f"{report_path} expected output mismatch")
    require(report.get("completion_check") == first_slice["completion_check"], f"{report_path} completion check mismatch")
    require(non_empty_list(report.get("forbidden_actions_identified")), f"{report_path} missing forbidden actions")
    if plan["activation"]["decision"] == "downgrade":
        require(
            report.get("agreed_downgrade_target") == expected.get("downgrade_target"),
            f"{report_path} downgrade target disagreement",
        )
    else:
        require(non_empty_list(report.get("risk_gates_identified")), f"{report_path} missing risk gates")
    return 2


def average(scores: dict[str, int], metrics: list[str]) -> float:
    return sum(scores[metric] for metric in metrics) / len(metrics)


def evaluate_fixture(
    fixture: dict[str, Any],
    baselines: list[dict[str, Any]],
    out_root: Path,
    skill_hash: str,
) -> dict[str, Any]:
    fixture_id = fixture["id"]
    expected = fixture["expected"]
    plan_path = ROOT / fixture["candidate_plan"]
    prompt_path = ROOT / fixture["prompt_path"]
    raw_path = ROOT / fixture["raw_output"]
    consumer_path = ROOT / fixture["consumer_report"]
    plan = read_json(plan_path)
    validate_plan(plan, expected)
    raw_text = validate_raw_output(raw_path, plan_path, plan, fixture_id)
    require(
        plan["source_prompt"].strip() == prompt_path.read_text().strip(),
        f"{fixture_id} plan source_prompt does not match prompt file",
    )
    consumer_score = validate_consumer_report(consumer_path, plan, expected)

    fixture_out = out_root / fixture_id
    fixture_out.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(plan_path, fixture_out / "workflow.plan.json")
    (fixture_out / "raw-output.json").write_text(raw_text)
    (fixture_out / "blueprint.md").write_text(render_blueprint(plan))
    (fixture_out / "skill.sha256").write_text(skill_hash + "\n")

    candidate = {
        "name": CREATED_BY,
        "normalized": True,
        "artifact_path": rel(plan_path),
        "raw_output_path": rel(raw_path),
        "scores": candidate_scores(plan, expected, consumer_score),
    }
    baseline_records = [
        load_baseline(baseline, fixture_id, prompt_path.read_text().strip(), expected)
        for baseline in baselines
    ]
    scorecard = {
        "fixture_id": fixture_id,
        "category": fixture["category"],
        "prompt_path": fixture["prompt_path"],
        "skill_hash": skill_hash,
        "candidate": candidate,
        "baselines": baseline_records,
    }
    consumer_out = out_root / "consumer" / f"{fixture_id}.json"
    consumer_out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(consumer_path, consumer_out)
    scorecard["consumer_report"] = rel(consumer_out)
    write_json(fixture_out / "scorecard.json", scorecard)
    return scorecard


def evaluate_manifest(manifest_path: Path, out_root: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    require_keys(manifest, ["fixtures", "baselines"], "manifest")
    fixture_ids = [fixture["id"] for fixture in manifest["fixtures"]]
    require(len(fixture_ids) == len(set(fixture_ids)), "manifest fixture ids must be unique")
    for baseline in manifest["baselines"]:
        require("source_path" in baseline, f"baseline {baseline.get('name')} missing source_path")
        fixture_records = baseline.get("fixture_records")
        require(isinstance(fixture_records, dict), f"baseline {baseline.get('name')} must use fixture_records")
        missing = [fixture_id for fixture_id in fixture_ids if fixture_id not in fixture_records]
        require(not missing, f"baseline {baseline.get('name')} missing fixture records: {missing}")
    out_root.mkdir(parents=True, exist_ok=True)
    skill_hash = hash_file(ROOT / "SKILL.md")
    scorecards = [
        evaluate_fixture(fixture, manifest["baselines"], out_root, skill_hash)
        for fixture in manifest["fixtures"]
    ]
    categories = {card["category"] for card in scorecards}
    require({"positive", "negative", "borderline", "meta"} <= categories, "manifest misses categories")
    require(sum(1 for card in scorecards if card["category"] == "positive") >= 4, "need four positives")
    require(sum(1 for card in scorecards if card["category"] == "negative") >= 4, "need four negatives")
    require(sum(1 for card in scorecards if card["category"] == "borderline") >= 3, "need three borderline fixtures")
    require(sum(1 for card in scorecards if card["category"] == "meta") >= 1, "need one meta fixture")

    candidate_avg = sum(average(card["candidate"]["scores"], KEEP_KILL_METRICS) for card in scorecards) / len(scorecards)
    baseline_avgs: dict[str, float] = {}
    for baseline in manifest["baselines"]:
        name = baseline["name"]
        values = [
            average(next(item for item in card["baselines"] if item["name"] == name)["scores"], KEEP_KILL_METRICS)
            for card in scorecards
        ]
        baseline_avgs[name] = sum(values) / len(values)
    keep = all(candidate_avg >= value * 1.2 for value in baseline_avgs.values())
    summary = {
        "manifest": rel(manifest_path),
        "fixture_count": len(scorecards),
        "candidate_keep_kill_average": round(candidate_avg, 3),
        "baseline_keep_kill_averages": {key: round(value, 3) for key, value in baseline_avgs.items()},
        "decision": "keep" if keep else "kill-or-merge",
        "scorecards": [f"{card['fixture_id']}/scorecard.json" for card in scorecards],
    }
    write_json(out_root / "summary.json", summary)
    return summary


def valid_plan_fixture(decision: str = "activate") -> dict[str, Any]:
    activation = {
        "decision": decision,
        "matched_thresholds": ["resumable-handoffs", "adversarial-verification"] if decision == "activate" else [],
        "downgrade_target": None if decision == "activate" else "direct-codex",
        "reason": "Fixture rationale.",
    }
    return {
        "schema_version": "0.5",
        "plan_id": f"self-test-{decision}",
        "created_by": CREATED_BY,
        "source_prompt": "Design a workflow.",
        "activation": activation,
        "objective": "Produce a reusable workflow artifact.",
        "surfaces": [{"id": "repo", "kind": "repo", "locator": ".", "access_mode": "read-only"}],
        "assumptions": [{"claim": "Inputs exist.", "verification": "Inspect the fixture files."}],
        "patterns": ["Sequential"] if decision == "activate" else [],
        "phases": [
            {
                "id": "inspect",
                "name": "Inspect",
                "entry_criteria": ["Prompt is available"],
                "exit_criteria": ["Inputs are listed"],
                "depends_on": [],
                "worker_ids": ["planner"],
                "outputs": ["input-ledger"],
            }
        ] if decision == "activate" else [],
        "workers": [
            {
                "id": "planner",
                "role": "Planner",
                "tool_permissions": {
                    "read": True,
                    "write": False,
                    "shell": False,
                    "network": False,
                    "mcp_connectors": [],
                    "requires_escalation_for": ["write", "shell", "network"],
                },
                "forbidden_actions": ["edit files"],
                "context_budget": {
                    "max_files": 5,
                    "max_tokens": 2000,
                    "must_include": ["prompt"],
                    "must_exclude": ["secrets"],
                },
                "prompt_contract": {
                    "inputs": ["prompt"],
                    "required_output_schema": "input-ledger",
                    "stop_conditions": ["missing prompt"],
                },
                "ownership": ["planning only"],
            }
        ] if decision == "activate" else [],
        "handoffs": [
            {
                "from_phase": "inspect",
                "to_phase": "inspect",
                "artifact": "input-ledger",
                "artifact_schema": {
                    "format": "json",
                    "required_fields": ["inputs"],
                    "validation_command": "python -m json.tool input-ledger.json",
                },
            }
        ] if decision == "activate" else [],
        "parallelism": {"shape": "none", "concurrency_cap": 1, "fan_in_rule": "No fan-in.", "barriers": []},
        "verification": [
            {
                "claim_or_output": "Plan is reusable.",
                "falsifier": "A consumer cannot identify the first slice.",
                "evidence_required": ["consumer report"],
            }
        ] if decision == "activate" else [],
        "risk_gates": [
            {
                "trigger": "write action",
                "safe_default": "stop before writing",
                "requires_user_approval": True,
            }
        ],
        "budget": {
            "max_agents": 1,
            "max_rounds": 1,
            "max_retries": 0,
            "time_box": "10 minutes",
            "file_touch_limit": "none",
        },
        "resume": {
            "cacheable_outputs": ["input-ledger"] if decision == "activate" else [],
            "invalidators": ["prompt changes"],
            "restart_points": ["inspect"] if decision == "activate" else [],
        },
        "execution_path": {
            "mode": "subagent-plan" if decision == "activate" else "direct-codex",
            "first_slice": {
                "instruction": "Inspect the prompt and list required inputs.",
                "inputs": ["prompt"],
                "expected_output": "input ledger",
                "completion_check": "ledger has inputs",
                "forbidden_actions": ["write files"],
            },
            "consumer": "codex-agent",
        },
    }


def self_test() -> None:
    active = valid_plan_fixture("activate")
    validate_plan(active, {"activation": "activate", "required_thresholds": ["resumable-handoffs"]})
    downgrade = valid_plan_fixture("downgrade")
    validate_plan(downgrade, {"activation": "downgrade", "downgrade_target": "direct-codex"})

    wrong_creator = json.loads(json.dumps(active))
    wrong_creator["created_by"] = "other-workflow-tool"
    try:
        validate_plan(wrong_creator, {"activation": "activate"})
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: wrong created_by passed")

    bad = dict(active)
    bad["patterns"] = ["Imaginary Pattern"]
    try:
        validate_plan(bad, {"activation": "activate"})
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: unknown pattern passed")

    bad_worker = json.loads(json.dumps(active))
    bad_worker["workers"][0]["tool_permissions"]["shell"] = "false"
    try:
        validate_plan(bad_worker, {"activation": "activate"})
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: non-boolean tool permission passed")

    bad_gate = json.loads(json.dumps(active))
    bad_gate["risk_gates"][0]["safe_default"] = ""
    try:
        validate_plan(bad_gate, {"activation": "activate"})
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: empty safe default passed")

    valid_report = {
        "fixture_id": active["plan_id"],
        "consumer_verdict": "pass",
        "received_spec_or_expected_answer": False,
        "first_slice": active["execution_path"]["first_slice"]["instruction"],
        "inputs_needed": ["prompt"],
        "expected_output": active["execution_path"]["first_slice"]["expected_output"],
        "completion_check": active["execution_path"]["first_slice"]["completion_check"],
        "forbidden_actions_identified": ["write files"],
        "risk_gates_identified": ["write action"],
    }
    tmp_report = ROOT / "out" / "v0.5-self-test-consumer.json"
    write_json(tmp_report, valid_report)
    validate_consumer_report(tmp_report, active, {"activation": "activate"})
    bad_report = dict(valid_report)
    bad_report["consumer_verdict"] = "fail"
    write_json(tmp_report, bad_report)
    try:
        validate_consumer_report(tmp_report, active, {"activation": "activate"})
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: failing consumer report passed")
    tmp_report.unlink(missing_ok=True)

    tmp_plan = ROOT / "out" / "v0.5-self-test-plan.json"
    tmp_raw = ROOT / "out" / "v0.5-self-test-raw.json"
    write_json(tmp_plan, active)
    write_json(tmp_raw, active)
    try:
        validate_raw_output(tmp_raw, tmp_plan, active, active["plan_id"])
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: duplicated raw output passed")
    write_json(
        tmp_raw,
        {
            "raw_kind": "workflow-output",
            "fixture_id": active["plan_id"],
            "rendered_blueprint": "blueprint",
            "workflow_plan": active,
        },
    )
    validate_raw_output(tmp_raw, tmp_plan, active, active["plan_id"])
    tmp_plan.unlink(missing_ok=True)
    tmp_raw.unlink(missing_ok=True)

    print("plan evaluator self-test: pass")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--plan")
    parser.add_argument("--manifest")
    parser.add_argument("--out", default="out/v0.5")
    args = parser.parse_args()

    try:
        if args.self_test:
            self_test()
            return
        if args.plan:
            validate_plan(read_json(ROOT / args.plan))
            print(f"plan valid: {args.plan}")
            return
        if args.manifest:
            summary = evaluate_manifest(ROOT / args.manifest, ROOT / args.out)
            print(f"manifest evaluated: {summary['fixture_count']} fixtures, decision={summary['decision']}")
            return
        parser.error("use --self-test, --plan, or --manifest")
    except EvaluationError as exc:
        raise SystemExit(f"evaluate_plan: {exc}") from exc


if __name__ == "__main__":
    main()
