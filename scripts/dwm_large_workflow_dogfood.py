#!/usr/bin/env python3
"""V74 dogfood receipt for V73 large-workflow control."""

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
from dwm_large_workflow_control import assess_workflow  # noqa: E402


TOOL = "dwm_large_workflow_dogfood.py"
SCHEMA_VERSION = "1.0"
DOGFOOD_CONTROL_VERSION = "74.0.0"
DOGFOOD_CONTROL_ROOT = ROOT / "out" / "large-workflow-dogfood"
DEFAULT_RUN = ROOT / "out" / "v9" / "v32-semantic-dogfood"
SENTINEL = ".dwm_large_workflow_dogfood-owned.json"


class LargeWorkflowDogfoodError(ValueError):
    """Structured V74 large-workflow dogfood failure."""

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
        raise LargeWorkflowDogfoodError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise LargeWorkflowDogfoodError(code, "path contains a symlink", path=current)


def resolve_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_LARGE_WORKFLOW_DOGFOOD_PATH_UNSAFE", message="dogfood control output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = DOGFOOD_CONTROL_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise LargeWorkflowDogfoodError("ERR_LARGE_WORKFLOW_DOGFOOD_PATH_UNSAFE", f"dogfood control output must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise LargeWorkflowDogfoodError("ERR_LARGE_WORKFLOW_DOGFOOD_PATH_UNSAFE", "dogfood control output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_LARGE_WORKFLOW_DOGFOOD_PATH_SYMLINK")
    return resolved


def resolve_run(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_LARGE_WORKFLOW_DOGFOOD_RUN_UNSAFE", message="dogfood run path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    out_resolved = (ROOT / "out").resolve(strict=False)
    try:
        resolved.relative_to(out_resolved)
    except ValueError as exc:
        raise LargeWorkflowDogfoodError("ERR_LARGE_WORKFLOW_DOGFOOD_RUN_UNSAFE", "dogfood run must resolve under out", path=value) from exc
    check_components_not_symlink(candidate, code="ERR_LARGE_WORKFLOW_DOGFOOD_PATH_SYMLINK")
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


def prepare_out_dir(path: Path, dogfood_id: str, *, source: Path | str) -> None:
    if path.exists():
        if path.is_symlink():
            raise LargeWorkflowDogfoodError("ERR_LARGE_WORKFLOW_DOGFOOD_PATH_SYMLINK", "dogfood control output is a symlink", path=path)
        if not path.is_dir():
            raise LargeWorkflowDogfoodError("ERR_LARGE_WORKFLOW_DOGFOOD_PATH_UNSAFE", "dogfood control output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("dogfood_id") != dogfood_id:
            raise LargeWorkflowDogfoodError("ERR_LARGE_WORKFLOW_DOGFOOD_PATH_UNSAFE", "existing dogfood control output is not dogfood-owned", path=path)
        shutil.rmtree(path)
    DOGFOOD_CONTROL_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(
        path / SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "dogfood_control_version": DOGFOOD_CONTROL_VERSION,
            "dogfood_id": dogfood_id,
            "source_path": str(source),
            "created_at": now_utc(),
        },
        root=path,
    )


def completed_phases(status: dict[str, Any]) -> list[str]:
    values = status.get("completed_phase_ids", [])
    return [str(value) for value in values] if isinstance(values, list) else []


def phase_records(status: dict[str, Any]) -> list[dict[str, Any]]:
    phases = completed_phases(status)
    if not phases:
        phases = ["scope", "execute", "verify"]
    records = []
    for index, phase_id in enumerate(phases):
        if index == 0:
            depends_on: list[str] = []
        else:
            depends_on = [phases[index - 1]]
        records.append(
            {
                "id": phase_id,
                "slice_size": "small" if phase_id in {"human_gate", "scope", "verify"} else "medium",
                "depends_on": depends_on,
            }
        )
    return records


def dogfood_blockers(status: dict[str, Any]) -> list[dict[str, Any]]:
    blockers = []
    if status.get("status") != "workflow-complete":
        blockers.append({"code": "ERR_LARGE_WORKFLOW_DOGFOOD_NOT_COMPLETE", "message": "dogfood run is not workflow-complete"})
    if status.get("resume_state") != "resumable":
        blockers.append({"code": "ERR_LARGE_WORKFLOW_DOGFOOD_NOT_RESUMABLE", "message": "dogfood run is not resumable"})
    invalidators = status.get("invalidators", [])
    if isinstance(invalidators, list) and invalidators:
        blockers.append({"code": "ERR_LARGE_WORKFLOW_DOGFOOD_INVALIDATED", "message": "dogfood run has invalidators", "details": invalidators})
    human_approved = status.get("human_approved_phase_ids", [])
    if "human_gate" not in human_approved:
        blockers.append({"code": "ERR_LARGE_WORKFLOW_DOGFOOD_HUMAN_GATE_MISSING", "message": "dogfood human_gate approval is missing"})
    snapshots = status.get("snapshots")
    if not isinstance(snapshots, dict) or not snapshots:
        blockers.append({"code": "ERR_LARGE_WORKFLOW_DOGFOOD_SNAPSHOTS_MISSING", "message": "dogfood source hashes are missing"})
    return blockers


def workflow_from_status(status: dict[str, Any], *, run_path: str) -> dict[str, Any]:
    phases = phase_records(status)
    reviewed = status.get("reviewed_phase_ids", [])
    snapshots = status.get("snapshots", {})
    return {
        "objective": "Use DWM dogfood evidence to prove a large workflow can preserve direction, quality, efficiency, recovery, and evidence before more graph or benchmark promotion.",
        "summary": "Internal large-workflow dogfood control receipt.",
        "user_intent_trace": [
            "large work should follow user intent",
            "quality and efficiency matter",
            "human gates only when risk is real",
        ],
        "success_criteria": [
            "workflow-complete dogfood status",
            "human gate approved when required",
            "no invalidators",
            "source hashes present",
        ],
        "drift_checks": [
            "status must be workflow-complete",
            "selected phases must be empty after completion",
            "invalidators must be empty",
        ],
        "phases": phases,
        "parallelism": {"concurrency_cap": 2, "fan_in_rule": "fan in only after evidence review and release decision"},
        "verification": ["status.json checked", "source hashes checked", "V73 control evaluator applied"],
        "review_repair_loop": {"reviewed_phase_ids": reviewed, "repair": "block and repair stale or incomplete dogfood evidence"},
        "artifact_contracts": ["status.json", "state.json", "run.json", "hashes.json", "human-approval.md"],
        "quality_gates": ["workflow-complete", "resumable", "no invalidators", "human_gate approved"],
        "budget": {"max_rounds": 1, "max_retries": 1, "time_box": "one dogfood control receipt"},
        "metrics": {
            "completed_phase_count": len(completed_phases(status)),
            "reviewed_phase_count": len(reviewed) if isinstance(reviewed, list) else 0,
            "human_interruptions": 1 if "human_gate" in status.get("human_approved_phase_ids", []) else 0,
            "invalidator_count": len(status.get("invalidators", [])) if isinstance(status.get("invalidators", []), list) else 0,
        },
        "automation": ["derive V73 control workflow from dogfood status", "write dogfood-control receipt"],
        "risk_gates": [{"trigger": "dogfood human gate or stale evidence", "safe_default": "stop before continuing and ask for approval"}],
        "resume": {
            "restart_points": [phase["id"] for phase in phases],
            "invalidators": ["status changed", "snapshot hash drift", "human approval missing"],
        },
        "repair_paths": ["rerun dogfood replay", "refresh stale status", "request human approval at real gate"],
        "evidence": {
            "receipts": [f"{run_path}/status.json", f"{run_path}/hashes.json", "dogfood-control.json"],
            "source_hashes": snapshots if isinstance(snapshots, dict) else {},
        },
        "claim_limits": ["local dogfood control evidence only", "no external benchmark superiority", "no fully autonomous completion claim"],
    }


def render_markdown(receipt: dict[str, Any]) -> str:
    lines = [
        f"# Large Workflow Dogfood {receipt['dogfood_id']}",
        "",
        f"- Status: `{receipt['status']}`",
        f"- Run path: `{receipt['run_path']}`",
        f"- Control status: `{receipt['control']['status']}`",
        f"- Control score: `{receipt['control']['total_score']}/{receipt['control']['max_score']}`",
        f"- Dogfood blockers: `{len(receipt['blocked_by'])}`",
        "",
        "## Blockers",
        "",
    ]
    if receipt["blocked_by"]:
        for blocker in receipt["blocked_by"]:
            lines.append(f"- `{blocker['code']}`: {blocker['message']}")
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def make_receipt(dogfood_id: str, status: dict[str, Any], *, run_path: str) -> dict[str, Any]:
    workflow = workflow_from_status(status, run_path=run_path)
    control = assess_workflow(dogfood_id, workflow)
    blockers = dogfood_blockers(status)
    if control["status"] != "large-workflow-controlled":
        blockers.extend(control["blocked_by"])
    final_status = "dogfood-control-recorded" if not blockers else "dogfood-control-blocked"
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "dogfood_control_version": DOGFOOD_CONTROL_VERSION,
        "dogfood_id": dogfood_id,
        "status": final_status,
        "run_path": run_path,
        "run_status": status,
        "workflow": workflow,
        "control": control,
        "blocked_by": blockers,
        "source_hashes": {"run_status": canonical_hash(status), "workflow": canonical_hash(workflow), "control": canonical_hash(control)},
    }


def write_receipt(out_dir: Path, receipt: dict[str, Any]) -> None:
    write_json_atomic(out_dir / "dogfood-control.json", receipt, root=out_dir)
    write_json_atomic(out_dir / "large-workflow-control.json", receipt["control"], root=out_dir)
    write_json_atomic(
        out_dir / "status.json",
        {
            "schema_version": SCHEMA_VERSION,
            "tool": TOOL,
            "dogfood_id": receipt["dogfood_id"],
            "status": receipt["status"],
            "control_status": receipt["control"]["status"],
            "control_score": receipt["control"]["total_score"],
            "blocked_by": receipt["blocked_by"],
            "source_hashes": receipt["source_hashes"],
        },
        root=out_dir,
    )
    write_text_atomic(out_dir / "dogfood-control.md", render_markdown(receipt), root=out_dir)


def record_run(run_path: Path, out_dir: Path) -> dict[str, Any]:
    run_path = resolve_run(run_path)
    status_path = run_path / "status.json"
    if not status_path.is_file() or status_path.is_symlink():
        raise LargeWorkflowDogfoodError("ERR_LARGE_WORKFLOW_DOGFOOD_STATUS_MISSING", "dogfood status is missing", path=status_path)
    status = read_json(status_path)
    out_dir = resolve_out(out_dir)
    prepare_out_dir(out_dir, out_dir.name, source=run_path)
    receipt = make_receipt(out_dir.name, status, run_path=rel(run_path))
    write_receipt(out_dir, receipt)
    return receipt


def run_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    fixtures = manifest.get("fixtures")
    if not isinstance(fixtures, list):
        raise LargeWorkflowDogfoodError("ERR_LARGE_WORKFLOW_DOGFOOD_MANIFEST_INVALID", "manifest fixtures must be a list", path=manifest_path)
    suite_id = str(manifest.get("suite_id", "v74-large-workflow-dogfood"))
    out_dir = resolve_out(out_dir)
    prepare_out_dir(out_dir, out_dir.name, source=manifest_path)
    records = []
    for fixture in fixtures:
        if not isinstance(fixture, dict):
            raise LargeWorkflowDogfoodError("ERR_LARGE_WORKFLOW_DOGFOOD_MANIFEST_INVALID", "fixture must be an object", path=manifest_path)
        fixture_id = str(fixture.get("id", "fixture"))
        status = fixture.get("run_status")
        if not isinstance(status, dict):
            raise LargeWorkflowDogfoodError("ERR_LARGE_WORKFLOW_DOGFOOD_MANIFEST_INVALID", "fixture run_status must be an object", fixture_id=fixture_id)
        fixture_out = out_dir / fixture_id
        prepare_out_dir(fixture_out, fixture_id, source=manifest_path)
        receipt = make_receipt(fixture_id, status, run_path=str(fixture.get("run_path", "fixture-run")))
        write_receipt(fixture_out, receipt)
        expected_status = fixture.get("expected_status")
        status_result = "pass" if expected_status in (None, receipt["status"]) else "fail"
        records.append(
            {
                "id": fixture_id,
                "required": bool(fixture.get("required", True)),
                "status": status_result,
                "dogfood_status": receipt["status"],
                "control_status": receipt["control"]["status"],
                "blocked_by": receipt["blocked_by"],
                "error": None if status_result == "pass" else f"expected status {expected_status}, got {receipt['status']}",
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
        raise LargeWorkflowDogfoodError("ERR_LARGE_WORKFLOW_DOGFOOD_FIXTURE_FAILED", "required dogfood control fixture failed", path=manifest_path)
    return summary


def ready_status() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "run_id": "fixture-dogfood",
        "status": "workflow-complete",
        "resume_state": "resumable",
        "completed_phase_ids": ["release_inventory", "evidence_review", "release_decision", "human_gate"],
        "reviewed_phase_ids": ["evidence_review", "release_decision"],
        "human_approved_phase_ids": ["human_gate"],
        "selected_phase_ids": [],
        "invalidators": [],
        "snapshots": {"run_hash": "fixture-run", "state_hash": "fixture-state", "journal_hash": "fixture-journal"},
    }


def self_test() -> None:
    ready = make_receipt("self-test-ready", ready_status(), run_path="fixture-run")
    if ready["status"] != "dogfood-control-recorded":
        raise LargeWorkflowDogfoodError("ERR_LARGE_WORKFLOW_DOGFOOD_SELF_TEST_FAILED", "ready dogfood status should record")
    missing_gate = ready_status()
    missing_gate["human_approved_phase_ids"] = []
    blocked = make_receipt("self-test-missing-gate", missing_gate, run_path="fixture-run")
    if blocked["status"] != "dogfood-control-blocked":
        raise LargeWorkflowDogfoodError("ERR_LARGE_WORKFLOW_DOGFOOD_SELF_TEST_FAILED", "missing human gate should block")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="run V74 dogfood control self-test")
    parser.add_argument("--manifest", type=Path, help="run dogfood control fixtures from a manifest")
    parser.add_argument("--out", type=Path, help="output directory under out/large-workflow-dogfood")
    subparsers = parser.add_subparsers(dest="command")
    record_parser = subparsers.add_parser("record", help="record V73 control receipt for a dogfood run")
    record_parser.add_argument("--run", type=Path, default=DEFAULT_RUN)
    record_parser.add_argument("--out", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        if args.self_test:
            self_test()
            print("large workflow dogfood self-test: pass")
            return
        if args.manifest:
            if args.out is None:
                raise LargeWorkflowDogfoodError("ERR_LARGE_WORKFLOW_DOGFOOD_ARGS_INVALID", "--manifest requires --out")
            summary = run_manifest(args.manifest, args.out)
            print(json.dumps(summary, sort_keys=True))
            return
        if args.command == "record":
            receipt = record_run(args.run, args.out)
            print(json.dumps({"status": receipt["status"], "dogfood_id": receipt["dogfood_id"], "control_status": receipt["control"]["status"]}, sort_keys=True))
            return
        raise LargeWorkflowDogfoodError("ERR_LARGE_WORKFLOW_DOGFOOD_ARGS_INVALID", "choose --self-test, --manifest, or record")
    except LargeWorkflowDogfoodError as exc:
        print(json.dumps({"status": "error", "error": exc.to_record()}, sort_keys=True), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
