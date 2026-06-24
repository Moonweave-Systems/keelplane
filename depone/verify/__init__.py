from __future__ import annotations

import argparse
import importlib
import json
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

from depone.core.plan_schema import load_plan
from depone.verify.adapters import generic, resolve
from depone.verify.engine import run_verification
from depone.verify.operator_view import write_operator_view


def run(args: argparse.Namespace) -> None:
    if args.self_test:
        _self_test()
        return

    if not args.plan:
        print(
            "Usage: depone verify <plan.json> --evidence <evidence-dir>",
            file=sys.stderr,
        )
        sys.exit(1)
    if not args.evidence:
        print("Error: --evidence is required", file=sys.stderr)
        sys.exit(1)

    try:
        plan = load_plan(args.plan)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"Error: cannot load plan: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        adapter_mod = resolve(args.adapter)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    mod = importlib.import_module(adapter_mod)
    try:
        evidence = mod.read_evidence(args.evidence)
    except NotADirectoryError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    report = run_verification(plan, evidence, framework=args.adapter)

    report_dict = asdict(report)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(report_dict, f, indent=2)
        f.write("\n")

    verdict = report_dict["verdict"]
    print(f"Verification report written to {out_path}")
    print(f"  Verdict: {verdict}")
    print(f"  Decision: {report_dict['decision']}")
    print(f"  Assurance: {report_dict['assurance']}")
    print(f"  Phases: {len(report_dict['phases'])}")

    if args.operator_view_out:
        view_path = write_operator_view(report, args.operator_view_out)
        print(f"Operator view written to {view_path}")

    if verdict != "verified":
        sys.exit(1)


