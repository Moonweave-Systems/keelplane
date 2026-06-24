"""depone design — decompose an objective into a workflow plan.

In V104.0, design produces a template plan.json from common workflow patterns,
then validates it against the schema. The plan is intended to be reviewed and
refined by the AI agent or human operator before compilation.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

from depone.cli.design_contract import apply_minimal_contract
from depone.core.plan_schema import validate_plan_strict

# Reusable workflow templates indexed by detected pattern.
# Each template is a partial plan.json that gets populated with the objective.
_PLAN_TEMPLATES: dict[str, dict[str, Any]] = {
    "sequential": {
        "schema_version": "0.5",
        "plan_id": "",
        "created_by": "depone",
        "source_prompt": "",
        "activation": {
            "decision": "activate",
            "matched_thresholds": ["downstream-consumer", "human-gates"],
            "downgrade_target": None,
            "reason": "Sequential workflow with clear phase dependencies and human gates.",
        },
        "objective": "",
        "surfaces": [],
        "assumptions": [],
        "patterns": ["Sequential"],
        "phases": [],
        "workers": [],
        "handoffs": [],
        "parallelism": {
            "shape": "none",
            "concurrency_cap": 1,
            "barriers": [],
            "fan_in_rule": "single downstream review",
        },
        "verification": [],
        "risk_gates": [],
        "budget": {
            "max_agents": 3,
            "max_rounds": 5,
            "max_retries": 2,
            "time_box": "30m",
            "file_touch_limit": "5 files",
        },
        "resume": {"cacheable_outputs": [], "invalidators": [], "restart_points": []},
        "execution_path": {
            "mode": "plugin",
            "first_slice": {
                "instruction": "",
                "inputs": [],
                "expected_output": "Completed first phase",
                "completion_check": "Verify first phase output artifact exists and is non-empty.",
                "forbidden_actions": [],
            },
            "consumer": "codex-agent",
        },
    },
    "research": {
        "schema_version": "0.5",
        "plan_id": "",
        "created_by": "depone",
        "source_prompt": "",
        "activation": {
            "decision": "activate",
            "matched_thresholds": ["multi-surface-fanout", "adversarial-verification"],
            "downgrade_target": None,
            "reason": "Multi-angle research with independent verification.",
        },
        "objective": "",
        "surfaces": [],
        "assumptions": [],
        "patterns": ["Parallel Fan-Out / Fan-In", "Adversarial Verify"],
        "phases": [],
        "workers": [],
        "handoffs": [],
        "parallelism": {
            "shape": "fan-out-fan-in",
            "concurrency_cap": 3,
            "barriers": ["research-complete"],
            "fan_in_rule": "all research findings reconcile before review",
        },
        "verification": [],
        "risk_gates": [],
        "budget": {
            "max_agents": 5,
            "max_rounds": 3,
            "max_retries": 1,
            "time_box": "45m",
            "file_touch_limit": "8 files",
        },
        "resume": {"cacheable_outputs": [], "invalidators": [], "restart_points": []},
        "execution_path": {
            "mode": "plugin",
            "first_slice": {
                "instruction": "",
                "inputs": [],
                "expected_output": "Research findings document",
                "completion_check": "Verify findings contain actionable evidence, not speculation.",
                "forbidden_actions": ["write", "network"],
            },
            "consumer": "codex-agent",
        },
    },
    "audit": {
        "schema_version": "0.5",
        "plan_id": "",
        "created_by": "depone",
        "source_prompt": "",
        "activation": {
            "decision": "activate",
            "matched_thresholds": [
                "multi-surface-fanout",
                "resumable-handoffs",
                "adversarial-verification",
            ],
            "downgrade_target": None,
            "reason": "Codebase audit with parallel surface investigation and adversarial verification.",
        },
        "objective": "",
        "surfaces": [],
        "assumptions": [],
        "patterns": [
            "Parallel Fan-Out / Fan-In",
            "Adversarial Verify",
            "Resume And Cache",
        ],
        "phases": [],
        "workers": [],
        "handoffs": [],
        "parallelism": {
            "shape": "fan-out-fan-in",
            "concurrency_cap": 4,
            "barriers": ["audit-complete"],
            "fan_in_rule": "all inspected surfaces reconcile before review",
        },
        "verification": [],
        "risk_gates": [
            {
                "trigger": "write",
                "safe_default": "read-only analysis",
                "requires_user_approval": True,
            },
        ],
        "budget": {
            "max_agents": 6,
            "max_rounds": 5,
            "max_retries": 2,
            "time_box": "60m",
            "file_touch_limit": "10 files",
        },
        "resume": {"cacheable_outputs": [], "invalidators": [], "restart_points": []},
        "execution_path": {
            "mode": "plugin",
            "first_slice": {
                "instruction": "",
                "inputs": [],
                "expected_output": "Surface map with potential findings per area",
                "completion_check": "Verify each surface has been inspected and findings documented.",
                "forbidden_actions": ["write", "network"],
            },
            "consumer": "codex-agent",
        },
    },
}

_PATTERN_KEYWORDS: list[tuple[list[str], str]] = [
    (["audit", "review", "inspect", "check", "security", "scan"], "audit"),
    (["research", "investigate", "explore", "find", "search", "study"], "research"),
]


def _detect_pattern(objective: str) -> str:
    """Detect a workflow pattern from the objective text."""
    obj_lower = objective.lower()
    for keywords, pattern in _PATTERN_KEYWORDS:
        if any(kw in obj_lower for kw in keywords):
            return pattern
    return "sequential"


def _generate_plan_id(objective: str) -> str:
    """Generate a stable plan ID from the objective."""
    import hashlib

    suffix = hashlib.md5(objective.encode()).hexdigest()[:8]
    words = objective.lower().split()[:4]
    slug = "-".join(w for w in words if w.isalpha())
    return f"{slug}-{suffix}"


def _create_surface_from_path(path_str: str | None) -> list[dict[str, str]]:
    """Create a surface entry from a repo path."""
    if not path_str:
        return []
    p = Path(path_str)
    return [
        {
            "id": p.name or "root",
            "kind": "repo",
            "locator": str(p.resolve()),
            "access_mode": "read-only",
        }
    ]


def run(args: argparse.Namespace) -> None:
    if args.self_test:
        _self_test()
        return

    objective = args.objective
    if not objective:
        print(
            "Usage: depone design <objective> [--surface PATH] [--out plan.json]",
            file=sys.stderr,
        )
        sys.exit(1)
    pattern_name = _detect_pattern(objective)
    template = _PLAN_TEMPLATES.get(pattern_name, _PLAN_TEMPLATES["sequential"])
    plan_id = _generate_plan_id(objective)

    plan = copy.deepcopy(template)
    plan["plan_id"] = plan_id
    plan["source_prompt"] = objective
    plan["objective"] = objective
    plan["surfaces"] = _create_surface_from_path(args.surface or ".")
    apply_minimal_contract(plan, objective)

    errors = validate_plan_strict(plan)
    if errors:
        print(
            f"Error: generated plan failed validation with {len(errors)} issue(s):",
            file=sys.stderr,
        )
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(1)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(plan, f, indent=2)
        f.write("\n")

    print(f"Plan written to {out_path}")
    print(f"  Pattern: {pattern_name}")
    print(f"  Plan ID: {plan_id}")
    print(f"  Objective: {objective}")


def _self_test() -> None:
    """Run a basic self-test."""
    import tempfile

    print("depone design --self-test")
    tests = 0
    passed = 0

    # Test 1: detect audit pattern
    tests += 1
    pattern = _detect_pattern("audit all API routes for security issues")
    if pattern == "audit":
        passed += 1
        print(f"  [PASS] Test {tests}: audit pattern detected")
    else:
        print(f"  [FAIL] Test {tests}: expected 'audit', got '{pattern}'")

    # Test 2: detect research pattern
    tests += 1
    pattern = _detect_pattern("research the best caching strategy")
    if pattern == "research":
        passed += 1
        print(f"  [PASS] Test {tests}: research pattern detected")
    else:
        print(f"  [FAIL] Test {tests}: expected 'research', got '{pattern}'")

    # Test 3: detect sequential (fallback)
    tests += 1
    pattern = _detect_pattern("deploy the application to production")
    if pattern == "sequential":
        passed += 1
        print(f"  [PASS] Test {tests}: sequential fallback")
    else:
        print(f"  [FAIL] Test {tests}: expected 'sequential', got '{pattern}'")

    tests += 1
    with tempfile.TemporaryDirectory() as tmp:
        out_path = Path(tmp) / "plan.json"
        fake_args = argparse.Namespace(
            objective="audit authentication module",
            out=str(out_path),
            surface=".",
            self_test=False,
        )
        run(fake_args)
        generated = json.loads(out_path.read_text())
        errors = validate_plan_strict(generated)
        if out_path.exists() and not errors:
            passed += 1
            print(f"  [PASS] Test {tests}: strict-valid plan file written")
        else:
            print(f"  [FAIL] Test {tests}: generated plan errors: {errors}")

    print(f"\nSelf-test: {passed}/{tests} passed")
    sys.exit(0 if passed == tests else 1)
