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
import re
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
ESCALATION_TARGETS = {"write", "shell", "network", "external-message"}
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
ALLOWED_BLINDED_INPUTS = {"workflow.plan.json", "blueprint.md", "original prompt", "repository path"}
BASELINE_ADAPTER_VERSION = "0.5-source-contract-v1"
EXPECTED_BASELINES = {"workflow-router-skill", "claude-agent-workflow-designer"}
UNSAFE_DEFAULT_TERMS = {
    "continue",
    "proceed",
    "automatically",
    "after writing",
    "after shell",
    "afterward",
    "afterwards",
    "otherwise",
    "then",
}
FORBIDDEN_PROVENANCE_TERMS = {
    "answer key",
    "expected answer",
    "expected-answer",
    "author commentary",
    "cheat sheet",
    "gold answer",
    "ground truth",
    "marking pass",
    "rubric",
    "scorecard",
    "separate note",
    "solution key",
    "docs/spec",
    "docs slash spec",
    "reviewed against docs",
    "spec boundaries",
    "v0.5-plan",
    "fixture expectation",
}
REPO_INPUT_ALIASES = {
    "checkout path",
    "repository path",
    "repository root",
    "repo path",
    "repo root",
    "working tree",
    "workspace path",
}
POSITIVE_SUPPORT_TERMS = {
    "defines",
    "describes",
    "mentions",
    "preserves",
    "provides",
    "present",
    "routes",
    "supports",
}
CONTRADICTORY_SUPPORT_TERMS = {
    "absent",
    "contradictory",
    "cannot",
    "does not",
    "fails",
    "lack",
    "lacks",
    "missing",
    "no ",
    "not ",
    "unavailable",
    "without",
}
DOWNGRADE_EXECUTION_TARGETS = {
    "direct-codex": ("direct-codex", "human"),
    "workflow-router": ("direct-codex", "human"),
    "simple-plan": ("direct-codex", "human"),
}
BASELINE_OBSERVATION_KEYS = [
    "activation_decision",
    "handoff_guidance",
    "verification_guidance",
    "safety_gates",
    "resume_guidance",
    "consumer_can_route",
]
BASELINE_OBSERVATION_TERMS = {
    "activation_decision": {"activate", "activation", "downgrade", "route", "schema"},
    "handoff_guidance": {"handoff", "summary", "downstream", "continuation"},
    "verification_guidance": {"verification", "verify", "evidence", "check", "falsifier"},
    "safety_gates": {"safety", "gate", "safe-default", "approval", "destructive"},
    "resume_guidance": {"resume", "restartable", "cache", "phase output", "recovery"},
    "consumer_can_route": {"consumer", "route", "downstream", "start"},
}
VACUOUS_INTERPRETATION_TERMS = {"banana", "vibes"}
EXPECTED_CATEGORY_RULES = {
    "positive": ("activate", None),
    "negative": ("downgrade", None),
    "borderline": ("downgrade", "workflow-router"),
    "meta": ("activate", None),
}
EXPECTED_CATEGORY_COUNTS = {"positive": 4, "negative": 4, "borderline": 3, "meta": 1}
FIXTURE_ID_CATEGORY_PREFIXES = {
    "pos": "positive",
    "neg": "negative",
    "border": "borderline",
    "meta": "meta",
}
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
    extra = sorted(set(data) - set(keys))
    require(not extra, f"{where} contains unexpected keys: {extra}")


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


def same_items(left: Any, right: Any) -> bool:
    return isinstance(left, list) and sorted(left) == sorted(right)