def _self_test() -> None:
    """Verify distinguishes known-good from tampered evidence."""
    print("depone verify --self-test")
    tests = 0
    passed = 0

    def _write_evidence_contract(path: Path) -> None:
        contract = {
            "schema_version": "v105.verify_wedge",
            "required_evidence": ["run-metadata.json"],
        }
        (path / "evidence-contract.json").write_text(json.dumps(contract))

    def _create_evidence_dir(tmp: str, *, tamper: bool = False) -> dict:
        """Create a sample evidence dir. If tamper=True, corrupt the handoff hash."""
        d = Path(tmp) / "evidence"
        d.mkdir(parents=True, exist_ok=True)

        # Handoff artifact
        handoff_content = (
            "analysis complete: all endpoints authenticated"
            if not tamper
            else "TAMPERED DATA"
        )
        (d / "handoffs").mkdir(parents=True, exist_ok=True)
        (d / "handoffs" / "phase-1-report.md").write_text(handoff_content)

        # Gate approval
        (d / "gates" / "write").mkdir(parents=True, exist_ok=True)
        (d / "gates" / "write" / "approved").write_text("approved")

        # Run metadata
        meta = {"run_id": "test-run-001", "num_rounds": 3}
        (d / "run-metadata.json").write_text(json.dumps(meta))
        _write_evidence_contract(d)

        # Plan that expects the handoff
        import hashlib

        expected_sha = (
            hashlib.sha256(
                b"analysis complete: all endpoints authenticated"
            ).hexdigest()
            if not tamper
            else "0" * 64
        )

        plan = {
            "schema_version": "0.5",
            "plan_id": "test-verify-plan",
            "created_by": "depone",
            "source_prompt": "test verification",
            "activation": {
                "decision": "activate",
                "matched_thresholds": ["downstream-consumer"],
                "downgrade_target": None,
                "reason": "test",
            },
            "objective": "test verification",
            "surfaces": [],
            "assumptions": ["this is a test"],
            "patterns": ["Sequential"],
            "phases": [
                {
                    "id": "phase-1",
                    "name": "Analysis",
                    "entry_criteria": [],
                    "exit_criteria": [],
                },
                {
                    "id": "phase-2",
                    "name": "Review",
                    "entry_criteria": [],
                    "exit_criteria": [],
                },
            ],
            "workers": [],
            "handoffs": [
                {
                    "from_phase": "phase-1",
                    "to_phase": "phase-2",
                    "artifact": "handoffs/phase-1-report.md",
                    "expected_hash": expected_sha,
                    "artifact_schema": {
                        "format": "markdown",
                        "required_fields": ["content"],
                        "validation_command": "",
                    },
                }
            ],
            "parallelism": {
                "shape": "none",
                "cap": 1,
                "barriers": [],
                "fan_in_rule": None,
            },
            "verification": [
                {
                    "claim_or_output": "All endpoints authenticated",
                    "ground_truth": "handoffs/phase-1-report.md",
                }
            ],
            "risk_gates": [
                {
                    "trigger": "write",
                    "safe_default": "read-only",
                    "requires_user_approval": True,
                }
            ],
            "budget": {"max_agents": 5, "max_rounds": 10, "max_retries": 2},
            "resume": {"cached_outputs": [], "invalidation_rules": []},
            "execution_path": {
                "mode": "plugin",
                "first_slice": {
                    "instruction": "",
                    "inputs": [],
                    "expected_output": "",
                    "completion_check": "",
                    "forbidden_actions": [],
                },
                "consumer": "codex-agent",
            },
        }

        plan_path = Path(tmp) / "plan.json"
        with open(plan_path, "w") as f:
            json.dump(plan, f, indent=2)

        return {"plan": plan, "plan_path": str(plan_path), "evidence_dir": str(d)}

    # Test 1: Known-good evidence → verified
    tests += 1
    with tempfile.TemporaryDirectory() as tmp:
        ctx = _create_evidence_dir(tmp, tamper=False)
        plan = load_plan(ctx["plan_path"])
        evidence = generic.read_evidence(ctx["evidence_dir"])
        report = run_verification(plan, evidence)
        if report.verdict == "verified":
            passed += 1
            print(f"  [PASS] Test {tests}: known-good evidence → verified")
        else:
            print(f"  [FAIL] Test {tests}: expected verified, got {report.verdict}")

    # Test 2: Tampered evidence → refuted
    tests += 1
    with tempfile.TemporaryDirectory() as tmp:
        ctx = _create_evidence_dir(tmp, tamper=True)
        plan = load_plan(ctx["plan_path"])
        evidence = generic.read_evidence(ctx["evidence_dir"])
        report = run_verification(plan, evidence)
        if report.verdict == "refuted":
            passed += 1
            print(f"  [PASS] Test {tests}: tampered evidence → refuted")
        else:
            print(f"  [FAIL] Test {tests}: expected refuted, got {report.verdict}")

    # Test 3: Missing description-only handoff (no expected_hash) → insufficient-evidence
    tests += 1
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp) / "evidence"
        d.mkdir(parents=True)
        (d / "run-metadata.json").write_text('{"run_id": "empty-run"}')
        _write_evidence_contract(d)
        empty_plan = {
            "schema_version": "0.5",
            "plan_id": "empty-test",
            "created_by": "depone",
            "source_prompt": "test",
            "activation": {
                "decision": "activate",
                "matched_thresholds": ["downstream-consumer"],
                "downgrade_target": None,
                "reason": "test",
            },
            "objective": "test",
            "surfaces": [],
            "assumptions": ["test"],
            "patterns": ["Sequential"],
            "phases": [
                {
                    "id": "phase-1",
                    "name": "Test",
                    "entry_criteria": [],
                    "exit_criteria": [],
                },
                {
                    "id": "phase-2",
                    "name": "Next",
                    "entry_criteria": [],
                    "exit_criteria": [],
                },
            ],
            "workers": [],
            "handoffs": [
                {
                    "from_phase": "phase-1",
                    "to_phase": "phase-2",
                    "artifact": "missing-report.md",
                    "expected_hash": "",
                    "artifact_schema": {
                        "format": "markdown",
                        "required_fields": ["content"],
                        "validation_command": "",
                    },
                }
            ],
            "parallelism": {
                "shape": "none",
                "cap": 1,
                "barriers": [],
                "fan_in_rule": None,
            },
            "verification": [],
            "risk_gates": [],
            "budget": {"max_agents": 5, "max_rounds": 10, "max_retries": 2},
            "resume": {"cached_outputs": [], "invalidation_rules": []},
            "execution_path": {
                "mode": "plugin",
                "first_slice": {
                    "instruction": "",
                    "inputs": [],
                    "expected_output": "",
                    "completion_check": "",
                    "forbidden_actions": [],
                },
                "consumer": "codex-agent",
            },
        }
        plan_path = Path(tmp) / "plan.json"
        with open(plan_path, "w") as f:
            json.dump(empty_plan, f, indent=2)
        evidence = generic.read_evidence(str(d))
        report = run_verification(empty_plan, evidence)
        if report.verdict == "insufficient-evidence":
            passed += 1
            print(
                f"  [PASS] Test {tests}: description-only handoff → insufficient-evidence"
            )
        else:
            print(
                f"  [FAIL] Test {tests}: expected insufficient-evidence, got {report.verdict}"
            )

    # Test 4: Canonical handoff with evidence_path + good evidence → verified
    tests += 1
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp) / "evidence"
        d.mkdir(parents=True)
        (d / "reports").mkdir(parents=True, exist_ok=True)
        (d / "reports" / "analysis.md").write_text("analysis ok")
        (d / "run-metadata.json").write_text('{"run_id": "canon-test"}')
        _write_evidence_contract(d)
        plan_canon_good = {
            "schema_version": "0.5",
            "plan_id": "canon-good",
            "created_by": "depone",
            "source_prompt": "test",
            "activation": {
                "decision": "activate",
                "matched_thresholds": ["downstream-consumer"],
                "downgrade_target": None,
                "reason": "test",
            },
            "objective": "test",
            "surfaces": [],
            "assumptions": ["test"],
            "patterns": ["Sequential"],
            "phases": [
                {
                    "id": "phase-1",
                    "name": "Test",
                    "entry_criteria": [],
                    "exit_criteria": [],
                },
                {
                    "id": "phase-2",
                    "name": "Next",
                    "entry_criteria": [],
                    "exit_criteria": [],
                },
            ],
            "workers": [],
            "handoffs": [
                {
                    "from_phase": "phase-1",
                    "to_phase": "phase-2",
                    "artifact": "full analysis report",
                    "evidence_path": "reports/analysis.md",
                    "artifact_schema": {
                        "format": "markdown",
                        "required_fields": [],
                        "validation_command": "",
                    },
                }
            ],
            "parallelism": {
                "shape": "none",
                "cap": 1,
                "barriers": [],
                "fan_in_rule": None,
            },
            "verification": [],
            "risk_gates": [],
            "budget": {"max_agents": 5, "max_rounds": 10, "max_retries": 2},
            "resume": {"cached_outputs": [], "invalidation_rules": []},
            "execution_path": {
                "mode": "plugin",
                "first_slice": {
                    "instruction": "",
                    "inputs": [],
                    "expected_output": "",
                    "completion_check": "",
                    "forbidden_actions": [],
                },
                "consumer": "codex-agent",
            },
        }
        evidence = generic.read_evidence(str(d))
        report = run_verification(plan_canon_good, evidence)
        if report.verdict == "verified":
            passed += 1
            print(f"  [PASS] Test {tests}: canonical evidence_path + good → verified")
        else:
            print(f"  [FAIL] Test {tests}: expected verified, got {report.verdict}")

    # Test 5: Description artifact, no path/hash, good rest → insufficient-evidence
    tests += 1
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp) / "evidence"
        d.mkdir(parents=True)
        (d / "gates" / "write").mkdir(parents=True, exist_ok=True)
        (d / "gates" / "write" / "approved").write_text("ok")
        (d / "run-metadata.json").write_text('{"run_id": "no-handoff-evidence"}')
        _write_evidence_contract(d)
        plan_canon_desc = {
            "schema_version": "0.5",
            "plan_id": "canon-desc",
            "created_by": "depone",
            "source_prompt": "test",
            "activation": {
                "decision": "activate",
                "matched_thresholds": ["downstream-consumer"],
                "downgrade_target": None,
                "reason": "test",
            },
            "objective": "test",
            "surfaces": [],
            "assumptions": ["test"],
            "patterns": ["Sequential"],
            "phases": [
                {
                    "id": "phase-1",
                    "name": "Test",
                    "entry_criteria": [],
                    "exit_criteria": [],
                },
                {
                    "id": "phase-2",
                    "name": "Next",
                    "entry_criteria": [],
                    "exit_criteria": [],
                },
            ],
            "workers": [],
            "handoffs": [
                {
                    "from_phase": "phase-1",
                    "to_phase": "phase-2",
                    "artifact": "some analysis result",
                    "artifact_schema": {
                        "format": "text",
                        "required_fields": [],
                        "validation_command": "",
                    },
                }
            ],
            "parallelism": {
                "shape": "none",
                "cap": 1,
                "barriers": [],
                "fan_in_rule": None,
            },
            "verification": [],
            "risk_gates": [
                {
                    "trigger": "write",
                    "safe_default": "read-only",
                    "requires_user_approval": True,
                }
            ],
            "budget": {"max_agents": 5, "max_rounds": 10, "max_retries": 2},
            "resume": {"cached_outputs": [], "invalidation_rules": []},
            "execution_path": {
                "mode": "plugin",
                "first_slice": {
                    "instruction": "",
                    "inputs": [],
                    "expected_output": "",
                    "completion_check": "",
                    "forbidden_actions": [],
                },
                "consumer": "codex-agent",
            },
        }
        evidence = generic.read_evidence(str(d))
        report = run_verification(plan_canon_desc, evidence)
        if report.verdict == "insufficient-evidence":
            passed += 1
            print(
                f"  [PASS] Test {tests}: description artifact, no path/hash → insufficient-evidence"
            )
        else:
            print(
                f"  [FAIL] Test {tests}: expected insufficient-evidence, got {report.verdict}"
            )

    # Test 6: Hash tamper → refuted (canonical keys)
    tests += 1
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp) / "evidence"
        d.mkdir(parents=True)
        (d / "handoffs").mkdir(parents=True, exist_ok=True)
        (d / "handoffs" / "output.json").write_text("TAMPERED")
        (d / "run-metadata.json").write_text('{"run_id": "tamper-test"}')
        _write_evidence_contract(d)
        plan_canon_tamper = {
            "schema_version": "0.5",
            "plan_id": "canon-tamper",
            "created_by": "depone",
            "source_prompt": "test",
            "activation": {
                "decision": "activate",
                "matched_thresholds": ["downstream-consumer"],
                "downgrade_target": None,
                "reason": "test",
            },
            "objective": "test",
            "surfaces": [],
            "assumptions": ["test"],
            "patterns": ["Sequential"],
            "phases": [
                {
                    "id": "phase-1",
                    "name": "Test",
                    "entry_criteria": [],
                    "exit_criteria": [],
                },
                {
                    "id": "phase-2",
                    "name": "Next",
                    "entry_criteria": [],
                    "exit_criteria": [],
                },
            ],
            "workers": [],
            "handoffs": [
                {
                    "from_phase": "phase-1",
                    "to_phase": "phase-2",
                    "artifact": "handoffs/output.json",
                    "expected_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                    "artifact_schema": {
                        "format": "json",
                        "required_fields": [],
                        "validation_command": "",
                    },
                }
            ],
            "parallelism": {
                "shape": "none",
                "cap": 1,
                "barriers": [],
                "fan_in_rule": None,
            },
            "verification": [],
            "risk_gates": [],
            "budget": {"max_agents": 5, "max_rounds": 10, "max_retries": 2},
            "resume": {"cached_outputs": [], "invalidation_rules": []},
            "execution_path": {
                "mode": "plugin",
                "first_slice": {
                    "instruction": "",
                    "inputs": [],
                    "expected_output": "",
                    "completion_check": "",
                    "forbidden_actions": [],
                },
                "consumer": "codex-agent",
            },
        }
        evidence = generic.read_evidence(str(d))
        report = run_verification(plan_canon_tamper, evidence)
        if report.verdict == "refuted":
            passed += 1
            print(f"  [PASS] Test {tests}: hash tamper (canonical) → refuted")
        else:
            print(f"  [FAIL] Test {tests}: expected refuted, got {report.verdict}")

    tests += 1
    with tempfile.TemporaryDirectory() as tmp:
        ctx = _create_evidence_dir(tmp, tamper=False)
        approved = Path(ctx["evidence_dir"]) / "gates" / "write" / "approved"
        approved.unlink()
        evidence = generic.read_evidence(ctx["evidence_dir"])
        report = run_verification(ctx["plan"], evidence)
        if report.verdict == "insufficient-evidence":
            passed += 1
            print(
                f"  [PASS] Test {tests}: missing required gate evidence → insufficient-evidence"
            )
        else:
            print(
                f"  [FAIL] Test {tests}: expected insufficient-evidence, got {report.verdict}"
            )

    print(f"\nSelf-test: {passed}/{tests} passed")
    sys.exit(0 if passed == tests else 1)
