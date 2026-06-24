#!/usr/bin/env python3
"""V73 large-workflow control-plane fitness evaluator."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from compile_workflow import canonical_hash, read_json, write_json_atomic, write_text_atomic  # noqa: E402


TOOL = "dwm_large_workflow_control.py"
SCHEMA_VERSION = "1.0"
CONTROL_VERSION = "73.0.0"
CONTROL_ROOT = ROOT / "out" / "large-workflow-control"
SENTINEL = ".dwm_large_workflow_control-owned.json"

AXES = [
    {
        "id": "direction_fidelity",
        "label": "Direction Fidelity",
        "signals": ["objective", "user_intent_trace", "success_criteria", "drift_checks"],
    },
    {
        "id": "large_work_decomposition",
        "label": "Large Work Decomposition",
        "signals": ["phases", "phase_dependencies", "packet_sizing", "parallelism"],
    },
    {
        "id": "execution_quality",
        "label": "Execution Quality",
        "signals": ["verification", "review_repair_loop", "artifact_contracts", "quality_gates"],
    },
    {
        "id": "efficiency",
        "label": "Efficiency",
        "signals": ["budget", "cost_tracking", "automation", "human_gate_minimization"],
    },
    {
        "id": "recovery_ability",
        "label": "Recovery Ability",
        "signals": ["resume_points", "invalidators", "repair_paths", "safe_defaults"],
    },
    {
        "id": "evidence_quality",
        "label": "Evidence Quality",
        "signals": ["receipts", "source_hashes", "measurable_metrics", "claim_limits"],
    },
]


class LargeWorkflowControlError(ValueError):
    """Structured V73 large-workflow control failure."""

    def __init__(self, code: str, message: str, *, path: Path | str | None = None, fixture_id: str | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.path = str(path) if path is not None else None
        self.fixture_id = fixture_id

    def to_record(self) -> dict[str, Any]:
        record: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.path is not None:
            record["path"] = self.path
        if self.fixture_id is not None:
            record["fixture_id"] = self.fixture_id
        return record


def now_utc() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def rel(path: Path) -> str:
    resolved = path.resolve(strict=False)
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return str(resolved)


def reject_traversal(path: Path, *, code: str, message: str) -> None:
    if any(part == ".." for part in path.parts):
        raise LargeWorkflowControlError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise LargeWorkflowControlError(code, "path contains a symlink", path=current)


def resolve_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_LARGE_WORKFLOW_CONTROL_PATH_UNSAFE", message="control output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = CONTROL_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise LargeWorkflowControlError("ERR_LARGE_WORKFLOW_CONTROL_PATH_UNSAFE", f"control output must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise LargeWorkflowControlError("ERR_LARGE_WORKFLOW_CONTROL_PATH_UNSAFE", "control output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_LARGE_WORKFLOW_CONTROL_PATH_SYMLINK")
    return resolved


def read_sentinel(path: Path) -> dict[str, Any] | None:
    sentinel = path / SENTINEL
    if not sentinel.is_file() or sentinel.is_symlink():
        return None
    try:
        data = json.loads(sentinel.read_text())
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def prepare_out_dir(path: Path, control_id: str, *, source: Path | str) -> None:
    if path.exists():
        if path.is_symlink():
            raise LargeWorkflowControlError("ERR_LARGE_WORKFLOW_CONTROL_PATH_SYMLINK", "control output is a symlink", path=path)
        if not path.is_dir():
            raise LargeWorkflowControlError("ERR_LARGE_WORKFLOW_CONTROL_PATH_UNSAFE", "control output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("control_id") != control_id:
            raise LargeWorkflowControlError("ERR_LARGE_WORKFLOW_CONTROL_PATH_UNSAFE", "existing control output is not control-owned", path=path)
        shutil.rmtree(path)
    CONTROL_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(
        path / SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "control_version": CONTROL_VERSION,
            "control_id": control_id,
            "source_path": str(source),
            "created_at": now_utc(),
        },
        root=path,
    )


def list_present(value: Any) -> bool:
    return isinstance(value, list) and len(value) > 0


def dict_present(value: Any) -> bool:
    return isinstance(value, dict) and len(value) > 0


def has_signal(workflow: dict[str, Any], signal: str) -> bool:
    phases = workflow.get("phases")
    verification = workflow.get("verification")
    metrics = workflow.get("metrics")
    resume = workflow.get("resume")
    risk_gates = workflow.get("risk_gates")
    evidence = workflow.get("evidence")

    if signal == "objective":
        return isinstance(workflow.get("objective"), str) and bool(workflow["objective"].strip())
    if signal == "user_intent_trace":
        return list_present(workflow.get("user_intent_trace"))
    if signal == "success_criteria":
        return list_present(workflow.get("success_criteria"))
    if signal == "drift_checks":
        return list_present(workflow.get("drift_checks"))
    if signal == "phases":
        return isinstance(phases, list) and len(phases) >= 3
    if signal == "phase_dependencies":
        return isinstance(phases, list) and any(isinstance(phase, dict) and phase.get("depends_on") for phase in phases)
    if signal == "packet_sizing":
        return isinstance(phases, list) and all(isinstance(phase, dict) and phase.get("slice_size") in {"small", "medium", "large"} for phase in phases)
    if signal == "parallelism":
        return dict_present(workflow.get("parallelism")) and isinstance(workflow.get("parallelism", {}).get("concurrency_cap"), int)
    if signal == "verification":
        return list_present(verification)
    if signal == "review_repair_loop":
        return dict_present(workflow.get("review_repair_loop"))
    if signal == "artifact_contracts":
        return list_present(workflow.get("artifact_contracts"))
    if signal == "quality_gates":
        return list_present(workflow.get("quality_gates"))
    if signal == "budget":
        return dict_present(workflow.get("budget"))
    if signal == "cost_tracking":
        return dict_present(metrics) and any(key in metrics for key in ["duration_ms", "commands_run", "human_interruptions", "files_touched"])
    if signal == "automation":
        return list_present(workflow.get("automation"))
    if signal == "human_gate_minimization":
        return list_present(risk_gates) and all(isinstance(gate, dict) and gate.get("trigger") and gate.get("safe_default") for gate in risk_gates)
    if signal == "resume_points":
        return dict_present(resume) and list_present(resume.get("restart_points"))
    if signal == "invalidators":
        return dict_present(resume) and list_present(resume.get("invalidators"))
    if signal == "repair_paths":
        return list_present(workflow.get("repair_paths"))
    if signal == "safe_defaults":
        return list_present(risk_gates) and all(isinstance(gate, dict) and gate.get("safe_default") for gate in risk_gates)
    if signal == "receipts":
        return dict_present(evidence) and list_present(evidence.get("receipts"))
    if signal == "source_hashes":
        return dict_present(evidence) and dict_present(evidence.get("source_hashes"))
    if signal == "measurable_metrics":
        return dict_present(metrics)
    if signal == "claim_limits":
        return list_present(workflow.get("claim_limits"))
    return False


def score_axis(workflow: dict[str, Any], axis: dict[str, Any]) -> dict[str, Any]:
    signals = axis["signals"]
    present = [signal for signal in signals if has_signal(workflow, signal)]
    missing = [signal for signal in signals if signal not in present]
    if len(present) == len(signals):
        score = 2
    elif present:
        score = 1
    else:
        score = 0
    return {
        "axis": axis["id"],
        "label": axis["label"],
        "score": score,
        "present_signals": present,
        "missing_signals": missing,
        "improvement_surface": missing[:],
    }


def detect_overclaim(workflow: dict[str, Any]) -> list[str]:
    text_values: list[str] = []
    for key in ["objective", "summary", "public_claim"]:
        value = workflow.get(key)
        if isinstance(value, str):
            text_values.append(value.lower())
    combined = " ".join(text_values)
    forbidden = ["external benchmark superiority", "guaranteed best quality", "always autonomous", "no human gate needed"]
    return [term for term in forbidden if term in combined]


def assess_workflow(control_id: str, workflow: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(workflow, dict):
        raise LargeWorkflowControlError("ERR_LARGE_WORKFLOW_CONTROL_INPUT_INVALID", "workflow must be an object")
    axis_scores = [score_axis(workflow, axis) for axis in AXES]
    overclaims = detect_overclaim(workflow)
    blocking_axes = [axis for axis in axis_scores if axis["score"] < 2]
    blocked_by = []
    if blocking_axes:
        blocked_by.extend({"code": "ERR_LARGE_WORKFLOW_CONTROL_AXIS_INCOMPLETE", "axis": axis["axis"], "missing": axis["missing_signals"]} for axis in blocking_axes)
    if overclaims:
        blocked_by.append({"code": "ERR_LARGE_WORKFLOW_CONTROL_OVERCLAIM", "terms": overclaims})
    status = "large-workflow-controlled" if not blocked_by else "large-workflow-blocked"
    total_score = sum(axis["score"] for axis in axis_scores)
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "control_version": CONTROL_VERSION,
        "control_id": control_id,
        "status": status,
        "axis_count": len(axis_scores),
        "total_score": total_score,
        "max_score": len(axis_scores) * 2,
        "axis_scores": axis_scores,
        "blocked_by": blocked_by,
        "next_action": "continue workflow execution" if status == "large-workflow-controlled" else "repair missing control signals before execution",
        "source_hashes": {"workflow": canonical_hash(workflow), "axes": canonical_hash(AXES)},
    }


def render_markdown(control: dict[str, Any]) -> str:
    lines = [
        f"# Large Workflow Control {control['control_id']}",
        "",
        f"- Status: `{control['status']}`",
        f"- Score: `{control['total_score']}/{control['max_score']}`",
        f"- Next action: {control['next_action']}",
        "",
        "## Axis Scores",
        "",
        "| Axis | Score | Missing Signals |",
        "| --- | ---: | --- |",
    ]
    for axis in control["axis_scores"]:
        missing = ", ".join(axis["missing_signals"]) or "none"
        lines.append(f"| {axis['label']} | {axis['score']} | {missing} |")
    if control["blocked_by"]:
        lines.extend(["", "## Blockers", ""])
        for blocker in control["blocked_by"]:
            lines.append(f"- `{blocker['code']}`: {json.dumps(blocker, sort_keys=True)}")
    lines.append("")
    return "\n".join(lines)


def write_control(out_dir: Path, control: dict[str, Any]) -> None:
    write_json_atomic(out_dir / "large-workflow-control.json", control, root=out_dir)
    write_json_atomic(
        out_dir / "status.json",
        {
            "schema_version": SCHEMA_VERSION,
            "tool": TOOL,
            "control_id": control["control_id"],
            "status": control["status"],
            "total_score": control["total_score"],
            "max_score": control["max_score"],
            "blocked_by": control["blocked_by"],
            "source_hashes": control["source_hashes"],
        },
        root=out_dir,
    )
    write_text_atomic(out_dir / "large-workflow-control.md", render_markdown(control), root=out_dir)


def run_assess(workflow_path: Path, out_dir: Path) -> dict[str, Any]:
    workflow = read_json(workflow_path)
    out_dir = resolve_out(out_dir)
    prepare_out_dir(out_dir, out_dir.name, source=workflow_path)
    control = assess_workflow(out_dir.name, workflow)
    write_control(out_dir, control)
    return control


def run_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    fixtures = manifest.get("fixtures")
    if not isinstance(fixtures, list):
        raise LargeWorkflowControlError("ERR_LARGE_WORKFLOW_CONTROL_MANIFEST_INVALID", "manifest fixtures must be a list", path=manifest_path)
    suite_id = str(manifest.get("suite_id", "v73-large-workflow-control"))
    out_dir = resolve_out(out_dir)
    prepare_out_dir(out_dir, out_dir.name, source=manifest_path)
    records = []
    for fixture in fixtures:
        if not isinstance(fixture, dict):
            raise LargeWorkflowControlError("ERR_LARGE_WORKFLOW_CONTROL_MANIFEST_INVALID", "fixture must be an object", path=manifest_path)
        fixture_id = str(fixture.get("id", "fixture"))
        workflow = fixture.get("workflow")
        if not isinstance(workflow, dict):
            raise LargeWorkflowControlError("ERR_LARGE_WORKFLOW_CONTROL_MANIFEST_INVALID", "fixture workflow must be an object", fixture_id=fixture_id)
        fixture_out = out_dir / fixture_id
        prepare_out_dir(fixture_out, fixture_id, source=manifest_path)
        control = assess_workflow(fixture_id, workflow)
        write_control(fixture_out, control)
        expected_status = fixture.get("expected_status")
        status = "pass" if expected_status in (None, control["status"]) else "fail"
        records.append(
            {
                "id": fixture_id,
                "required": bool(fixture.get("required", True)),
                "status": status,
                "control_status": control["status"],
                "total_score": control["total_score"],
                "blocked_by": control["blocked_by"],
                "error": None if status == "pass" else f"expected status {expected_status}, got {control['status']}",
            }
        )
    failed_required = [record for record in records if record["required"] and record["status"] != "pass"]
    summary = {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "suite_id": suite_id,
        "fixture_count": len(records),
        "required_fixture_count": sum(1 for record in records if record["required"]),
        "required_passed": sum(1 for record in records if record["required"] and record["status"] == "pass"),
        "passed": sum(1 for record in records if record["status"] == "pass"),
        "failed": sum(1 for record in records if record["status"] != "pass"),
        "decision": "keep" if not failed_required else "kill",
        "fixtures": records,
        "source_hashes": {"manifest": canonical_hash(manifest)},
    }
    write_json_atomic(out_dir / "summary.json", summary, root=out_dir)
    if failed_required:
        raise LargeWorkflowControlError("ERR_LARGE_WORKFLOW_CONTROL_FIXTURE_FAILED", "required control fixture failed", path=manifest_path)
    return summary


def complete_workflow() -> dict[str, Any]:
    return {
        "objective": "Carry a large repository task from user intent to verified output without direction drift.",
        "summary": "Internal control-plane assessment for a large DWM workflow.",
        "user_intent_trace": ["original objective", "non-goals", "success criteria"],
        "success_criteria": ["direction preserved", "quality verified", "human gates only for real risk"],
        "drift_checks": ["compare next action with original objective", "block unsupported public claims"],
        "phases": [
            {"id": "scope", "slice_size": "small", "depends_on": []},
            {"id": "decompose", "slice_size": "medium", "depends_on": ["scope"]},
            {"id": "execute", "slice_size": "medium", "depends_on": ["decompose"]},
            {"id": "verify", "slice_size": "small", "depends_on": ["execute"]},
        ],
        "parallelism": {"concurrency_cap": 2, "fan_in_rule": "fan in only for synthesis"},
        "verification": ["contract self-test", "independent review", "artifact hash checks"],
        "review_repair_loop": {"review": "adversarial", "repair": "bounded retry"},
        "artifact_contracts": ["workflow.plan.json", "receipt.json", "status.json"],
        "quality_gates": ["tests pass", "review passes", "claim limits pass"],
        "budget": {"max_rounds": 3, "max_retries": 1, "time_box": "large task slice"},
        "metrics": {"duration_ms": 0, "commands_run": 0, "human_interruptions": 0, "files_touched": 0},
        "automation": ["resume next safe packet", "generate control receipt"],
        "risk_gates": [{"trigger": "write/deploy/secret/external action", "safe_default": "stop and request approval"}],
        "resume": {"restart_points": ["scope", "decompose", "execute", "verify"], "invalidators": ["objective changed", "artifact hash drift"]},
        "repair_paths": ["repair failed verification", "redesign bad decomposition", "ask human at real gate"],
        "evidence": {"receipts": ["large-workflow-control.json"], "source_hashes": {"fixture": "self-test"}},
        "claim_limits": ["internal workflow control evidence only", "no external benchmark superiority"],
    }


def self_test() -> None:
    controlled = assess_workflow("self-test-ready", complete_workflow())
    if controlled["status"] != "large-workflow-controlled" or controlled["total_score"] != 12:
        raise LargeWorkflowControlError("ERR_LARGE_WORKFLOW_CONTROL_SELF_TEST_FAILED", "complete workflow should be controlled")
    incomplete = complete_workflow()
    incomplete.pop("drift_checks")
    blocked = assess_workflow("self-test-blocked", incomplete)
    if blocked["status"] != "large-workflow-blocked":
        raise LargeWorkflowControlError("ERR_LARGE_WORKFLOW_CONTROL_SELF_TEST_FAILED", "missing drift checks should block")
    overclaim = complete_workflow()
    overclaim["public_claim"] = "external benchmark superiority"
    overclaim_blocked = assess_workflow("self-test-overclaim", overclaim)
    if overclaim_blocked["status"] != "large-workflow-blocked":
        raise LargeWorkflowControlError("ERR_LARGE_WORKFLOW_CONTROL_SELF_TEST_FAILED", "overclaims should block")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="run V73 large-workflow control self-test")
    parser.add_argument("--manifest", type=Path, help="run control fixtures from a manifest")
    parser.add_argument("--out", type=Path, help="output directory under out/large-workflow-control")
    subparsers = parser.add_subparsers(dest="command")
    assess_parser = subparsers.add_parser("assess", help="assess one workflow JSON object")
    assess_parser.add_argument("--workflow", type=Path, required=True)
    assess_parser.add_argument("--out", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        if args.self_test:
            self_test()
            print("large workflow control self-test: pass")
            return
        if args.manifest:
            if args.out is None:
                raise LargeWorkflowControlError("ERR_LARGE_WORKFLOW_CONTROL_ARGS_INVALID", "--manifest requires --out")
            summary = run_manifest(args.manifest, args.out)
            print(json.dumps(summary, sort_keys=True))
            return
        if args.command == "assess":
            control = run_assess(args.workflow, args.out)
            print(json.dumps({"status": control["status"], "control_id": control["control_id"], "total_score": control["total_score"]}, sort_keys=True))
            return
        raise LargeWorkflowControlError("ERR_LARGE_WORKFLOW_CONTROL_ARGS_INVALID", "choose --self-test, --manifest, or assess")
    except LargeWorkflowControlError as exc:
        print(json.dumps({"status": "error", "error": exc.to_record()}, sort_keys=True), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