def unique_list(value: list[Any]) -> bool:
    return len(value) == len(set(map(str, value)))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def canonical_json_text(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


def word_tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def contains_phrase(text: str, phrase: str) -> bool:
    tokens = word_tokens(text)
    return all(token in tokens for token in word_tokens(phrase))


def interpretation_mentions_observation(key: str, interpretation: str) -> bool:
    normalized = interpretation.lower()
    return any(term in normalized for term in BASELINE_OBSERVATION_TERMS[key])


def activation_interpretation_is_meaningful(interpretation: str) -> bool:
    normalized = interpretation.lower()
    if any(term in normalized for term in VACUOUS_INTERPRETATION_TERMS):
        return False
    routes_or_describes = "routes" in normalized or "describes" in normalized
    schema_boundary = "schema" in normalized and any(
        term in normalized for term in ["does not", "not ", "fails to", "cannot", "lacks"]
    )
    decision_boundary = any(term in normalized for term in ["decide", "emit", "artifact"])
    return routes_or_describes and schema_boundary and decision_boundary


def gate_matches_term(gate: dict[str, Any], term: str) -> bool:
    return contains_phrase(gate["trigger"], term)


def safe_default_blocks_before_action(text: str) -> bool:
    normalized = " ".join(text.lower().split())
    if any(term in normalized for term in UNSAFE_DEFAULT_TERMS):
        return False
    if "/" in normalized or re.search(r"\bor\b", normalized):
        return False
    allowed = [
        r"^stop before [a-z0-9 ,/.-]+ and ask for approval$",
        r"^do not [a-z0-9 ,/.-]+ without approval$",
        r"^preserve [a-z0-9 ,/.-]+ and ask before [a-z0-9 ,/.-]+$",
    ]
    return any(re.fullmatch(pattern, normalized) for pattern in allowed)


def normalized_provenance_text(text: str) -> str:
    deobfuscated = text.lower().translate(str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t"}))
    return " ".join(re.findall(r"[a-z0-9]+", deobfuscated))


def collapsed_provenance_text(text: str) -> str:
    deobfuscated = text.lower().translate(str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t"}))
    return "".join(re.findall(r"[a-z0-9]+", deobfuscated))


def forbid_provenance_leaks(text: str, where: str) -> None:
    normalized = normalized_provenance_text(text)
    collapsed = collapsed_provenance_text(text)
    for forbidden in FORBIDDEN_PROVENANCE_TERMS:
        normalized_forbidden = normalized_provenance_text(forbidden)
        collapsed_forbidden = collapsed_provenance_text(forbidden)
        require(
            normalized_forbidden not in normalized and collapsed_forbidden not in collapsed,
            f"{where} references forbidden provenance source: {forbidden}",
        )


def resolve_out_root(value: str) -> Path:
    path = Path(value)
    resolved = path.resolve() if path.is_absolute() else (ROOT / path).resolve()
    try:
        relative = resolved.relative_to(ROOT)
    except ValueError as exc:
        raise EvaluationError(f"--out must resolve inside this repository: {value}") from exc
    require(relative.parts and relative.parts[0] == "out", "--out must resolve under this repository's out/ directory")
    require(relative != Path("out"), "--out must name a subdirectory under out/")
    return resolved


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
    require(
        len(activation["matched_thresholds"]) == len(thresholds),
        "activation.matched_thresholds contains duplicate values",
    )
    allowed_thresholds = EXCLUSIVE_THRESHOLDS | SUPPORTING_THRESHOLDS
    unknown_thresholds = thresholds - allowed_thresholds
    require(
        not unknown_thresholds,
        f"activation.matched_thresholds contains unknown values: {sorted(unknown_thresholds)}",
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
        require(not thresholds, "downgrade plans must not claim activation thresholds")

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
    activated = plan["activation"]["decision"] == "activate"
    require(patterns or not activated, "activated plans need patterns")
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
    worker_ids = [worker.get("id") for worker in workers if isinstance(worker, dict)]
    require(len(worker_ids) == len(set(worker_ids)), "worker ids must be unique")
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
        require(non_empty_list(worker["forbidden_actions"]), "forbidden_actions must be non-empty")
        require(non_empty_list(worker["ownership"]), "ownership must be non-empty")

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
        unknown_escalations = set(permissions["requires_escalation_for"]) - ESCALATION_TARGETS
        require(
            not unknown_escalations,
            f"requires_escalation_for contains unknown values: {sorted(unknown_escalations)}",
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
        require(non_empty_list(budget["must_include"]), "must_include must be non-empty")
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


def validate_phase_graph(plan: dict[str, Any], activated: bool) -> None:
    phases = plan["phases"]
    phase_ids = [phase["id"] for phase in phases]
    require(len(phase_ids) == len(set(phase_ids)), "phase ids must be unique")
    phase_outputs = {
        phase["id"]: set(phase["outputs"])
        for phase in phases
    }
    for phase in phases:
        for dependency in phase["depends_on"]:
            require(dependency in phase_outputs, f"phase depends on unknown phase: {dependency}")
    dependency_map = {phase["id"]: set(phase["depends_on"]) for phase in phases}

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(phase_id: str) -> None:
        require(phase_id not in visiting, f"phase dependency cycle includes: {phase_id}")
        if phase_id in visited:
            return
        visiting.add(phase_id)
        for dependency in dependency_map[phase_id]:
            visit(dependency)
        visiting.remove(phase_id)
        visited.add(phase_id)

    for phase_id in phase_ids:
        visit(phase_id)

    for handoff in plan["handoffs"]:
        from_phase = handoff["from_phase"]
        to_phase = handoff["to_phase"]
        require(from_phase in phase_outputs, f"handoff from unknown phase: {from_phase}")
        require(to_phase in phase_outputs, f"handoff to unknown phase: {to_phase}")
        if from_phase != to_phase:
            require(
                from_phase in dependency_map[to_phase],
                f"handoff target must depend on source phase: {from_phase} -> {to_phase}",
            )
        require(
            handoff["artifact"] in phase_outputs[from_phase],
            f"handoff artifact not produced by source phase: {handoff['artifact']}",
        )

    restart_points = plan["resume"]["restart_points"]
    for restart_point in restart_points:
        require(restart_point in phase_outputs, f"resume restart point is not a phase: {restart_point}")
    all_outputs = set().union(*phase_outputs.values()) if phase_outputs else set()
    for output in plan["resume"]["cacheable_outputs"]:
        require(output in all_outputs, f"resume cacheable output is not produced by any phase: {output}")
    if activated and phase_ids:
        adjacency = {phase_id: set() for phase_id in phase_ids}
        for phase_id, dependencies in dependency_map.items():
            for dependency in dependencies:
                adjacency[phase_id].add(dependency)
                adjacency[dependency].add(phase_id)
        for handoff in plan["handoffs"]:
            from_phase = handoff["from_phase"]
            to_phase = handoff["to_phase"]
            adjacency[from_phase].add(to_phase)
            adjacency[to_phase].add(from_phase)
        reachable = set()
        stack = [phase_ids[0]]
        while stack:
            phase_id = stack.pop()
            if phase_id in reachable:
                continue
            reachable.add(phase_id)
            stack.extend(sorted(adjacency[phase_id] - reachable))
        require(reachable == set(phase_ids), "activated phase graph must be connected")
    if not activated:
        require(not restart_points, "downgrade artifacts must not define restart points")


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
    activated = plan["activation"]["decision"] == "activate"
    require(gates or not activated, "activated plans need risk gates")
    triggers = []
    for gate in gates:
        require(isinstance(gate, dict), "risk gate must be an object")
        require_keys(gate, ["trigger", "safe_default", "requires_user_approval"], "risk_gate")
        require(non_empty_string(gate["trigger"]), "risk gate trigger is empty")
        require(non_empty_string(gate["safe_default"]), "risk gate safe_default is empty")
        require(isinstance(gate["requires_user_approval"], bool), "requires_user_approval must be bool")
        require(gate["requires_user_approval"] is True, "risk gates must require user approval")
        require(
            safe_default_blocks_before_action(gate["safe_default"]),
            f"risk gate safe_default is not a safe stop/ask/preserve default: {gate['trigger']}",
        )
        triggers.append(gate["trigger"].lower())
    if expected:
        for required in expected.get("required_risk_gates", []):
            require(
                any(contains_phrase(trigger, required) for trigger in triggers),
                f"missing required risk gate: {required}",
            )
    required_gate_terms: set[str] = set()
    for worker in plan["workers"]:
        permissions = worker["tool_permissions"]
        if permissions["write"]:
            required_gate_terms.add("write")
        if permissions["shell"]:
            required_gate_terms.add("shell")
        if permissions["network"]:
            required_gate_terms.add("network")
        for escalation in permissions["requires_escalation_for"]:
            required_gate_terms.add(str(escalation).replace("-", " "))
    for surface in plan["surfaces"]:
        if surface["access_mode"] != "read-only":
            required_gate_terms.add("write")
    if expected:
        for required in expected.get("required_risk_gates", []):
            required_gate_terms.add(str(required).replace("-", " "))
    for term in sorted(required_gate_terms):
        matches = [gate for gate in gates if gate_matches_term(gate, term)]
        require(matches, f"missing risk gate for {term}")
        require(
            any(
                sum(gate_matches_term(gate, other) for other in required_gate_terms) == 1
                for gate in matches
            ),
            f"risk gate for {term} must be separate from other required permission gates",
        )


def validate_budget_resume_execution(plan: dict[str, Any], activated: bool, expected: dict[str, Any] | None) -> None:
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
    require(resume["invalidators"] or not activated, "activated plans need invalidators")
    require(resume["restart_points"] or not activated, "activated plans need restart points")

    execution = plan["execution_path"]
    require(isinstance(execution, dict), "execution_path must be an object")
    require_keys(execution, ["mode", "first_slice", "consumer"], "execution_path")
    require(execution["mode"] in EXECUTION_MODES, "invalid execution mode")
    require(execution["consumer"] in CONSUMERS, "invalid consumer")
    if not activated:
        target = plan["activation"]["downgrade_target"]
        expected_mode, expected_consumer = DOWNGRADE_EXECUTION_TARGETS[target]
        require(execution["mode"] == expected_mode, "downgrade execution mode contradicts target")
        require(execution["consumer"] == expected_consumer, "downgrade consumer contradicts target")
    first_slice = execution["first_slice"]
    require(isinstance(first_slice, dict), "first_slice must be an object")
    require_keys(
        first_slice,
        ["instruction", "inputs", "expected_output", "completion_check", "forbidden_actions"],
        "first_slice",
    )
    require(non_empty_string(first_slice["instruction"]), "first_slice.instruction is empty")
    require(non_empty_list(first_slice["inputs"]), "first_slice.inputs must be non-empty")
    require(non_empty_string(first_slice["expected_output"]), "first_slice.expected_output is empty")
    require(non_empty_string(first_slice["completion_check"]), "first_slice.completion_check is empty")
    require(non_empty_list(first_slice["forbidden_actions"]), "first_slice.forbidden_actions must be non-empty")
    require(unique_list(first_slice["inputs"]), "first_slice.inputs must be unique")
    require(unique_list(first_slice["forbidden_actions"]), "first_slice.forbidden_actions must be unique")
    repo_bound = any(surface["kind"] == "repo" for surface in plan["surfaces"]) or bool(
        expected and expected.get("requires_repository_path")
    )
    if repo_bound:
        require("repository path" in first_slice["inputs"], "repo-bound first_slice.inputs must include repository path")
    else:
        unexpected_repo_inputs = sorted(set(first_slice["inputs"]) & REPO_INPUT_ALIASES)
        require(not unexpected_repo_inputs, f"non-repo first_slice.inputs contains repo-only inputs: {unexpected_repo_inputs}")
    if not activated:
        target = plan["activation"]["downgrade_target"]
        expected_instruction = f"Use {target} instead of dynamic-workflow-designer for this request."
        require(
            first_slice["instruction"] == expected_instruction,
            "downgrade first_slice.instruction must route to the downgrade target",
        )


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
    if not activated:
        require(plan["workers"] == [], "downgrade artifacts must not emit worker prompt contracts")
    validate_surfaces(plan)
    if expected and expected.get("requires_repository_path"):
        require(
            any(surface["kind"] == "repo" for surface in plan["surfaces"]),
            "repo-bound fixtures must declare at least one repo surface",
        )
    if expected and expected.get("fixture_category") == "meta":
        require(plan["execution_path"]["mode"] == "backlog", "meta fixtures must use a backlog execution path")
    validate_assumptions(plan, activated)
    validate_patterns(plan, expected)
    validate_workers(plan, activated)
    validate_phases(plan, activated)
    validate_handoffs(plan, activated)
    validate_parallelism(plan, activated)
    validate_verification(plan, activated)
    validate_risk_gates(plan, expected)
    validate_budget_resume_execution(plan, activated, expected)
    validate_phase_graph(plan, activated)


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


def packet_hashes(plan: dict[str, Any]) -> dict[str, str]:
    hashes = {
        "workflow.plan.json": sha256_text(canonical_json_text(plan)),
        "blueprint.md": sha256_text(render_blueprint(plan)),
        "original prompt": sha256_text(plan["source_prompt"]),
    }
    repo_surfaces = [surface for surface in plan["surfaces"] if surface["kind"] == "repo"]
    if repo_surfaces:
        repo_input = canonical_json_text(
            {
                "repository_surfaces": [
                    {
                        "id": surface["id"],
                        "locator": surface["locator"],
                        "access_mode": surface["access_mode"],
                    }
                    for surface in repo_surfaces
                ]
            }
        )
        hashes["repository surfaces"] = sha256_text(repo_input)
    return hashes


def candidate_scores(
    plan: dict[str, Any],
    expected: dict[str, Any],
    downstream_consumer_success: int,
) -> dict[str, int]:
    decision_ok = plan["activation"]["decision"] == expected["activation"]
    gates_ok = all(
        any(contains_phrase(g["trigger"], required) for g in plan["risk_gates"])
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


def score_baseline_failure(
    failure: dict[str, Any],
    expected: dict[str, Any],
    source_text: str,
) -> dict[str, int]:
    require_keys(
        failure,
        [
            "adapter_version",
            "baseline",
            "fixture_id",
            "normalization_failure_kind",
            "normalized",
            "observation_evidence",
            "observations",
            "prompt",
            "reason",
            "source_sha256",
        ],
        "baseline normalization_failure",
    )
    require("scores" not in failure, "normalization failure records must not contain hand-authored scores")
    require(failure.get("adapter_version") == BASELINE_ADAPTER_VERSION, "baseline adapter version mismatch")
    require(non_empty_string(failure.get("source_sha256")), "baseline source hash is empty")
    require(
        failure.get("normalization_failure_kind") == "no-schema-valid-artifact",
        "baseline failures must record no-schema-valid-artifact",
    )
    observations = failure.get("observations")
    require(isinstance(observations, dict), "baseline observations must be an object")
    require_keys(observations, BASELINE_OBSERVATION_KEYS, "baseline observations")
    for key in ["handoff_guidance", "verification_guidance", "safety_gates", "resume_guidance", "consumer_can_route"]:
        require(isinstance(observations[key], bool), f"baseline observation {key} must be bool")
    evidence = failure.get("observation_evidence")
    require(isinstance(evidence, dict), "baseline observation_evidence must be an object")
    require_keys(evidence, BASELINE_OBSERVATION_KEYS, "baseline observation_evidence")
    seen_excerpts: set[str] = set()
    for key in BASELINE_OBSERVATION_KEYS:
        item = evidence[key]
        require(isinstance(item, dict), f"baseline evidence {key} must be an object")
        evidence_keys = (
            ["observation", "source_excerpt", "interpretation", "activation_support"]
            if key == "activation_decision"
            else ["observation", "source_excerpt", "interpretation", "supports_observation"]
        )
        require_keys(item, evidence_keys, f"baseline evidence {key}")
        require(item["observation"] == key, f"baseline evidence {key} observation mismatch")
        excerpt = item["source_excerpt"]
        require(non_empty_string(excerpt), f"baseline evidence {key} excerpt is empty")
        require(len(excerpt.strip()) >= 24, f"baseline evidence {key} excerpt is too short")
        require(len(word_tokens(excerpt)) >= 4, f"baseline evidence {key} excerpt has too few tokens")
        require(excerpt not in seen_excerpts, f"baseline evidence excerpt reused: {excerpt}")
        seen_excerpts.add(excerpt)
        require(excerpt in source_text, f"baseline evidence {key} excerpt not found in source")
        require(non_empty_string(item["interpretation"]), f"baseline evidence {key} interpretation is empty")
        if key != "activation_decision":
            interpretation = f" {item['interpretation'].lower()} "
            require(
                isinstance(item["supports_observation"], bool),
                f"baseline evidence {key} supports_observation must be bool",
            )
            require(
                item["supports_observation"] == observations[key],
                f"baseline evidence {key} support contradicts observation value",
            )
            if item["supports_observation"]:
                require(
                    not any(term in interpretation for term in CONTRADICTORY_SUPPORT_TERMS),
                    f"baseline evidence {key} interpretation contradicts positive support",
                )
                require(
                    any(term in interpretation for term in POSITIVE_SUPPORT_TERMS),
                    f"baseline evidence {key} interpretation does not explain positive support",
                )
                require(
                    interpretation_mentions_observation(key, item["interpretation"]),
                    f"baseline evidence {key} interpretation omits the observation topic",
                )
            else:
                require(
                    interpretation.strip().startswith("does not support"),
                    f"baseline evidence {key} interpretation contradicts negative support",
                )
                require(
                    interpretation_mentions_observation(key, item["interpretation"]),
                    f"baseline evidence {key} interpretation omits the observation topic",
                )
        else:
            require(
                interpretation_mentions_observation(key, item["interpretation"]),
                "baseline evidence activation_decision interpretation omits the observation topic",
            )
            require(
                activation_interpretation_is_meaningful(item["interpretation"]),
                "baseline evidence activation_decision interpretation lacks evidence action",
            )
            require(
                item["activation_support"] in {"activate", "downgrade", "ambiguous"},
                "baseline evidence activation_decision support is invalid",
            )
            require(
                item["activation_support"] == observations[key],
                "baseline evidence activation_decision support contradicts observation value",
            )

    observed_decision = observations["activation_decision"]
    require(observed_decision in {"activate", "downgrade", "ambiguous"}, "invalid baseline activation decision")
    if observed_decision == expected["activation"]:
        activation_score = 2
    elif observed_decision == "ambiguous":
        activation_score = 1
    else:
        activation_score = 0
    return {
        "activation_discipline": activation_score,
        "executable_artifact": 0,
        "handoff_clarity": 1 if observations["handoff_guidance"] else 0,
        "verification_strength": 1 if observations["verification_guidance"] else 0,
        "safety_gating": 2 if observations["safety_gates"] else 0,
        "resume_value": 1 if observations["resume_guidance"] else 0,
        "downstream_consumer_success": 1 if observations["consumer_can_route"] else 0,
    }


def load_baseline(
    entry: dict[str, Any],
    fixture_id: str,
    prompt_text: str,
    expected: dict[str, Any],
) -> dict[str, Any]:
    require_keys(entry, ["name", "source_path", "fixture_records"], "baseline manifest entry")
    name = entry["name"]
    source_path = ROOT / entry["source_path"]
    require(source_path.exists(), f"baseline source not found: {entry['source_path']}")
    source_text = source_path.read_text()
    fixture_records = entry.get("fixture_records")
    require(isinstance(fixture_records, dict), f"baseline {name} must use fixture_records")
    require(fixture_id in fixture_records, f"baseline {name} missing fixture record for {fixture_id}")
    record = fixture_records[fixture_id]
    require(isinstance(record, dict), f"baseline {name} fixture record must be an object")
    if record.get("normalized_plan"):
        raise EvaluationError("V0.5 baseline records must use source-hashed normalization_failure records")
    if record.get("normalization_failure"):
        require_keys(record, ["normalization_failure"], f"baseline {name} fixture record {fixture_id}")
        failure_path = ROOT / record["normalization_failure"]
        failure = read_json(failure_path)
        require(failure.get("baseline") == name, f"{failure_path} baseline mismatch")
        require(failure.get("fixture_id") == fixture_id, f"{failure_path} fixture mismatch")
        require(failure.get("prompt") == prompt_text, f"{failure_path} prompt mismatch")
        require(failure.get("source_sha256") == hash_file(source_path), f"{failure_path} source hash mismatch")
        scores = score_baseline_failure(failure, expected, source_text)
        return {
            "name": name,
            "normalized": False,
            "artifact_path": None,
            "normalization_failure": rel(failure_path),
            "reason": failure.get("reason", ""),
            "scores": scores,
        }
    raise EvaluationError(f"baseline {name} lacks normalized_plan or normalization_failure for {fixture_id}")


def validate_raw_output(
    raw_path: Path,
    plan_path: Path,
    plan: dict[str, Any],
    fixture_id: str,
    prompt_text: str,
    skill_hash: str,
) -> str:
    raw_text = raw_path.read_text()
    plan_text = plan_path.read_text()
    require(raw_text != plan_text, f"{fixture_id} raw output duplicates parsed plan")
    raw = read_json(raw_path)
    require_keys(
        raw,
        [
            "raw_kind",
            "fixture_id",
            "source_prompt",
            "producer",
            "skill_sha256",
            "rendered_blueprint",
            "workflow_plan",
            "packet_sha256",
        ],
        f"{fixture_id} raw output",
    )
    require(raw.get("fixture_id") == fixture_id, f"{fixture_id} raw output fixture mismatch")
    require(raw.get("source_prompt") == prompt_text, f"{fixture_id} raw output prompt mismatch")
    require(raw.get("raw_kind") == "workflow-output", f"{fixture_id} raw output has wrong kind")
    require(raw.get("producer") == CREATED_BY, f"{fixture_id} raw output producer mismatch")
    require(raw.get("skill_sha256") == skill_hash, f"{fixture_id} raw output skill hash mismatch")
    require(raw.get("workflow_plan") == plan, f"{fixture_id} raw output does not contain parsed plan")
    require(raw.get("rendered_blueprint") == render_blueprint(plan), f"{fixture_id} raw blueprint drift")
    require(raw.get("packet_sha256") == packet_hashes(plan), f"{fixture_id} raw packet hashes drift")
    return raw_text


def validate_consumer_report(
    report_path: Path,
    plan: dict[str, Any],
    expected: dict[str, Any],
) -> int:
    report = read_json(report_path)
    common_keys = {
        "fixture_id",
        "consumer_verdict",
        "received_spec_or_expected_answer",
        "blinded_inputs",
        "first_slice",
        "inputs_needed",
        "expected_output",
        "completion_check",
        "forbidden_actions_identified",
        "risk_gates_identified",
        "safe_defaults_identified",
        "provenance",
    }
    allowed_keys = set(common_keys)
    if plan["activation"]["decision"] == "downgrade":
        allowed_keys.add("agreed_downgrade_target")
    extra = set(report) - allowed_keys
    require(not extra, f"{report_path} contains unexpected consumer fields: {sorted(extra)}")
    require(report.get("fixture_id") == plan["plan_id"], f"{report_path} fixture mismatch")
    require(report.get("consumer_verdict") == "pass", f"{report_path} consumer did not pass")
    require(report.get("received_spec_or_expected_answer") is False, f"{report_path} is not blinded")
    blinded_inputs = report.get("blinded_inputs")
    require(isinstance(blinded_inputs, list), f"{report_path} blinded_inputs must be a list")
    require(unique_list(blinded_inputs), f"{report_path} blinded_inputs must be unique")
    require(set(blinded_inputs) <= ALLOWED_BLINDED_INPUTS, f"{report_path} has forbidden blinded inputs")
    require({"workflow.plan.json", "blueprint.md", "original prompt"} <= set(blinded_inputs), f"{report_path} missing required blinded inputs")
    repo_bound = any(surface["kind"] == "repo" for surface in plan["surfaces"]) or bool(
        expected.get("requires_repository_path")
    )
    if repo_bound:
        require("repository path" in blinded_inputs, f"{report_path} missing repository path for repo-bound plan")
    else:
        require("repository path" not in blinded_inputs, f"{report_path} includes repository path for non-repo plan")
    first_slice = plan["execution_path"]["first_slice"]
    require(report.get("first_slice") == first_slice["instruction"], f"{report_path} first slice mismatch")
    require(same_items(report.get("inputs_needed"), first_slice["inputs"]), f"{report_path} inputs mismatch")
    require(isinstance(report.get("inputs_needed"), list) and unique_list(report["inputs_needed"]), f"{report_path} inputs_needed must be unique")
    require(set(first_slice["inputs"]) <= set(blinded_inputs), f"{report_path} first-slice inputs not available to consumer")
    require(report.get("expected_output") == first_slice["expected_output"], f"{report_path} expected output mismatch")
    require(report.get("completion_check") == first_slice["completion_check"], f"{report_path} completion check mismatch")
    require(
        same_items(report.get("forbidden_actions_identified"), first_slice["forbidden_actions"]),
        f"{report_path} forbidden actions mismatch",
    )
    require(
        isinstance(report.get("forbidden_actions_identified"), list) and unique_list(report["forbidden_actions_identified"]),
        f"{report_path} forbidden actions must be unique",
    )
    require(
        same_items(report.get("risk_gates_identified"), [gate["trigger"] for gate in plan["risk_gates"]]),
        f"{report_path} risk gates mismatch",
    )
    require(
        isinstance(report.get("risk_gates_identified"), list) and unique_list(report["risk_gates_identified"]),
        f"{report_path} risk gates must be unique",
    )
    require(
        report.get("safe_defaults_identified") == {
            gate["trigger"]: gate["safe_default"] for gate in plan["risk_gates"]
        },
        f"{report_path} safe defaults mismatch",
    )
    if plan["activation"]["decision"] == "downgrade":
        require(
            report.get("agreed_downgrade_target") == expected.get("downgrade_target"),
            f"{report_path} downgrade target disagreement",
        )
    provenance = report.get("provenance")
    require(isinstance(provenance, dict), f"{report_path} provenance must be an object")
    allowed_provenance_keys = {
        "run_kind",
        "supplied_inputs",
        "transcript_excerpt",
        "reviewer_note",
        "field_support",
        "packet_sha256",
    }
    extra_provenance = set(provenance) - allowed_provenance_keys
    require(not extra_provenance, f"{report_path} provenance contains unexpected fields: {sorted(extra_provenance)}")
    require_keys(
        provenance,
        ["run_kind", "supplied_inputs", "transcript_excerpt", "reviewer_note", "field_support", "packet_sha256"],
        f"{report_path} provenance",
    )
    require(provenance["run_kind"] == "blinded-sample-review", f"{report_path} has wrong consumer run kind")
    require(same_items(provenance["supplied_inputs"], blinded_inputs), f"{report_path} provenance inputs mismatch")
    require(provenance["packet_sha256"] == packet_hashes(plan), f"{report_path} provenance packet hashes drift")
    require(non_empty_string(provenance["transcript_excerpt"]), f"{report_path} transcript excerpt is empty")
    require(first_slice["instruction"] in provenance["transcript_excerpt"], f"{report_path} transcript omits first slice")
    require(non_empty_string(provenance["reviewer_note"]), f"{report_path} reviewer note is empty")
    forbid_provenance_leaks(provenance["transcript_excerpt"], f"{report_path} transcript")
    forbid_provenance_leaks(provenance["reviewer_note"], f"{report_path} reviewer note")
    field_support = provenance["field_support"]
    require(isinstance(field_support, dict), f"{report_path} field_support must be an object")
    required_support = [
        "first_slice",
        "inputs_needed",
        "expected_output",
        "completion_check",
        "forbidden_actions",
        "risk_gates",
        "safe_defaults",
    ]
    if plan["activation"]["decision"] == "downgrade":
        required_support.append("downgrade_target")
    require_keys(field_support, required_support, f"{report_path} field_support")
    extra_support = set(field_support) - set(required_support)
    require(not extra_support, f"{report_path} field_support contains unexpected fields: {sorted(extra_support)}")

    def require_support(field: str, values: list[str]) -> None:
        support = field_support[field]
        require(non_empty_string(support), f"{report_path} support for {field} is empty")
        forbid_provenance_leaks(support, f"{report_path} support for {field}")
        for value in values:
            require(str(value) in support, f"{report_path} support for {field} omits {value}")

    require_support("first_slice", [first_slice["instruction"]])
    require_support("inputs_needed", list(first_slice["inputs"]))
    require_support("expected_output", [first_slice["expected_output"]])
    require_support("completion_check", [first_slice["completion_check"]])
    require_support("forbidden_actions", list(first_slice["forbidden_actions"]))
    require_support("risk_gates", [gate["trigger"] for gate in plan["risk_gates"]])
    safe_default_values: list[str] = []
    for gate in plan["risk_gates"]:
        safe_default_values.extend([gate["trigger"], gate["safe_default"]])
    require_support("safe_defaults", safe_default_values)
    if plan["activation"]["decision"] == "downgrade":
        require_support("downgrade_target", [str(expected.get("downgrade_target"))])
    return 2


def average(scores: dict[str, int], metrics: list[str]) -> float:
    return sum(scores[metric] for metric in metrics) / len(metrics)


def validate_decision_doc(summary: dict[str, Any], decision_path: Path | None = None) -> None:
    decision_path = ROOT / "docs" / "v0.5-decision.md" if decision_path is None else decision_path
    raw_text = decision_path.read_text()
    text = " ".join(raw_text.lower().split())
    clauses = [
        " ".join(clause.split())
        for sentence in re.split(r"(?<=[.!?])\s+", raw_text.lower())
        for clause in re.split(r"\b(?:but|however|though|although|yet)\b|[,;:]", sentence)
    ]
    allowed_negated_boundary_claims = [
        r"\bdoes not claim runtime execution(?: or live model generation)?(?: from `?skill\.md`?)?",
        r"\bdoes not claim live model generation(?: from `?skill\.md`?)?",
        r"\bdoes not claim fresh baseline execution\b",
        r"\bdoes not use runtime-backed evidence(?: from sibling baselines)?\b",
        r"\bwithout runtime-backed evidence\b",
        r"\bnever reran the baseline\b",
        r"\bdid not rerun the baseline\b",
        r"\bdoes not rerun the baseline\b",
        r"\bdo not rerun the baseline\b",
    ]
    forbidden_boundary_claims = [
        r"\bfresh baseline re-execution\b",
        r"\bfreshly rechecked\b.{0,120}\bsibling baseline\b",
        r"\bfresh rerun\b.{0,120}\b(peer|sibling) baselines?\b",
        r"\bfreshly rerun\b.{0,120}\b(peer|sibling) baselines?\b",
        r"\bbaseline re-execution\b",
        r"\breran the baseline\b",
        r"\blive source\b",
        r"\bruntime evidence\b",
        r"\bruntime-backed evidence\b",
        r"\bcompar(?:es|ing)\b.{0,120}\bsibling baselines live\b",
        r"\bcompar(?:es|ing)\b.{0,120}\bfreshly rerun\b.{0,120}\bsibling baselines\b",
        r"\bbaseline skills?\b.{0,120}\brerun live\b",
        r"\blive\b.{0,120}\bfor this gate\b",
        r"\brer(?:un|an) live\b",
        r"\bdoes claim fresh baseline execution\b",
        r"\bdoes claim\b.{0,120}\blive sibling-baseline comparison\b",
        r"\bclaims fresh baseline execution\b",
        r"\bclaims\b.{0,120}\blive sibling-baseline comparison\b",
        r"\bclaims runtime execution\b",
        r"\bclaims live model generation\b",
    ]
    for clause in clauses:
        scan_clause = clause.replace("not only", "")
        for allowed_pattern in allowed_negated_boundary_claims:
            scan_clause = re.sub(allowed_pattern, "", scan_clause)
        for pattern in forbidden_boundary_claims:
            require(
                not re.search(pattern, scan_clause),
                "docs/v0.5-decision.md contains contradictory boundary claim",
            )

    decisions = re.findall(r"(?i)\bdecision:\s*([a-z0-9-]+)\b", raw_text)
    require(decisions == [summary["decision"]], "docs/v0.5-decision.md has contradictory decision values")

    fixture_matches = re.findall(r"(?i)(\d+)\s+fixtures evaluated\.", raw_text)
    require(
        fixture_matches == [str(summary["fixture_count"])],
        "docs/v0.5-decision.md fixture count does not match generated summary",
    )

    candidate_matches = re.findall(r"(?i)candidate keep/kill average:\s*([0-9.]+)\.", raw_text)
    require(
        candidate_matches == [str(summary["candidate_keep_kill_average"])],
        "docs/v0.5-decision.md candidate average does not match generated summary",
    )
    for name, value in summary["baseline_keep_kill_averages"].items():
        pattern = rf"(?i)`{re.escape(name)}` baseline average:\s*([0-9.]+)\."
        matches = re.findall(pattern, raw_text)
        require(
            matches == [str(value)],
            f"docs/v0.5-decision.md baseline average mismatch for {name}",
        )
    require("aggregate keep/kill average" in text, "docs/v0.5-decision.md omits aggregate average boundary")
    margin = (summary["candidate_keep_kill_average"] / max(summary["baseline_keep_kill_averages"].values())) - 1
    claimed_margins = re.findall(r"(?i)(more\s+than|at\s+least)\s+(\d+(?:\.\d+)?)\s+percent", raw_text)
    require(claimed_margins, "docs/v0.5-decision.md omits measured margin claim")
    for comparator, claimed_margin in claimed_margins:
        claimed = float(claimed_margin) / 100
        if comparator.lower().startswith("more"):
            require(claimed < margin, "docs/v0.5-decision.md overstates aggregate keep/kill margin")
        else:
            require(claimed <= margin + 1e-12, "docs/v0.5-decision.md overstates aggregate keep/kill margin")
    if "per-metric margin" in text:
        require(
            "does not claim a per-metric margin" in text,
            "docs/v0.5-decision.md contains unsupported per-metric margin claim",
        )
    required_claims = [
        "Four positive fixtures activate.",
        "Four negative fixtures downgrade.",
        "Three borderline fixtures downgrade to `workflow-router`.",
        "The meta/runtime fixture activates to a backlog-oriented execution path.",
        "Every fixture has a schema-valid artifact or valid downgrade artifact.",
        "`workflow-router-skill`: source-hashed normalization failure",
        "`claude-agent-workflow-designer`: source-hashed normalization failure",
        "not a live blinded-review runner",
        "does not claim runtime execution or live model generation",
        "does not claim fresh baseline execution",
    ]
    for claim in required_claims:
        normalized_claim = " ".join(claim.lower().split())
        require(
            normalized_claim in text,
            f"docs/v0.5-decision.md omits required claim: {claim}",
        )


def evaluate_fixture(
    fixture: dict[str, Any],
    baselines: list[dict[str, Any]],
    out_root: Path,
    skill_hash: str,
) -> dict[str, Any]:
    fixture_id = fixture["id"]
    expected = dict(fixture["expected"])
    expected["fixture_category"] = fixture["category"]
    plan_path = ROOT / fixture["candidate_plan"]
    prompt_path = ROOT / fixture["prompt_path"]
    raw_path = ROOT / fixture["raw_output"]
    consumer_path = ROOT / fixture["consumer_report"]
    prompt_text = prompt_path.read_text().strip()
    plan = read_json(plan_path)
    require(plan.get("plan_id") == fixture_id, f"{fixture_id} candidate plan_id must match manifest id")
    validate_plan(plan, expected)
    raw_text = validate_raw_output(raw_path, plan_path, plan, fixture_id, prompt_text, skill_hash)
    require(
        plan["source_prompt"].strip() == prompt_text,
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
        load_baseline(baseline, fixture_id, prompt_text, expected)
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
    scorecard["consumer_report"] = fixture["consumer_report"]
    scorecard["consumer_report_sha256"] = hash_file(consumer_path)
    write_json(fixture_out / "scorecard.json", scorecard)
    return scorecard


def evaluate_manifest(manifest_path: Path, out_root: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    require_keys(manifest, ["schema_version", "fixtures", "baselines"], "manifest")
    require(manifest["schema_version"] == SCHEMA_VERSION, "manifest schema_version mismatch")
    require(isinstance(manifest["fixtures"], list) and manifest["fixtures"], "manifest fixtures must be non-empty")
    require(isinstance(manifest["baselines"], list) and manifest["baselines"], "manifest baselines must be non-empty")
    fixture_ids = [fixture["id"] for fixture in manifest["fixtures"]]
    require(len(fixture_ids) == len(set(fixture_ids)), "manifest fixture ids must be unique")
    raw_baseline_names = [baseline.get("name") for baseline in manifest["baselines"]]
    require(len(raw_baseline_names) == len(set(raw_baseline_names)), "manifest baseline names must be unique")
    baseline_names = set(raw_baseline_names)
    require(len(raw_baseline_names) == len(EXPECTED_BASELINES), "manifest must contain exactly the expected baselines")
    require(baseline_names == EXPECTED_BASELINES, f"manifest baselines must be {sorted(EXPECTED_BASELINES)}")
    for baseline in manifest["baselines"]:
        require_keys(baseline, ["name", "source_path", "fixture_records"], "baseline manifest entry")
        fixture_records = baseline.get("fixture_records")
        require(isinstance(fixture_records, dict), f"baseline {baseline.get('name')} must use fixture_records")
        missing = [fixture_id for fixture_id in fixture_ids if fixture_id not in fixture_records]
        require(not missing, f"baseline {baseline.get('name')} missing fixture records: {missing}")
        extra = sorted(set(fixture_records) - set(fixture_ids))
        require(not extra, f"baseline {baseline.get('name')} has unknown fixture records: {extra}")
        for fixture_id, record in fixture_records.items():
            require(isinstance(record, dict), f"baseline {baseline.get('name')} fixture record {fixture_id} must be an object")
            require_keys(record, ["normalization_failure"], f"baseline {baseline.get('name')} fixture record {fixture_id}")
    expected_baseline_paths = {
        record["normalization_failure"]
        for baseline in manifest["baselines"]
        for record in baseline["fixture_records"].values()
    }
    actual_baseline_paths = {
        rel(path)
        for path in sorted((ROOT / "samples" / "v0.5" / "baselines").glob("*/*.normalization-failure.json"))
    }
    require(expected_baseline_paths == actual_baseline_paths, "manifest baseline records must match tracked baseline corpus")
    fixture_keys = [
        "id",
        "category",
        "prompt_path",
        "candidate_plan",
        "raw_output",
        "consumer_report",
        "expected",
    ]
    for fixture in manifest["fixtures"]:
        validate_fixture_manifest_entry(fixture)
    expected_candidate_paths = {fixture["candidate_plan"] for fixture in manifest["fixtures"]}
    expected_raw_paths = {fixture["raw_output"] for fixture in manifest["fixtures"]}
    expected_consumer_paths = {fixture["consumer_report"] for fixture in manifest["fixtures"]}
    actual_candidate_paths = {
        rel(path)
        for path in sorted((ROOT / "samples" / "v0.5" / "candidates").glob("*.workflow.plan.json"))
    }
    actual_raw_paths = {
        rel(path)
        for path in sorted((ROOT / "samples" / "v0.5" / "raw").glob("*.raw-output.json"))
    }
    actual_consumer_paths = {
        rel(path)
        for path in sorted((ROOT / "samples" / "v0.5" / "consumer").glob("*.json"))
    }
    require(expected_candidate_paths == actual_candidate_paths, "manifest candidate paths must match tracked candidate corpus")
    require(expected_raw_paths == actual_raw_paths, "manifest raw-output paths must match tracked raw corpus")
    require(expected_consumer_paths == actual_consumer_paths, "manifest consumer paths must match tracked consumer corpus")
    if out_root.exists():
        shutil.rmtree(out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    skill_hash = hash_file(ROOT / "SKILL.md")
    scorecards = [
        evaluate_fixture(fixture, manifest["baselines"], out_root, skill_hash)
        for fixture in manifest["fixtures"]
    ]
    categories = {card["category"] for card in scorecards}
    require({"positive", "negative", "borderline", "meta"} <= categories, "manifest misses categories")
    require(len(scorecards) == sum(EXPECTED_CATEGORY_COUNTS.values()), "manifest must contain exactly 12 fixtures")
    for category, expected_count in EXPECTED_CATEGORY_COUNTS.items():
        actual_count = sum(1 for card in scorecards if card["category"] == category)
        require(actual_count == expected_count, f"need exactly {expected_count} {category} fixtures")

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
    validate_decision_doc(summary)
    return summary


def validate_fixture_manifest_entry(fixture: dict[str, Any]) -> None:
    fixture_keys = [
        "id",
        "category",
        "prompt_path",
        "candidate_plan",
        "raw_output",
        "consumer_report",
        "expected",
    ]
    expected_keys = [
        "activation",
        "downgrade_target",
        "required_thresholds",
        "required_patterns",
        "forbidden_patterns",
        "required_risk_gates",
        "requires_repository_path",
    ]
    require_keys(fixture, fixture_keys, "manifest fixture")
    require(fixture["category"] in {"positive", "negative", "borderline", "meta"}, f"fixture {fixture['id']} category is invalid")
    id_prefix = fixture["id"].split("-", 1)[0]
    require(
        FIXTURE_ID_CATEGORY_PREFIXES.get(id_prefix) == fixture["category"],
        f"fixture {fixture['id']} category does not match id prefix",
    )
    require(isinstance(fixture["expected"], dict), f"fixture {fixture['id']} expected must be an object")
    require_keys(fixture["expected"], expected_keys, f"fixture {fixture['id']} expected")
    require(fixture["expected"]["activation"] in {"activate", "downgrade"}, f"fixture {fixture['id']} expected.activation is invalid")
    require(isinstance(fixture["expected"]["requires_repository_path"], bool), f"fixture {fixture['id']} expected.requires_repository_path must be bool")
    for key in ["required_thresholds", "required_patterns", "forbidden_patterns", "required_risk_gates"]:
        require(isinstance(fixture["expected"][key], list), f"fixture {fixture['id']} expected.{key} must be a list")
    category_activation, category_downgrade = EXPECTED_CATEGORY_RULES[fixture["category"]]
    require(
        fixture["expected"]["activation"] == category_activation,
        f"fixture {fixture['id']} category contradicts expected.activation",
    )
    if category_downgrade:
        require(
            fixture["expected"]["downgrade_target"] == category_downgrade,
            f"fixture {fixture['id']} category contradicts expected.downgrade_target",
        )
    if fixture["expected"]["activation"] == "activate":
        require(fixture["expected"]["downgrade_target"] is None, f"fixture {fixture['id']} activate expected needs null downgrade_target")
        require(fixture["expected"]["required_thresholds"], f"fixture {fixture['id']} activate expected needs thresholds")
        require(fixture["expected"]["required_patterns"], f"fixture {fixture['id']} activate expected needs patterns")
    else:
        require(fixture["expected"]["downgrade_target"] in DOWNGRADE_TARGETS, f"fixture {fixture['id']} downgrade expected target is invalid")


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
                "safe_default": "stop before writing and ask for approval",
                "requires_user_approval": True,
            },
            {
                "trigger": "shell action",
                "safe_default": "stop before shell use and ask for approval",
                "requires_user_approval": True,
            },
            {
                "trigger": "network action",
                "safe_default": "stop before network use and ask for approval",
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
                "instruction": (
                    "Inspect the prompt and list required inputs."
                    if decision == "activate"
                    else "Use direct-codex instead of dynamic-workflow-designer for this request."
                ),
                "inputs": ["original prompt", "repository path"],
                "expected_output": "input ledger",
                "completion_check": "ledger has inputs",
                "forbidden_actions": ["write files"],
            },
            "consumer": "codex-agent" if decision == "activate" else "human",
        },
    }


def self_test() -> None:
    active = valid_plan_fixture("activate")
    validate_plan(active, {"activation": "activate", "required_thresholds": ["resumable-handoffs"]})
    downgrade = valid_plan_fixture("downgrade")
    validate_plan(downgrade, {"activation": "downgrade", "downgrade_target": "direct-codex"})
    extra_top = json.loads(json.dumps(active))
    extra_top["unexpected_top_level"] = {}
    try:
        validate_plan(extra_top, {"activation": "activate"})
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: unknown top-level field passed")
    extra_nested = json.loads(json.dumps(active))
    extra_nested["activation"]["unexpected"] = True
    try:
        validate_plan(extra_nested, {"activation": "activate"})
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: unknown nested field passed")
    bad_activation = json.loads(json.dumps(active))
    bad_activation["activation"]["matched_thresholds"].append("totally-made-up-threshold")
    try:
        validate_plan(bad_activation, {"activation": "activate"})
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: unknown activation threshold passed")
    bad_activation = json.loads(json.dumps(active))
    bad_activation["activation"]["matched_thresholds"].append("resumable-handoffs")
    try:
        validate_plan(bad_activation, {"activation": "activate"})
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: duplicate activation threshold passed")
    bad_activation = json.loads(json.dumps(downgrade))
    bad_activation["activation"]["matched_thresholds"] = ["resumable-handoffs", "adversarial-verification"]
    try:
        validate_plan(bad_activation, {"activation": "downgrade", "downgrade_target": "direct-codex"})
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: activation-grade downgrade thresholds passed")
    for threshold in ["multi-surface-fanout", "adversarial-verification"]:
        bad_activation = json.loads(json.dumps(downgrade))
        bad_activation["activation"]["matched_thresholds"] = [threshold]
        try:
            validate_plan(bad_activation, {"activation": "downgrade", "downgrade_target": "direct-codex"})
        except EvaluationError:
            pass
        else:
            raise EvaluationError("self-test failed: single activation threshold on downgrade passed")

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
    bad = json.loads(json.dumps(active))
    bad["patterns"] = []
    try:
        validate_plan(bad, {"activation": "activate"})
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: empty activated patterns passed")

    bad_worker = json.loads(json.dumps(active))
    bad_worker["workers"][0]["tool_permissions"]["shell"] = "false"
    try:
        validate_plan(bad_worker, {"activation": "activate"})
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: non-boolean tool permission passed")
    bad_worker = json.loads(json.dumps(active))
    bad_worker["workers"][0]["tool_permissions"]["requires_escalation_for"] = ["totally-made-up-capability"]
    bad_worker["risk_gates"].append(
        {
            "trigger": "totally made up capability",
            "safe_default": "stop before made up capability and ask for approval",
            "requires_user_approval": True,
        }
    )
    try:
        validate_plan(bad_worker, {"activation": "activate"})
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: unknown escalation target passed")
    for field in ["forbidden_actions", "ownership"]:
        bad_worker = json.loads(json.dumps(active))
        bad_worker["workers"][0][field] = []
        try:
            validate_plan(bad_worker, {"activation": "activate"})
        except EvaluationError:
            pass
        else:
            raise EvaluationError(f"self-test failed: empty worker {field} passed")
    bad_worker = json.loads(json.dumps(active))
    bad_worker["workers"][0]["context_budget"]["must_include"] = []
    try:
        validate_plan(bad_worker, {"activation": "activate"})
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: empty worker must_include passed")
    bad_worker = json.loads(json.dumps(active))
    bad_worker["workers"].append(json.loads(json.dumps(active["workers"][0])))
    try:
        validate_plan(bad_worker, {"activation": "activate"})
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: duplicate worker id passed")

    bad_gate = json.loads(json.dumps(active))
    bad_gate["risk_gates"] = []
    try:
        validate_plan(bad_gate, {"activation": "activate"})
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: empty safe default passed")
    bad_gate = json.loads(json.dumps(active))
    bad_gate["risk_gates"][0]["requires_user_approval"] = False
    try:
        validate_plan(bad_gate, {"activation": "activate"})
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: non-approving risk gate passed")
    bad_gate = json.loads(json.dumps(active))
    bad_gate["risk_gates"] = [
        {
            "trigger": "rewrite shellac networking note",
            "safe_default": "stop and ask",
            "requires_user_approval": True,
        }
    ]
    try:
        validate_plan(bad_gate, {"activation": "activate"})
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: substring-spoofed risk gate passed")
    bad_gate = json.loads(json.dumps(active))
    bad_gate["risk_gates"][0]["safe_default"] = "preserve evidence, then continue with the write"
    try:
        validate_plan(bad_gate, {"activation": "activate"})
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: unsafe continue safe_default passed")
    for unsafe_default in [
        "ask before writing, preserve evidence, then write files",
        "ask before shell use, stop for approval, then run the shell command",
        "stop before writing and ask for approval, otherwise write files",
        "do not write without approval; write files afterward",
        "preserve evidence and ask before writing, then delete files",
        "preserve context and ask before network use, then send the request",
        "preserve logs and ask before editing files or running shell commands",
        "stop before editing files / running shell commands and ask for approval",
    ]:
        bad_gate = json.loads(json.dumps(active))
        bad_gate["risk_gates"][0]["safe_default"] = unsafe_default
        try:
            validate_plan(bad_gate, {"activation": "activate"})
        except EvaluationError:
            pass
        else:
            raise EvaluationError(f"self-test failed: unsafe safe_default passed: {unsafe_default}")

    valid_report = {
        "fixture_id": active["plan_id"],
        "consumer_verdict": "pass",
        "received_spec_or_expected_answer": False,
        "blinded_inputs": ["workflow.plan.json", "blueprint.md", "original prompt", "repository path"],
        "first_slice": active["execution_path"]["first_slice"]["instruction"],
        "inputs_needed": ["original prompt", "repository path"],
        "expected_output": active["execution_path"]["first_slice"]["expected_output"],
        "completion_check": active["execution_path"]["first_slice"]["completion_check"],
        "forbidden_actions_identified": ["write files"],
        "risk_gates_identified": ["write action", "shell action", "network action"],
        "safe_defaults_identified": {
            "write action": "stop before writing and ask for approval",
            "shell action": "stop before shell use and ask for approval",
            "network action": "stop before network use and ask for approval",
        },
        "provenance": {
            "run_kind": "blinded-sample-review",
            "supplied_inputs": ["workflow.plan.json", "blueprint.md", "original prompt", "repository path"],
            "packet_sha256": packet_hashes(active),
            "transcript_excerpt": "Consumer selected first slice: Inspect the prompt and list required inputs.",
            "reviewer_note": "Inputs and gates were identified from the blinded packet.",
            "field_support": {
                "first_slice": "first_slice: Inspect the prompt and list required inputs.",
                "inputs_needed": "inputs_needed: original prompt; repository path",
                "expected_output": "expected_output: input ledger",
                "completion_check": "completion_check: ledger has inputs",
                "forbidden_actions": "forbidden_actions: write files",
                "risk_gates": "risk_gates: write action; shell action; network action",
                "safe_defaults": (
                    "safe_defaults: write action -> stop before writing and ask for approval; "
                    "shell action -> stop before shell use and ask for approval; "
                    "network action -> stop before network use and ask for approval"
                ),
            },
        },
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
    bad_report = dict(valid_report)
    bad_report["blinded_inputs"] = ["workflow.plan.json", "blueprint.md", "original prompt", "expected answers"]
    write_json(tmp_report, bad_report)
    try:
        validate_consumer_report(tmp_report, active, {"activation": "activate"})
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: forbidden blinded input passed")
    bad_report = dict(valid_report)
    bad_report["inputs_needed"] = ["wrong input"]
    write_json(tmp_report, bad_report)
    try:
        validate_consumer_report(tmp_report, active, {"activation": "activate"})
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: wrong consumer inputs passed")
    bad_report = json.loads(json.dumps(valid_report))
    bad_report["inputs_needed"] = ["original prompt", "repository path", "repository path"]
    write_json(tmp_report, bad_report)
    try:
        validate_consumer_report(tmp_report, active, {"activation": "activate"})
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: duplicate consumer inputs passed")
    bad_report = json.loads(json.dumps(valid_report))
    bad_report["risk_gates_identified"] = ["write action", "shell action", "network action", "write action"]
    write_json(tmp_report, bad_report)
    try:
        validate_consumer_report(tmp_report, active, {"activation": "activate"})
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: duplicate consumer risk gates passed")
    bad_report = dict(valid_report)
    bad_report["expected_answer"] = "leak"
    write_json(tmp_report, bad_report)
    try:
        validate_consumer_report(tmp_report, active, {"activation": "activate"})
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: unexpected consumer leakage field passed")
    bad_report = json.loads(json.dumps(valid_report))
    bad_report["provenance"]["transcript_excerpt"] = "No first slice here."
    write_json(tmp_report, bad_report)
    try:
        validate_consumer_report(tmp_report, active, {"activation": "activate"})
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: consumer report without transcript evidence passed")
    bad_report = json.loads(json.dumps(valid_report))
    bad_report["provenance"]["expected_answer"] = "leak"
    write_json(tmp_report, bad_report)
    try:
        validate_consumer_report(tmp_report, active, {"activation": "activate"})
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: nested consumer leakage field passed")
    bad_report = json.loads(json.dumps(valid_report))
    bad_report["provenance"]["reviewer_note"] = "I used docs/spec expected answer."
    write_json(tmp_report, bad_report)
    try:
        validate_consumer_report(tmp_report, active, {"activation": "activate"})
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: consumer provenance source leak passed")
    bad_report = json.loads(json.dumps(valid_report))
    bad_report["provenance"]["reviewer_note"] = "I had the gold answer in a separate note while reviewing."
    write_json(tmp_report, bad_report)
    try:
        validate_consumer_report(tmp_report, active, {"activation": "activate"})
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: gold-answer consumer provenance leak passed")
    bad_report = json.loads(json.dumps(valid_report))
    bad_report["provenance"]["reviewer_note"] = "Reviewed against the ground truth rubric before marking pass."
    write_json(tmp_report, bad_report)
    try:
        validate_consumer_report(tmp_report, active, {"activation": "activate"})
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: ground-truth consumer provenance leak passed")
    for note in [
        "I had the solution key while reviewing.",
        "A cheat sheet was available during review.",
        "I reviewed the author commentary before deciding pass.",
    ]:
        bad_report = json.loads(json.dumps(valid_report))
        bad_report["provenance"]["reviewer_note"] = note
        write_json(tmp_report, bad_report)
        try:
            validate_consumer_report(tmp_report, active, {"activation": "activate"})
        except EvaluationError:
            pass
        else:
            raise EvaluationError("self-test failed: consumer provenance synonym leak passed")
    bad_report = json.loads(json.dumps(valid_report))
    bad_report["provenance"]["field_support"]["safe_defaults"] += "; docs / spec"
    write_json(tmp_report, bad_report)
    try:
        validate_consumer_report(tmp_report, active, {"activation": "activate"})
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: spaced provenance source leak passed")
    bad_report = json.loads(json.dumps(valid_report))
    bad_report["provenance"]["field_support"]["safe_defaults"] += "; score-card"
    write_json(tmp_report, bad_report)
    try:
        validate_consumer_report(tmp_report, active, {"activation": "activate"})
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: hyphenated provenance source leak passed")
    bad_report = json.loads(json.dumps(valid_report))
    bad_report["provenance"]["field_support"]["safe_defaults"] += "; score/card"
    write_json(tmp_report, bad_report)
    try:
        validate_consumer_report(tmp_report, active, {"activation": "activate"})
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: slashed provenance source leak passed")
    bad_report = json.loads(json.dumps(valid_report))
    bad_report["provenance"]["field_support"]["safe_defaults"] += "; sc0recard"
    write_json(tmp_report, bad_report)
    try:
        validate_consumer_report(tmp_report, active, {"activation": "activate"})
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: obfuscated provenance source leak passed")
    repo_report = json.loads(json.dumps(valid_report))
    repo_report["blinded_inputs"] = ["workflow.plan.json", "blueprint.md", "original prompt"]
    repo_report["provenance"]["supplied_inputs"] = ["workflow.plan.json", "blueprint.md", "original prompt"]
    repo_plan = json.loads(json.dumps(active))
    write_json(tmp_report, repo_report)
    try:
        validate_consumer_report(tmp_report, repo_plan, {"activation": "activate"})
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: repo-bound consumer without repository path passed")
    manifest_repo_report = json.loads(json.dumps(valid_report))
    manifest_repo_report["blinded_inputs"] = ["workflow.plan.json", "blueprint.md", "original prompt"]
    manifest_repo_report["inputs_needed"] = ["original prompt"]
    manifest_repo_report["provenance"]["supplied_inputs"] = ["workflow.plan.json", "blueprint.md", "original prompt"]
    manifest_repo_report["provenance"]["field_support"]["inputs_needed"] = "inputs_needed: original prompt"
    manifest_repo_plan = json.loads(json.dumps(active))
    manifest_repo_plan["surfaces"][0]["kind"] = "web-source"
    manifest_repo_plan["execution_path"]["first_slice"]["inputs"] = ["original prompt"]
    write_json(tmp_report, manifest_repo_report)
    try:
        validate_consumer_report(
            tmp_report,
            manifest_repo_plan,
            {"activation": "activate", "requires_repository_path": True},
        )
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: expected repo-bound consumer without repository path passed")
    non_repo_report = json.loads(json.dumps(valid_report))
    non_repo_plan = json.loads(json.dumps(active))
    non_repo_plan["surfaces"][0]["kind"] = "web-source"
    non_repo_plan["execution_path"]["first_slice"]["inputs"] = ["original prompt"]
    write_json(tmp_report, non_repo_report)
    try:
        validate_consumer_report(tmp_report, non_repo_plan, {"activation": "activate"})
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: non-repo consumer with repository path passed")
    bad_report = json.loads(json.dumps(valid_report))
    bad_report["provenance"]["field_support"]["risk_gates"] = "risk_gates omitted"
    write_json(tmp_report, bad_report)
    try:
        validate_consumer_report(tmp_report, active, {"activation": "activate"})
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: unsupported consumer risk gates passed")
    tmp_report.unlink(missing_ok=True)

    tmp_plan = ROOT / "out" / "v0.5-self-test-plan.json"
    tmp_raw = ROOT / "out" / "v0.5-self-test-raw.json"
    write_json(tmp_plan, active)
    write_json(tmp_raw, active)
    try:
        validate_raw_output(tmp_raw, tmp_plan, active, active["plan_id"], active["source_prompt"], "self-test-hash")
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: duplicated raw output passed")
    write_json(
        tmp_raw,
        {
            "raw_kind": "workflow-output",
            "fixture_id": active["plan_id"],
            "source_prompt": active["source_prompt"],
            "producer": CREATED_BY,
            "skill_sha256": "self-test-hash",
            "rendered_blueprint": "stale blueprint",
            "workflow_plan": active,
            "packet_sha256": packet_hashes(active),
        },
    )
    try:
        validate_raw_output(tmp_raw, tmp_plan, active, active["plan_id"], active["source_prompt"], "self-test-hash")
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: stale raw blueprint passed")
    write_json(
        tmp_raw,
        {
            "raw_kind": "workflow-output",
            "fixture_id": active["plan_id"],
            "source_prompt": active["source_prompt"],
            "producer": CREATED_BY,
            "skill_sha256": "self-test-hash",
            "rendered_blueprint": render_blueprint(active),
            "workflow_plan": active,
            "packet_sha256": packet_hashes(active),
        },
    )
    validate_raw_output(tmp_raw, tmp_plan, active, active["plan_id"], active["source_prompt"], "self-test-hash")
    repo_hash_plan = json.loads(json.dumps(active))
    changed_repo_hash_plan = json.loads(json.dumps(active))
    changed_repo_hash_plan["surfaces"][0]["locator"] = "different/repo/path"
    if packet_hashes(repo_hash_plan)["repository surfaces"] == packet_hashes(changed_repo_hash_plan)["repository surfaces"]:
        raise EvaluationError("self-test failed: repository packet hash ignored repo locator")
    raw_with_extra = json.loads(tmp_raw.read_text())
    raw_with_extra["unexpected_raw_field"] = True
    write_json(tmp_raw, raw_with_extra)
    try:
        validate_raw_output(tmp_raw, tmp_plan, active, active["plan_id"], active["source_prompt"], "self-test-hash")
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: raw output extra field passed")
    bad_phase = json.loads(json.dumps(active))
    bad_phase["phases"][0]["depends_on"] = ["missing-phase"]
    try:
        validate_plan(bad_phase, {"activation": "activate"})
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: dangling phase reference passed")
    bad_phase = json.loads(json.dumps(active))
    bad_phase["phases"][0]["depends_on"] = ["inspect"]
    try:
        validate_plan(bad_phase, {"activation": "activate"})
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: cyclic phase graph passed")
    bad_resume = json.loads(json.dumps(active))
    bad_resume["resume"]["cacheable_outputs"] = ["ghost-output"]
    try:
        validate_plan(bad_resume, {"activation": "activate"})
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: unknown cacheable output passed")
    bad_resume = json.loads(json.dumps(active))
    bad_resume["resume"]["invalidators"] = []
    try:
        validate_plan(bad_resume, {"activation": "activate"})
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: empty resume invalidators passed")
    bad_first_slice = json.loads(json.dumps(active))
    bad_first_slice["execution_path"]["first_slice"]["inputs"].append("repository path")
    try:
        validate_plan(bad_first_slice, {"activation": "activate"})
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: duplicate first-slice input passed")
    bad_first_slice = json.loads(json.dumps(downgrade))
    bad_first_slice["execution_path"]["first_slice"]["inputs"] = ["original prompt", "repo root"]
    try:
        validate_plan(bad_first_slice, {"activation": "downgrade", "downgrade_target": "direct-codex"})
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: non-repo first-slice repo alias passed")
    bad_meta = json.loads(json.dumps(active))
    bad_meta["execution_path"]["mode"] = "runtime"
    try:
        validate_plan(bad_meta, {"activation": "activate", "fixture_category": "meta"})
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: meta fixture runtime execution path passed")
    bad_phase = json.loads(json.dumps(active))
    bad_phase["phases"].append(
        {
            "id": "orphan",
            "name": "Orphan",
            "entry_criteria": ["Orphan entry"],
            "exit_criteria": ["Orphan exit"],
            "depends_on": [],
            "worker_ids": ["planner"],
            "outputs": ["orphan-output"],
        }
    )
    try:
        validate_plan(bad_phase, {"activation": "activate"})
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: disconnected active phase passed")
    bad_downgrade = json.loads(json.dumps(downgrade))
    bad_downgrade["workers"] = json.loads(json.dumps(active["workers"]))
    try:
        validate_plan(bad_downgrade, {"activation": "downgrade", "downgrade_target": "direct-codex"})
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: downgrade worker contract passed")
    bad_downgrade = json.loads(json.dumps(downgrade))
    bad_downgrade["execution_path"]["mode"] = "runtime"
    try:
        validate_plan(bad_downgrade, {"activation": "downgrade", "downgrade_target": "direct-codex"})
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: contradictory downgrade execution mode passed")
    bad_downgrade = json.loads(json.dumps(downgrade))
    bad_downgrade["activation"]["downgrade_target"] = "workflow-router"
    bad_downgrade["execution_path"]["first_slice"]["instruction"] = "Use simple-plan instead and produce a minimal checklist."
    try:
        validate_plan(bad_downgrade, {"activation": "downgrade", "downgrade_target": "workflow-router"})
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: contradictory downgrade first slice passed")
    bad_downgrade = json.loads(json.dumps(downgrade))
    bad_downgrade["activation"]["downgrade_target"] = "workflow-router"
    bad_downgrade["execution_path"]["first_slice"]["instruction"] = (
        "Use workflow-router instead of dynamic-workflow-designer, then hand the user a simple-plan checklist."
    )
    try:
        validate_plan(bad_downgrade, {"activation": "downgrade", "downgrade_target": "workflow-router"})
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: mixed downgrade first slice passed")

    source_text = (
        "Classify the task using references/router-map.md.\n"
        "then summarize changed files and verification.\n"
        "Verify with the smallest meaningful command.\n"
        "Pause for explicit confirmation before destructive work.\n"
        "Preserve the strongest evidence gathered before reporting a blocker.\n"
        "choose the route that provides the earliest verifiable evidence.\n"
    )
    fixture_entry = {
        "id": "pos-fixture",
        "category": "positive",
        "prompt_path": "prompt.txt",
        "candidate_plan": "plan.json",
        "raw_output": "raw.json",
        "consumer_report": "consumer.json",
        "expected": {
            "activation": "activate",
            "downgrade_target": None,
            "required_thresholds": ["resumable-handoffs"],
            "required_patterns": ["Sequential"],
            "forbidden_patterns": [],
            "required_risk_gates": ["write"],
            "requires_repository_path": True,
        },
    }
    validate_fixture_manifest_entry(fixture_entry)
    bad_fixture_entry = json.loads(json.dumps(fixture_entry))
    del bad_fixture_entry["expected"]["required_thresholds"]
    try:
        validate_fixture_manifest_entry(bad_fixture_entry)
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: weakened fixture expected block passed")
    bad_fixture_entry = json.loads(json.dumps(fixture_entry))
    bad_fixture_entry["category"] = "surprise"
    try:
        validate_fixture_manifest_entry(bad_fixture_entry)
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: invalid fixture category passed")
    bad_fixture_entry = json.loads(json.dumps(fixture_entry))
    bad_fixture_entry["expected"]["activation"] = "maybe"
    try:
        validate_fixture_manifest_entry(bad_fixture_entry)
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: invalid expected activation passed")
    bad_fixture_entry = json.loads(json.dumps(fixture_entry))
    bad_fixture_entry["category"] = "negative"
    bad_fixture_entry["expected"]["activation"] = "downgrade"
    bad_fixture_entry["expected"]["downgrade_target"] = "direct-codex"
    try:
        validate_fixture_manifest_entry(bad_fixture_entry)
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: fixture category/id mismatch passed")
    bad_fixture_entry = json.loads(json.dumps(fixture_entry))
    bad_fixture_entry["category"] = "borderline"
    bad_fixture_entry["expected"]["activation"] = "downgrade"
    bad_fixture_entry["expected"]["downgrade_target"] = "direct-codex"
    try:
        validate_fixture_manifest_entry(bad_fixture_entry)
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: borderline downgrade target mismatch passed")

    baseline_failure = {
        "baseline": "baseline",
        "fixture_id": active["plan_id"],
        "prompt": active["source_prompt"],
        "adapter_version": BASELINE_ADAPTER_VERSION,
        "source_sha256": "0" * 64,
        "normalization_failure_kind": "no-schema-valid-artifact",
        "normalized": False,
        "reason": "Self-test baseline does not emit workflow.plan.json.",
        "observations": {
            "activation_decision": "ambiguous",
            "handoff_guidance": True,
            "verification_guidance": True,
            "safety_gates": True,
            "resume_guidance": False,
            "consumer_can_route": True,
        },
        "observation_evidence": {
            "activation_decision": {
                "observation": "activation_decision",
                "source_excerpt": "Classify the task using references/router-map.md.",
                "interpretation": "Routes requests but does not decide this fixture's schema activation.",
                "activation_support": "ambiguous",
            },
            "handoff_guidance": {
                "observation": "handoff_guidance",
                "source_excerpt": "then summarize changed files and verification.",
                "interpretation": "Provides handoff or summary guidance for downstream continuation.",
                "supports_observation": True,
            },
            "verification_guidance": {
                "observation": "verification_guidance",
                "source_excerpt": "Verify with the smallest meaningful command.",
                "interpretation": "Mentions verification.",
                "supports_observation": True,
            },
            "safety_gates": {
                "observation": "safety_gates",
                "source_excerpt": "Pause for explicit confirmation before destructive work.",
                "interpretation": "Mentions approval before destructive work.",
                "supports_observation": True,
            },
            "resume_guidance": {
                "observation": "resume_guidance",
                "source_excerpt": "Preserve the strongest evidence gathered before reporting a blocker.",
                "interpretation": "Does not support restartable outputs.",
                "supports_observation": False,
            },
            "consumer_can_route": {
                "observation": "consumer_can_route",
                "source_excerpt": "choose the route that provides the earliest verifiable evidence.",
                "interpretation": "Provides route choice guidance.",
                "supports_observation": True,
            },
        },
    }
    score_baseline_failure(baseline_failure, {"activation": "activate"}, source_text)
    equivalent_baseline_failure = json.loads(json.dumps(baseline_failure))
    equivalent_baseline_failure["observation_evidence"]["activation_decision"]["interpretation"] = (
        "Routes requests, but fails to emit a fixture-specific schema activation artifact."
    )
    score_baseline_failure(equivalent_baseline_failure, {"activation": "activate"}, source_text)
    bad_baseline_failure = json.loads(json.dumps(baseline_failure))
    bad_baseline_failure["observation_evidence"]["activation_decision"]["interpretation"] = "Activation route schema banana."
    try:
        score_baseline_failure(bad_baseline_failure, {"activation": "activate"}, source_text)
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: vacuous baseline activation interpretation passed")
    bad_baseline_failure = json.loads(json.dumps(baseline_failure))
    bad_baseline_failure["observation_evidence"]["activation_decision"]["interpretation"] = "Route only."
    try:
        score_baseline_failure(bad_baseline_failure, {"activation": "activate"}, source_text)
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: actionless baseline activation interpretation passed")
    bad_baseline_failure = json.loads(json.dumps(baseline_failure))
    bad_baseline_failure["observation_evidence"]["activation_decision"]["interpretation"] = "This schema artifact exists."
    try:
        score_baseline_failure(bad_baseline_failure, {"activation": "activate"}, source_text)
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: content-free baseline activation interpretation passed")
    bad_baseline_failure = json.loads(json.dumps(baseline_failure))
    bad_baseline_failure["observation_evidence"]["handoff_guidance"]["interpretation"] = (
        "The handoff guidance capability is absent."
    )
    try:
        score_baseline_failure(bad_baseline_failure, {"activation": "activate"}, source_text)
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: contradictory baseline support passed")
    bad_baseline_failure = json.loads(json.dumps(baseline_failure))
    bad_baseline_failure["observation_evidence"]["handoff_guidance"]["interpretation"] = "banana"
    try:
        score_baseline_failure(bad_baseline_failure, {"activation": "activate"}, source_text)
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: meaningless positive baseline support passed")
    bad_baseline_failure = json.loads(json.dumps(baseline_failure))
    bad_baseline_failure["observations"]["handoff_guidance"] = False
    bad_baseline_failure["observation_evidence"]["handoff_guidance"]["supports_observation"] = False
    bad_baseline_failure["observation_evidence"]["handoff_guidance"]["interpretation"] = (
        "Not missing; provides handoff or summary guidance for downstream continuation."
    )
    try:
        score_baseline_failure(bad_baseline_failure, {"activation": "activate"}, source_text)
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: false baseline observation with positive interpretation passed")
    bad_baseline_failure = json.loads(json.dumps(baseline_failure))
    bad_baseline_failure["observations"]["resume_guidance"] = False
    bad_baseline_failure["observation_evidence"]["resume_guidance"]["supports_observation"] = False
    bad_baseline_failure["observation_evidence"]["resume_guidance"]["interpretation"] = "Does not support banana."
    try:
        score_baseline_failure(bad_baseline_failure, {"activation": "activate"}, source_text)
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: vacuous negative baseline interpretation passed")
    baseline_failure["scores"] = {"activation_discipline": 2}
    try:
        score_baseline_failure(baseline_failure, {"activation": "activate"}, source_text)
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: hand-authored baseline scores passed")
    baseline_failure.pop("scores")
    baseline_failure["unexpected"] = True
    try:
        score_baseline_failure(baseline_failure, {"activation": "activate"}, source_text)
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: baseline extra field passed")
    baseline_failure.pop("unexpected")
    baseline_failure["observation_evidence"]["consumer_can_route"]["source_excerpt"] = "not in source"
    try:
        score_baseline_failure(baseline_failure, {"activation": "activate"}, source_text)
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: unsupported baseline evidence passed")
    baseline_failure["observation_evidence"]["consumer_can_route"]["source_excerpt"] = (
        "choose the route that provides the earliest verifiable evidence."
    )
    normalized_path = ROOT / "out" / "v0.5-self-test-normalized-plan.json"
    write_json(normalized_path, active)
    try:
        load_baseline(
            {
                "name": "workflow-router-skill",
                "source_path": "SKILL.md",
                "fixture_records": {
                    active["plan_id"]: {
                        "normalized_plan": rel(normalized_path),
                        "adapter_version": BASELINE_ADAPTER_VERSION,
                        "source_sha256": hash_file(ROOT / "SKILL.md"),
                        "source_excerpt": "Use this skill to turn a large objective into an executable workflow design.",
                        "interpretation": "Spoofed baseline artifact.",
                    }
                },
            },
            active["plan_id"],
            active["source_prompt"],
            {"activation": "activate"},
        )
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: spoofed normalized baseline passed")
    normalized_path.unlink(missing_ok=True)
    baseline_failure["observation_evidence"]["consumer_can_route"]["source_excerpt"] = "the"
    try:
        score_baseline_failure(baseline_failure, {"activation": "activate"}, source_text)
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: weak one-word baseline evidence passed")
    baseline_failure["observation_evidence"]["consumer_can_route"]["source_excerpt"] = (
        "choose the route that provides the earliest verifiable evidence."
    )
    baseline_failure["observation_evidence"]["consumer_can_route"]["source_excerpt"] = (
        baseline_failure["observation_evidence"]["activation_decision"]["source_excerpt"]
    )
    try:
        score_baseline_failure(baseline_failure, {"activation": "activate"}, source_text)
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: reused baseline evidence passed")

    tmp_manifest = ROOT / "out" / "v0.5-self-test-manifest.json"
    write_json(tmp_manifest, {"fixtures": [], "baselines": []})
    try:
        evaluate_manifest(tmp_manifest, ROOT / "out" / "v0.5-self-test-out")
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: manifest without schema_version passed")
    write_json(tmp_manifest, {"schema_version": SCHEMA_VERSION, "fixtures": [], "baselines": []})
    try:
        evaluate_manifest(tmp_manifest, ROOT / "out" / "v0.5-self-test-out")
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: empty manifest baselines passed")
    duplicate_manifest = {
        "schema_version": SCHEMA_VERSION,
        "fixtures": [{"id": "fixture"}],
        "baselines": [
            {"name": "workflow-router-skill", "source_path": "SKILL.md", "fixture_records": {"fixture": {}}},
            {"name": "workflow-router-skill", "source_path": "SKILL.md", "fixture_records": {"fixture": {}}},
            {"name": "claude-agent-workflow-designer", "source_path": "SKILL.md", "fixture_records": {"fixture": {}}},
        ],
    }
    write_json(tmp_manifest, duplicate_manifest)
    try:
        evaluate_manifest(tmp_manifest, ROOT / "out" / "v0.5-self-test-out")
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: duplicate manifest baselines passed")
    good_summary = {
        "decision": "keep",
        "fixture_count": 12,
        "candidate_keep_kill_average": 1.883,
        "baseline_keep_kill_averages": {
            "workflow-router-skill": 1.317,
            "claude-agent-workflow-designer": 0.8,
        },
    }
    validate_decision_doc(good_summary)
    tmp_decision = ROOT / "out" / "v0.5-self-test-decision.md"
    tmp_decision.write_text(
        "# Decision\n\n"
        "Decision: keep\n\n"
        "- Decision: kill-or-merge\n\n"
        "- 12 fixtures evaluated.\n"
        "- Candidate keep/kill average: 1.883.\n"
        "- `workflow-router-skill` baseline average: 1.317.\n"
        "- `claude-agent-workflow-designer` baseline average: 0.8.\n"
        "The candidate aggregate keep/kill average beats each baseline aggregate. "
        "V0.5 does not claim a per-metric margin.\n"
    )
    try:
        validate_decision_doc(good_summary, tmp_decision)
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: contradictory decision doc passed")
    tmp_decision.write_text(
        "# Decision\n\n"
        "Decision: keep\n\n"
        "- 12 fixtures evaluated.\n"
        "- Candidate keep/kill average: 1.883.\n"
        "- `workflow-router-skill` baseline average: 1.317.\n"
        "- `claude-agent-workflow-designer` baseline average: 0.8.\n"
        "The candidate aggregate keep/kill average beats each baseline aggregate by more "
        "than 90 percent across the evaluator's keep/kill metric set. "
        "V0.5 does not claim a per-metric margin.\n"
        "- Four positive fixtures activate.\n"
        "- Four negative fixtures downgrade.\n"
        "- Three borderline fixtures downgrade to `workflow-router`.\n"
        "- The meta/runtime fixture activates to a backlog-oriented execution path.\n"
        "- Every fixture has a schema-valid artifact or valid downgrade artifact.\n"
        "- `workflow-router-skill`: source-hashed normalization failure.\n"
        "- `claude-agent-workflow-designer`: source-hashed normalization failure.\n"
        "The consumer evidence format is not a live blinded-review runner.\n"
        "V0.5 does not claim runtime execution or live model generation from `SKILL.md`. "
        "It also does not claim fresh baseline execution.\n"
    )
    try:
        validate_decision_doc(good_summary, tmp_decision)
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: overstated decision margin passed")
    exact_margin_summary = {
        "decision": "keep",
        "fixture_count": 12,
        "candidate_keep_kill_average": 1.8,
        "baseline_keep_kill_averages": {
            "workflow-router-skill": 1.5,
            "claude-agent-workflow-designer": 1.0,
        },
    }
    exact_margin_decision_text = (
        "# Decision\n\n"
        "Decision: keep\n\n"
        "- 12 fixtures evaluated.\n"
        "- Candidate keep/kill average: 1.8.\n"
        "- `workflow-router-skill` baseline average: 1.5.\n"
        "- `claude-agent-workflow-designer` baseline average: 1.0.\n"
        "The candidate aggregate keep/kill average beats each baseline aggregate by at least "
        "20 percent across the evaluator's keep/kill metric set. "
        "V0.5 does not claim a per-metric margin.\n"
        "- Four positive fixtures activate.\n"
        "- Four negative fixtures downgrade.\n"
        "- Three borderline fixtures downgrade to `workflow-router`.\n"
        "- The meta/runtime fixture activates to a backlog-oriented execution path.\n"
        "- Every fixture has a schema-valid artifact or valid downgrade artifact.\n"
        "- `workflow-router-skill`: source-hashed normalization failure.\n"
        "- `claude-agent-workflow-designer`: source-hashed normalization failure.\n"
        "The consumer evidence format is not a live blinded-review runner.\n"
        "V0.5 does not claim runtime execution or live model generation from `SKILL.md`. "
        "It also does not claim fresh baseline execution.\n"
    )
    tmp_decision.write_text(exact_margin_decision_text)
    validate_decision_doc(exact_margin_summary, tmp_decision)
    tmp_decision.write_text(
        exact_margin_decision_text + "It does not use runtime-backed evidence from sibling baselines.\n"
    )
    validate_decision_doc(exact_margin_summary, tmp_decision)

    def assert_decision_boundary_rejected(claim: str, label: str) -> None:
        tmp_decision.write_text(exact_margin_decision_text + claim + "\n")
        try:
            validate_decision_doc(exact_margin_summary, tmp_decision)
        except EvaluationError as exc:
            require(
                str(exc) == "docs/v0.5-decision.md contains contradictory boundary claim",
                f"self-test failed: {label} failed for wrong reason: {exc}",
            )
        else:
            raise EvaluationError(f"self-test failed: {label} passed")

    assert_decision_boundary_rejected(
        "V0.5 claims fresh baseline execution and live sibling-baseline comparison.",
        "contradictory boundary claim",
    )
    assert_decision_boundary_rejected(
        "Both baseline skills were rerun live for this gate before comparison.",
        "live baseline rerun claim",
    )
    assert_decision_boundary_rejected(
        "This gate relies on fresh baseline re-execution against sibling sources.",
        "fresh baseline re-execution claim",
    )
    assert_decision_boundary_rejected(
        "We reran the baseline against the live source and used that runtime evidence.",
        "runtime evidence claim",
    )
    for claim in [
        "It freshly rechecked sibling baseline sources for this gate.",
        "This gate compares sibling baselines live during evaluation.",
        "The keep gate uses runtime-backed evidence from sibling baselines.",
        "The decision cites a fresh rerun of peer baselines.",
        "It also compares against freshly rerun sibling baselines before deciding.",
        "It does not use runtime-backed evidence, but it claims runtime execution from SKILL.md.",
        "It does not claim fresh baseline execution, but compares sibling baselines live during evaluation.",
        "The evaluator not only summarizes the data, it reran live sibling baselines for this gate.",
        "It does not use runtime-backed evidence and claims runtime execution from SKILL.md.",
        "It does not claim fresh baseline execution and compares sibling baselines live during evaluation.",
        "It does not claim fresh baseline execution or compares sibling baselines live during evaluation.",
        "It does not claim fresh baseline execution while comparing sibling baselines live during evaluation.",
        "It does not claim fresh baseline execution while both baseline skills reran live before comparison.",
        "The evaluator never reran the baseline and reran live sibling baselines for this gate.",
        "Without runtime-backed evidence it claims runtime execution from SKILL.md.",
        "V0.5 does not claim runtime execution or live model generation from SKILL.md and claims runtime execution from SKILL.md.",
    ]:
        assert_decision_boundary_rejected(claim, "baseline rerun paraphrase claim")
    tmp_decision.unlink(missing_ok=True)
    try:
        resolve_out_root("/tmp/v0.5-outside-repo")
    except EvaluationError:
        pass
    else:
        raise EvaluationError("self-test failed: external out path passed")
    tmp_plan.unlink(missing_ok=True)
    tmp_raw.unlink(missing_ok=True)
    tmp_manifest.unlink(missing_ok=True)

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
            summary = evaluate_manifest(ROOT / args.manifest, resolve_out_root(args.out))
            print(f"manifest evaluated: {summary['fixture_count']} fixtures, decision={summary['decision']}")
            if summary["decision"] != "keep":
                raise SystemExit(1)
            return
        parser.error("use --self-test, --plan, or --manifest")
    except EvaluationError as exc:
        raise SystemExit(f"evaluate_plan: {exc}") from exc


if __name__ == "__main__":
    main()
