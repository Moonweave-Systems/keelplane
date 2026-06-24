"""depone demo — run a complete design→compile→verify cycle.

The demo works entirely offline with Python stdlib only. It:
1. Generates a plan using depone design
2. Validates the plan
3. Compiles to Conductor YAML
4. Creates synthetic execution evidence
5. Verifies the evidence against the plan
6. Produces a verification report
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from depone.compile.conductor import emit_yaml
from depone.core.plan_schema import validate_plan_strict
from depone.verify.adapters.generic import read_evidence
from depone.verify.engine import run_verification


def run(args: argparse.Namespace) -> None:
    if args.self_test:
        _self_test()
        return

    out_dir = (
        Path(args.out) if args.out else Path(tempfile.mkdtemp(suffix="_depone_demo"))
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 56)
    print("  Depone Demo — Design → Compile → Verify")
    print("=" * 56)

    # Step 1: Design
    print("\n[1/4] Designing workflow...")
    plan = _generate_demo_plan()
    plan_path = out_dir / "plan.json"
    with open(plan_path, "w") as f:
        json.dump(plan, f, indent=2)
        f.write("\n")
    print(f"  Plan: {plan_path}")
    print(f"  Objective: {plan['objective']}")
    print(f"  Pattern: {plan['patterns'][0]}")

    # Step 2: Validate
    print("\n[2/4] Validating plan...")
    errors = validate_plan_strict(plan)
    if errors:
        print(f"  [FAIL] Plan validation: {len(errors)} error(s)")
        for e in errors:
            print(f"    - {e}")
        sys.exit(1)
    print("  [PASS] Plan is valid")

    # Step 3: Compile
    print("\n[3/4] Compiling to Conductor YAML...")
    yaml_path = out_dir / "workflow.yaml"
    yaml_content = emit_yaml(plan)
    yaml_path.write_text(yaml_content + "\n")
    print(f"  [PASS] Conductor YAML: {yaml_path}")

    # Step 4: Verify
    print("\n[4/4] Verifying execution evidence...")
    evidence_dir = out_dir / "evidence"
    _generate_synthetic_evidence(plan, evidence_dir)
    evidence = read_evidence(str(evidence_dir))
    report = run_verification(plan, evidence)
    report_path = out_dir / "verification-report.json"
    with open(report_path, "w") as f:
        json.dump(asdict(report), f, indent=2)
        f.write("\n")

    if report.verdict == "verified":
        print(f"  [PASS] Evidence verified: {report_path}")
        for p in report.phases:
            status_icon = "✓" if p.status == "passed" else "✗"
            print(f"    {status_icon} Phase '{p.phase_id}': {p.status}")
    else:
        print(f"  [FAIL] Evidence refuted ({report.verdict}): {report_path}")
        sys.exit(1)

    # Summary
    print("\n" + "=" * 56)
    print("  Demo Complete")
    print(f"  Output: {out_dir}")
    print(f"  Files: {len(list(out_dir.iterdir()))}")
    print("=" * 56)


def _generate_demo_plan() -> dict[str, Any]:
    """Generate a fully contract-compliant demo plan for a simple code review workflow."""
    return {
        "schema_version": "0.5",
        "plan_id": "demo-code-review-001",
        "created_by": "depone",
        "source_prompt": "Review the README for clarity and completeness",
        "objective": "Review the README for clarity and completeness",
        "activation": {
            "decision": "activate",
            "matched_thresholds": ["downstream-consumer", "human-gates"],
            "downgrade_target": None,
            "reason": "Sequential read-only review workflow with human gates.",
        },
        "surfaces": [
            {"id": "repo", "kind": "repo", "locator": ".", "access_mode": "read-only"},
        ],
        "assumptions": [
            {
                "claim": "README exists at repo root",
                "verification": "Check file exists",
            },
        ],
        "patterns": ["Sequential"],
        "phases": [
            {
                "id": "phase-1-inspect",
                "name": "Inspect README",
                "entry_criteria": ["README.md exists"],
                "exit_criteria": ["README content extracted"],
                "depends_on": [],
                "worker_ids": ["reader"],
                "outputs": ["README.md content", "handoffs/phase-2-input.md"],
            },
            {
                "id": "phase-2-review",
                "name": "Review content",
                "entry_criteria": ["README content available"],
                "exit_criteria": ["Review findings documented"],
                "depends_on": ["phase-1-inspect"],
                "worker_ids": ["reviewer"],
                "outputs": ["review-findings"],
            },
        ],
        "workers": [
            {
                "id": "reader",
                "role": "explorer",
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
                    "max_files": 5,
                    "max_tokens": 8000,
                    "must_include": ["README.md"],
                    "must_exclude": [],
                },
                "prompt_contract": {
                    "inputs": [{"name": "readme_path", "type": "string"}],
                    "required_output_schema": "content (string) + sections (list)",
                    "stop_conditions": ["content_extracted"],
                },
                "ownership": ["README.md"],
            },
            {
                "id": "reviewer",
                "role": "reviewer",
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
                    "max_files": 3,
                    "max_tokens": 16000,
                    "must_include": ["README.md"],
                    "must_exclude": [],
                },
                "prompt_contract": {
                    "inputs": [{"name": "readme_content", "type": "string"}],
                    "required_output_schema": "findings (list) + score (integer)",
                    "stop_conditions": ["review_complete"],
                },
                "ownership": ["review-findings"],
            },
        ],
        "handoffs": [
            {
                "from_phase": "phase-1-inspect",
                "to_phase": "phase-2-review",
                "artifact": "handoffs/phase-2-input.md",
                "artifact_schema": {
                    "format": "markdown",
                    "required_fields": ["content"],
                    "validation_command": "check non-empty",
                },
            },
        ],
        "parallelism": {
            "shape": "none",
            "concurrency_cap": 1,
            "barriers": [],
            "fan_in_rule": "all",
        },
        "verification": [
            {
                "claim_or_output": "Review handoff produced from reading the README",
                "ground_truth": "handoffs/phase-2-input.md",
                "evaluator": "ground-truth-contains",
                "expected": "README",
                "falsifier": "no review handoff referencing the README exists",
                "evidence_required": ["README.md file content"],
            },
        ],
        "risk_gates": [
            {
                "trigger": "write",
                "safe_default": "do not write without approval",
                "requires_user_approval": True,
            },
        ],
        "budget": {
            "max_agents": 2,
            "max_rounds": 3,
            "max_retries": 1,
            "time_box": "15m",
            "file_touch_limit": "5",
        },
        "resume": {
            "cacheable_outputs": ["README.md content", "review-findings"],
            "invalidators": ["README.md-change"],
            "restart_points": ["phase-1-inspect"],
        },
        "execution_path": {
            "mode": "plugin",
            "first_slice": {
                "instruction": "Read README.md and extract its content structure",
                "inputs": ["repository path", "README.md"],
                "expected_output": "README content with section breakdown",
                "completion_check": "Content is non-empty with at least 2 sections identified",
                "forbidden_actions": ["write", "shell", "network"],
            },
            "consumer": "codex-agent",
        },
    }


def _generate_synthetic_evidence(plan: dict[str, Any], evidence_dir: Path) -> None:
    """Generate synthetic execution evidence that passes verification."""
    evidence_dir.mkdir(parents=True, exist_ok=True)

    # Handoff artifact: phase-1 produces input for phase-2
    (evidence_dir / "handoffs").mkdir(parents=True, exist_ok=True)
    handoff_content = (
        "# README Review\n\n"
        "Reviewed README.md content. Structure: clear. "
        "Suggestion: add installation instructions."
    )
    (evidence_dir / "handoffs" / "phase-2-input.md").write_text(handoff_content)

    # Gate approval
    (evidence_dir / "gates" / "write").mkdir(parents=True, exist_ok=True)
    (evidence_dir / "gates" / "write" / "approved").write_text("approved")

    # Run metadata
    meta = {"run_id": "demo-run-001", "num_rounds": 2}
    (evidence_dir / "run-metadata.json").write_text(json.dumps(meta))

    contract = {
        "schema_version": "v105.verify_wedge",
        "required_evidence": ["run-metadata.json"],
    }
    (evidence_dir / "evidence-contract.json").write_text(json.dumps(contract))


def _self_test() -> None:
    """Run self-test."""
    import tempfile

    print("depone demo --self-test")

    # Run the full demo in a temp directory
    with tempfile.TemporaryDirectory() as tmp:

        class FakeArgs:
            out = tmp
            self_test = False

        try:
            run(FakeArgs())  # type: ignore[arg-type]
            print("\n  [PASS] Demo completed successfully")
            sys.exit(0)
        except SystemExit as e:
            if e.code == 0:
                print("\n  [PASS] Demo completed successfully")
                sys.exit(0)
            else:
                print(f"\n  [FAIL] Demo exited with code {e.code}")
                sys.exit(1)
        except Exception as e:
            print(f"\n  [FAIL] Demo failed: {e}")
            sys.exit(1)
