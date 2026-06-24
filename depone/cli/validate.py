"""depone validate — validate a plan.json against the schema."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from depone.core.plan_schema import (
    load_plan,
    validate_plan,
    validate_plan_strict,
    format_errors,
)


def run(args: argparse.Namespace) -> None:
    if args.self_test:
        _self_test()
        return

    plan_path = args.plan
    if not plan_path:
        print("Usage: depone validate <plan.json>")
        sys.exit(1)

    path = Path(plan_path)
    if not path.exists():
        print(f"Error: file not found: {path}")
        sys.exit(1)

    try:
        plan = load_plan(str(path))
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error: cannot load plan: {e}")
        sys.exit(1)

    errors = validate_plan_strict(plan)
    print(format_errors(errors))
    sys.exit(1 if errors else 0)


def _embedded_parity_holds() -> bool:
    import copy

    from depone.cli.demo import _generate_demo_plan
    from depone.core.embedded_plan_contract import validate_embedded_contract
    from depone.core.plan_schema import _load_repo_evaluator

    base = _generate_demo_plan()
    vectors: list[tuple[str, bool, dict]] = [("valid-base", True, base)]
    for field in (
        "assumptions",
        "patterns",
        "phases",
        "workers",
        "handoffs",
        "verification",
        "risk_gates",
    ):
        broken = copy.deepcopy(base)
        broken[field] = []
        vectors.append((f"empty-{field}", False, broken))
    no_approval = copy.deepcopy(base)
    no_approval["risk_gates"][0]["requires_user_approval"] = False
    vectors.append(("gate-no-approval", False, no_approval))

    canonical = _load_repo_evaluator()
    for _name, expected_valid, plan in vectors:
        embedded_valid = not validate_embedded_contract(plan)
        if embedded_valid != expected_valid:
            return False
        if canonical is not None and embedded_valid:
            try:
                canonical(plan)
            except ValueError:
                return False
    return True


def _self_test() -> None:
    """Run a basic self-test."""
    print("depone validate --self-test")
    tests = 0
    passed = 0

    # Test 1: lightweight check accepts minimal plan
    tests += 1
    valid_plan = {
        "schema_version": "0.5",
        "plan_id": "self-test",
        "created_by": "depone",
        "source_prompt": "self-test",
        "activation": {
            "decision": "activate",
            "matched_thresholds": ["downstream-consumer", "human-gates"],
            "downgrade_target": None,
            "reason": "test",
        },
        "objective": "self-test objective",
        "surfaces": [
            {"id": "test", "kind": "repo", "locator": ".", "access_mode": "read-only"}
        ],
        "assumptions": [],
        "patterns": ["Sequential"],
        "phases": [],
        "workers": [],
        "handoffs": [],
        "parallelism": {
            "shape": "none",
            "concurrency_cap": 1,
            "barriers": [],
            "fan_in_rule": "all",
        },
        "verification": [],
        "risk_gates": [],
        "budget": {
            "max_agents": 1,
            "max_rounds": 1,
            "max_retries": 0,
            "time_box": "5m",
            "file_touch_limit": "3",
        },
        "resume": {"cacheable_outputs": [], "invalidators": [], "restart_points": []},
        "execution_path": {
            "mode": "direct-codex",
            "first_slice": {
                "instruction": "do it",
                "inputs": ["task"],
                "expected_output": "done",
                "completion_check": "check",
                "forbidden_actions": ["write"],
            },
            "consumer": "human",
        },
    }
    errs = validate_plan(valid_plan)
    if not errs:
        passed += 1
        print(f"  [PASS] Test {tests}: lightweight check passes")
    else:
        print(f"  [FAIL] Test {tests}: lightweight check rejected: {errs}")

    # Test 2: missing required field
    tests += 1
    errs = validate_plan({})
    if errs:
        passed += 1
        print(f"  [PASS] Test {tests}: empty plan rejected ({len(errs)} errors)")
    else:
        print(f"  [FAIL] Test {tests}: empty plan incorrectly accepted")

    # Test 3: bad schema version
    tests += 1
    bad_version = dict(valid_plan)
    bad_version["schema_version"] = "9.9"
    errs = validate_plan(bad_version)
    if any("schema_version" in e for e in errs):
        passed += 1
        print(f"  [PASS] Test {tests}: bad schema version rejected")
    else:
        print(f"  [FAIL] Test {tests}: bad schema version accepted")

    # Test 4: embedded contract stays self-consistent and never looser than canonical
    tests += 1
    if _embedded_parity_holds():
        passed += 1
        print(f"  [PASS] Test {tests}: embedded contract parity")
    else:
        print(f"  [FAIL] Test {tests}: embedded contract drift detected")

    print(f"\nSelf-test: {passed}/{tests} passed")
    if passed == tests:
        root = Path(__file__).resolve().parents[2]
        script = root / "scripts" / "evaluate_plan.py"
        if not script.is_file():
            strict_errors = validate_plan_strict(valid_plan)
            if any("activated plans need assumptions" in e for e in strict_errors):
                print("  embedded strict validator: PASS")
            else:
                print(f"  embedded strict validator: FAIL ({strict_errors})")
                sys.exit(1)
            sys.exit(0)

        print("\nRunning evaluate_plan.py --self-test...")
        result = subprocess.run(
            [sys.executable, str(script), "--self-test"],
            cwd=str(root),
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            print("  evaluate_plan --self-test: PASS")
        else:
            print(f"  evaluate_plan --self-test: FAIL (exit {result.returncode})")
            if result.stdout:
                print(result.stdout[-500:])
            if result.stderr:
                print(result.stderr[-500:], file=sys.stderr)
            sys.exit(result.returncode)
    sys.exit(0 if passed == tests else 1)
