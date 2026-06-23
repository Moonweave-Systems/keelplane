#!/usr/bin/env python3
"""Prepare deterministic V4 parallel scheduling packets from trusted V3 state."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from compile_workflow import (  # noqa: E402
    canonical_hash,
    canonical_json_text,
    compile_plan,
    read_json,
    sha256_text,
    write_text_atomic,
)
from execute_packet import execute_local_shell, git_text, review_execution, worktree_path, write_json as write_exec_json  # noqa: E402
from run_workflow import start_runtime  # noqa: E402


TOOL = "orchestrate_workflow.py"
SCHEMA_VERSION = "1.0"
ORCHESTRATOR_VERSION = "0.1.0"
V1_OUT_ROOT = ROOT / "out" / "v1"
V2_OUT_ROOT = ROOT / "out" / "v2"
V3_OUT_ROOT = ROOT / "out" / "v3"
V4_OUT_ROOT = ROOT / "out" / "v4"
SENTINEL = ".orchestrate_workflow-owned.json"
V3_SENTINEL = ".run_workflow-owned.json"


class OrchestrateError(ValueError):
    """Structured V4 orchestration failure."""

    def __init__(self, code: str, message: str, *, path: Path | str | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.path = str(path) if path is not None else None

    def to_record(self) -> dict[str, Any]:
        record: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.path is not None:
            record["path"] = self.path
        return record


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def rel(path: Path) -> str:
    resolved = path.resolve(strict=False)
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return str(resolved)


def reject_traversal(path: Path, code: str, message: str) -> None:
    if any(part == ".." for part in path.parts):
        raise OrchestrateError(code, message, path=path)


def check_components_not_symlink(path: Path, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise OrchestrateError(code, "path contains a symlink", path=current)


def resolve_under_out(value: str | Path, root: Path, *, label: str) -> Path:
    raw = Path(value)
    reject_traversal(raw, "ERR_ORCH_OUTSIDE_REPO", f"{label} path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    out_root = root.resolve(strict=False)
    forbidden = {ROOT.resolve(), (ROOT / "out").resolve(strict=False), out_root}
    if resolved in forbidden:
        raise OrchestrateError("ERR_ORCH_OUTSIDE_REPO", f"{label} path must name a run directory", path=value)
    try:
        resolved.relative_to(out_root)
    except ValueError as exc:
        raise OrchestrateError("ERR_ORCH_OUTSIDE_REPO", f"{label} path must resolve under {out_root}", path=value) from exc
    check_components_not_symlink(candidate, "ERR_ORCH_DIR_SYMLINK")
    return resolved


def resolve_v3_dir(value: str | Path) -> Path:
    return resolve_under_out(value, V3_OUT_ROOT, label="V3 runtime")


def resolve_v4_out(value: str | Path) -> Path:
    return resolve_under_out(value, V4_OUT_ROOT, label="V4 output")


def ensure_contained(root: Path, path: Path) -> None:
    target = path if path.is_absolute() else root / path
    reject_traversal(path, "ERR_ORCH_OUTSIDE_REPO", "artifact path escapes owned directory")
    try:
        target.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError as exc:
        raise OrchestrateError("ERR_ORCH_OUTSIDE_REPO", "artifact path escapes owned directory", path=target) from exc


def ensure_artifact_parent(root: Path, path: Path) -> None:
    ensure_contained(root, path)
    current = root.resolve(strict=False)
    for part in path.resolve(strict=False).relative_to(current).parent.parts:
        current = current / part
        if current.exists():
            if current.is_symlink():
                raise OrchestrateError("ERR_ORCH_DIR_SYMLINK", "artifact parent is symlinked", path=current)
            if not current.is_dir():
                raise OrchestrateError("ERR_ORCH_OUTSIDE_REPO", "artifact parent is not a directory", path=current)
        else:
            current.mkdir()


def ensure_leaf_not_symlink(path: Path) -> None:
    if path.exists():
        if path.is_symlink():
            raise OrchestrateError("ERR_ORCH_LEAF_SYMLINK", "refusing to overwrite symlinked file", path=path)
        if not path.is_file():
            raise OrchestrateError("ERR_ORCH_OUTSIDE_REPO", "refusing to overwrite non-file leaf", path=path)


def write_text(path: Path, text: str, *, root: Path) -> None:
    ensure_artifact_parent(root, path)
    ensure_leaf_not_symlink(path)
    write_text_atomic(path, text, root=root)


def write_json(path: Path, data: Any, *, root: Path) -> None:
    write_text(path, canonical_json_text(data), root=root)


def read_json_obj(path: Path, *, code: str, label: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise OrchestrateError(code, f"{label} is missing or symlinked", path=path)
    try:
        data = json.loads(path.read_text())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OrchestrateError(code, f"{label} is malformed: {exc}", path=path) from exc
    if not isinstance(data, dict):
        raise OrchestrateError(code, f"{label} root must be an object", path=path)
    return data


def read_sentinel(path: Path, name: str = SENTINEL) -> dict[str, Any] | None:
    sentinel = path / name
    if not sentinel.is_file() or sentinel.is_symlink():
        return None
    try:
        data = json.loads(sentinel.read_text())
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def sentinel_payload(run_id: str, v3_dir: Path) -> dict[str, Any]:
    return {
        "tool": TOOL,
        "schema_version": SCHEMA_VERSION,
        "orchestrator_version": ORCHESTRATOR_VERSION,
        "run_id": run_id,
        "v3_run_path": rel(v3_dir),
        "created_at": now_utc(),
    }


def ensure_v4_dir(path: Path, run_id: str, v3_dir: Path) -> None:
    path = resolve_v4_out(path)
    if path.exists():
        if path.is_symlink():
            raise OrchestrateError("ERR_ORCH_DIR_SYMLINK", "V4 output directory is a symlink", path=path)
        if not path.is_dir():
            raise OrchestrateError("ERR_ORCH_OUTSIDE_REPO", "V4 output exists and is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None:
            raise OrchestrateError("ERR_ORCH_ARTIFACT_MALFORMED", "existing V4 output is not orchestrator-owned", path=path)
        if sentinel.get("tool") != TOOL or sentinel.get("run_id") != run_id or sentinel.get("v3_run_path") != rel(v3_dir):
            raise OrchestrateError("ERR_ORCH_ARTIFACT_MALFORMED", "existing V4 output sentinel does not match this run", path=path)
    path.mkdir(parents=True, exist_ok=True)
    if read_sentinel(path) is None:
        write_json(path / SENTINEL, sentinel_payload(run_id, v3_dir), root=path)


def trusted_v3_context(v3_dir: Path) -> dict[str, Any]:
    v3_dir = resolve_v3_dir(v3_dir)
    run = read_json_obj(v3_dir / "run.json", code="ERR_ORCH_UNTRUSTED_V3", label="V3 run.json")
    status = read_json_obj(v3_dir / "status.json", code="ERR_ORCH_UNTRUSTED_V3", label="V3 status.json")
    run_id = run.get("run_id")
    if not isinstance(run_id, str) or run_id != v3_dir.name:
        raise OrchestrateError("ERR_ORCH_UNTRUSTED_V3", "V3 run_id must match directory", path=v3_dir / "run.json")
    sentinel = read_sentinel(v3_dir, V3_SENTINEL)
    if sentinel is None or sentinel.get("tool") != "run_workflow.py" or sentinel.get("run_id") != run_id:
        raise OrchestrateError("ERR_ORCH_UNTRUSTED_V3", "V3 ownership sentinel is missing or mismatched", path=v3_dir / V3_SENTINEL)
    if status.get("status") != "advanced":
        raise OrchestrateError("ERR_ORCH_ENTRY_REJECTED", "V4 requires advanced V3 status", path=v3_dir / "status.json")
    next_paths = run.get("next_packet_paths")
    if not isinstance(next_paths, list) or next_paths != ["next/0001.packet.json"]:
        raise OrchestrateError("ERR_ORCH_UNTRUSTED_V3", "V3 next packet paths are unsupported", path=v3_dir / "run.json")
    packet = read_json_obj(v3_dir / "next" / "0001.packet.json", code="ERR_ORCH_UNTRUSTED_V3", label="V3 next packet")
    expected_packet_hash = status.get("snapshots", {}).get("next_packet_hash") if isinstance(status.get("snapshots"), dict) else None
    if expected_packet_hash != canonical_hash(packet):
        raise OrchestrateError("ERR_ORCH_STALE_V3", "V3 next packet does not match status snapshot", path=v3_dir / "next" / "0001.packet.json")
    v1_path = status.get("v1_run_path")
    if not isinstance(v1_path, str):
        raise OrchestrateError("ERR_ORCH_UNTRUSTED_V3", "V3 status is missing v1_run_path", path=v3_dir / "status.json")
    v1_dir = (ROOT / v1_path).resolve(strict=False)
    try:
        v1_dir.relative_to(V1_OUT_ROOT.resolve(strict=False))
    except ValueError as exc:
        raise OrchestrateError("ERR_ORCH_UNTRUSTED_V3", "V1 run path escapes out/v1", path=v1_path) from exc
    plan = read_json_obj(v1_dir / "plan.snapshot.json", code="ERR_ORCH_UNTRUSTED_V3", label="V1 plan snapshot")
    expected_plan_hash = status.get("snapshots", {}).get("plan_snapshot_hash") if isinstance(status.get("snapshots"), dict) else None
    if expected_plan_hash != canonical_hash(plan):
        raise OrchestrateError("ERR_ORCH_STALE_V3", "V1 plan snapshot does not match V3 status", path=v1_dir / "plan.snapshot.json")
    return {"v3_dir": v3_dir, "run": run, "status": status, "v3_packet": packet, "v1_dir": v1_dir, "plan": plan}


def phase_index(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    phases = plan.get("phases")
    if not isinstance(phases, list) or not phases:
        raise OrchestrateError("ERR_ORCH_PLAN_MALFORMED", "plan has no phases")
    indexed: dict[str, dict[str, Any]] = {}
    for phase in phases:
        if not isinstance(phase, dict) or not isinstance(phase.get("id"), str):
            raise OrchestrateError("ERR_ORCH_PLAN_MALFORMED", "phase is malformed")
        indexed[phase["id"]] = phase
    return indexed


def worker_index(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    workers = plan.get("workers")
    if not isinstance(workers, list):
        raise OrchestrateError("ERR_ORCH_PLAN_MALFORMED", "plan workers must be a list")
    indexed: dict[str, dict[str, Any]] = {}
    for worker in workers:
        if not isinstance(worker, dict) or not isinstance(worker.get("id"), str):
            raise OrchestrateError("ERR_ORCH_PLAN_MALFORMED", "worker is malformed")
        indexed[worker["id"]] = worker
    return indexed


def concurrency_cap(plan: dict[str, Any]) -> int:
    parallelism = plan.get("parallelism")
    if isinstance(parallelism, dict) and isinstance(parallelism.get("concurrency_cap"), int):
        return max(1, parallelism["concurrency_cap"])
    return 1


def incoming_handoffs(plan: dict[str, Any], phase_id: str) -> list[dict[str, Any]]:
    handoffs = plan.get("handoffs")
    if not isinstance(handoffs, list):
        return []
    return [item for item in handoffs if isinstance(item, dict) and item.get("to_phase") == phase_id]


def build_packet(
    *,
    index: int,
    phase: dict[str, Any],
    workers: list[dict[str, Any]],
    handoffs: list[dict[str, Any]],
    context: dict[str, Any],
    source_hashes: dict[str, str],
) -> dict[str, Any]:
    phase_id = phase["id"]
    return {
        "schema_version": SCHEMA_VERSION,
        "orchestrator_version": ORCHESTRATOR_VERSION,
        "packet_id": f"v4-parallel-{index:04d}-{phase_id}",
        "packet_index": index,
        "source_plan_id": context["plan"].get("plan_id"),
        "objective": context["plan"].get("objective"),
        "phase_id": phase_id,
        "phase_name": phase.get("name", phase_id),
        "depends_on": phase.get("depends_on", []),
        "entry_criteria": phase.get("entry_criteria", []),
        "exit_criteria": phase.get("exit_criteria", []),
        "expected_outputs": phase.get("outputs", []),
        "worker_ids": phase.get("worker_ids", []),
        "workers": workers,
        "handoff_inputs": handoffs,
        "stop_conditions": [
            "do not execute this packet in V4 scheduler",
            "return execution evidence through V2 and V2.5 before advancing",
            "stop before destructive, external, costly, production, secret, dependency, database, public API, delete, or history-rewrite actions",
        ],
        "source_hashes": source_hashes,
    }


def render_packet_prompt(packet: dict[str, Any]) -> str:
    lines = [
        "# V4 Parallel Packet",
        "",
        f"Packet: `{packet['packet_id']}`",
        f"Phase: `{packet['phase_id']}`",
        "",
        "## Objective",
        "",
        str(packet.get("objective", "")),
        "",
        "## Expected Outputs",
    ]
    for output in packet.get("expected_outputs", []):
        lines.append(f"- {output}")
    lines.extend(["", "## Workers"])
    for worker in packet.get("workers", []):
        lines.append(f"- `{worker.get('id')}` {worker.get('role')}")
    lines.extend(["", "## Stop Conditions"])
    for item in packet.get("stop_conditions", []):
        lines.append(f"- {item}")
    return "\n".join(lines) + "\n"


def build_schedule(context: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    plan = context["plan"]
    packet = context["v3_packet"]
    completed = packet.get("completed_phase_ids")
    if not isinstance(completed, list) or not all(isinstance(item, str) for item in completed):
        raise OrchestrateError("ERR_ORCH_ENTRY_REJECTED", "V3 packet has malformed completed_phase_ids")
    completed_set = set(completed)
    phases = plan.get("phases")
    if not isinstance(phases, list):
        raise OrchestrateError("ERR_ORCH_PLAN_MALFORMED", "plan phases must be a list")
    workers_by_id = worker_index(plan)
    source_hashes = {
        "v3_status_hash": canonical_hash(context["status"]),
        "v3_next_packet_hash": canonical_hash(packet),
        "v1_plan_snapshot_hash": canonical_hash(plan),
    }
    ready: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for phase in phases:
        if not isinstance(phase, dict) or not isinstance(phase.get("id"), str):
            raise OrchestrateError("ERR_ORCH_PLAN_MALFORMED", "phase is malformed")
        phase_id = phase["id"]
        if phase_id in completed_set:
            continue
        depends_on = phase.get("depends_on")
        worker_ids = phase.get("worker_ids")
        if not isinstance(depends_on, list) or not all(isinstance(item, str) for item in depends_on):
            raise OrchestrateError("ERR_ORCH_PLAN_MALFORMED", "phase depends_on is malformed")
        if not isinstance(worker_ids, list) or not all(isinstance(item, str) for item in worker_ids):
            raise OrchestrateError("ERR_ORCH_PLAN_MALFORMED", "phase worker_ids is malformed")
        unknown = [worker_id for worker_id in worker_ids if worker_id not in workers_by_id]
        if unknown:
            raise OrchestrateError("ERR_ORCH_PLAN_MALFORMED", f"phase references unknown worker: {unknown[0]}")
        unmet = [dep for dep in depends_on if dep not in completed_set]
        if unmet:
            blocked.append({"phase_id": phase_id, "unmet_dependencies": unmet})
        else:
            ready.append(phase)
    cap = concurrency_cap(plan)
    selected = ready[:cap]
    packets = []
    prompts = []
    for index, phase in enumerate(selected, start=1):
        worker_defs = [workers_by_id[worker_id] for worker_id in phase.get("worker_ids", [])]
        phase_packet = build_packet(
            index=index,
            phase=phase,
            workers=worker_defs,
            handoffs=incoming_handoffs(plan, phase["id"]),
            context=context,
            source_hashes=source_hashes,
        )
        packets.append(phase_packet)
        prompts.append(render_packet_prompt(phase_packet))
    schedule = {
        "schema_version": SCHEMA_VERSION,
        "orchestrator_version": ORCHESTRATOR_VERSION,
        "source_plan_id": plan.get("plan_id"),
        "completed_phase_ids": completed,
        "ready_phase_ids": [phase["id"] for phase in ready],
        "selected_phase_ids": [phase["id"] for phase in selected],
        "blocked_phases": blocked,
        "concurrency_cap": cap,
        "source_hashes": source_hashes,
        "packet_hashes": {packets[index]["packet_id"]: canonical_hash(packets[index]) for index in range(len(packets))},
        "prompt_hashes": {packets[index]["packet_id"]: sha256_text(prompts[index]) for index in range(len(packets))},
    }
    if not selected:
        raise OrchestrateError("ERR_ORCH_NO_READY_PHASE", "no ready phases are available")
    return schedule, packets, prompts


def journal_entry(context: dict[str, Any], schedule: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "orchestrator_version": ORCHESTRATOR_VERSION,
        "event_id": "0000",
        "event": "v4-schedule-created",
        "created_at": now_utc(),
        "v3_run_path": rel(context["v3_dir"]),
        "selected_phase_ids": schedule["selected_phase_ids"],
        "source_hashes": schedule["source_hashes"],
    }


def build_status(
    run_id: str,
    *,
    context: dict[str, Any] | None,
    schedule: dict[str, Any] | None,
    journal: dict[str, Any] | None,
    status: str,
    resume_state: str,
    invalidators: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    snapshots: dict[str, Any] = {}
    if schedule is not None:
        snapshots["schedule_hash"] = canonical_hash(schedule)
        snapshots["packet_hashes"] = schedule.get("packet_hashes", {})
        snapshots["prompt_hashes"] = schedule.get("prompt_hashes", {})
    if journal is not None:
        snapshots["journal_hash"] = canonical_hash(journal)
    if context is not None:
        snapshots["v3_status_hash"] = canonical_hash(context["status"])
        snapshots["v3_next_packet_hash"] = canonical_hash(context["v3_packet"])
        snapshots["v1_plan_snapshot_hash"] = canonical_hash(context["plan"])
    return {
        "schema_version": SCHEMA_VERSION,
        "orchestrator_version": ORCHESTRATOR_VERSION,
        "run_id": run_id,
        "status": status,
        "resume_state": resume_state,
        "selected_phase_ids": schedule.get("selected_phase_ids", []) if schedule else [],
        "ready_phase_ids": schedule.get("ready_phase_ids", []) if schedule else [],
        "invalidators": invalidators or [],
        "schedule_path": "schedule.json" if schedule else None,
        "journal_path": "journal/0000.json" if journal else None,
        "snapshots": snapshots,
        "checked_at": now_utc(),
    }


def render_resume(status: dict[str, Any]) -> str:
    lines = [
        "# V4 Resume",
        "",
        f"Run: `{status['run_id']}`",
        f"Status: `{status['status']}`",
        f"Resume state: `{status['resume_state']}`",
        "",
        "## Selected Phases",
    ]
    for phase_id in status.get("selected_phase_ids", []):
        lines.append(f"- `{phase_id}`")
    if status.get("invalidators"):
        lines.extend(["", "## Invalidators"])
        for item in status["invalidators"]:
            lines.append(f"- `{item.get('code')}` {item.get('message')}")
    return "\n".join(lines) + "\n"


def write_status(out_dir: Path, status: dict[str, Any]) -> None:
    write_json(out_dir / "status.json", status, root=out_dir)
    write_text(out_dir / "resume.md", render_resume(status), root=out_dir)


def write_error_status(out_dir: Path, run_id: str, v3_dir: Path, error: OrchestrateError) -> dict[str, Any]:
    ensure_v4_dir(out_dir, run_id, v3_dir)
    status = build_status(run_id, context=None, schedule=None, journal=None, status="blocked", resume_state="invalid", invalidators=[error.to_record()])
    write_status(out_dir, status)
    return status


def start_orchestration(v3_dir: Path, *, out_dir: Path | None = None) -> dict[str, Any]:
    v3_dir = resolve_v3_dir(v3_dir)
    out_dir = resolve_v4_out(out_dir) if out_dir is not None else V4_OUT_ROOT / v3_dir.name
    run_id = out_dir.name
    try:
        context = trusted_v3_context(v3_dir)
        ensure_v4_dir(out_dir, run_id, v3_dir)
        schedule, packets, prompts = build_schedule(context)
        journal = journal_entry(context, schedule)
        run = {
            "schema_version": SCHEMA_VERSION,
            "orchestrator_version": ORCHESTRATOR_VERSION,
            "run_id": run_id,
            "created_at": now_utc(),
            "v3_run_path": rel(v3_dir),
            "schedule_path": "schedule.json",
            "packet_paths": [f"packets/{packet['packet_index']:04d}.{packet['phase_id']}.packet.json" for packet in packets],
            "journal_paths": ["journal/0000.json"],
        }
        status = build_status(run_id, context=context, schedule=schedule, journal=journal, status="scheduled", resume_state="fresh")
    except OrchestrateError as exc:
        status = write_error_status(out_dir, run_id, v3_dir, exc)
        return {"status": status, "out_dir": out_dir}
    write_json(out_dir / "run.json", run, root=out_dir)
    write_json(out_dir / "schedule.json", schedule, root=out_dir)
    for packet, prompt in zip(packets, prompts, strict=True):
        stem = f"{packet['packet_index']:04d}.{packet['phase_id']}"
        write_json(out_dir / "packets" / f"{stem}.packet.json", packet, root=out_dir)
        write_text(out_dir / "packets" / f"{stem}.prompt.md", prompt, root=out_dir)
    write_json(out_dir / "journal" / "0000.json", journal, root=out_dir)
    write_status(out_dir, status)
    return {"status": status, "out_dir": out_dir, "schedule": schedule, "packets": packets}


def validate_v4_sentinel(run_dir: Path, run_id: str, v3_dir: Path) -> None:
    sentinel = read_sentinel(run_dir)
    if sentinel is None:
        raise OrchestrateError("ERR_ORCH_ARTIFACT_MALFORMED", "V4 output is missing ownership sentinel", path=run_dir / SENTINEL)
    if sentinel.get("tool") != TOOL or sentinel.get("run_id") != run_id or sentinel.get("v3_run_path") != rel(v3_dir):
        raise OrchestrateError("ERR_ORCH_ARTIFACT_MALFORMED", "V4 ownership sentinel does not match run.json", path=run_dir / SENTINEL)


def resume_orchestration(run_dir: Path) -> dict[str, Any]:
    run_dir = resolve_v4_out(run_dir)
    run = read_json_obj(run_dir / "run.json", code="ERR_ORCH_ARTIFACT_MALFORMED", label="run.json")
    run_id = run.get("run_id")
    if not isinstance(run_id, str) or run_id != run_dir.name:
        raise OrchestrateError("ERR_ORCH_ARTIFACT_MALFORMED", "run.json run_id must match V4 directory", path=run_dir / "run.json")
    v3_path = run.get("v3_run_path")
    if not isinstance(v3_path, str):
        raise OrchestrateError("ERR_ORCH_ARTIFACT_MALFORMED", "run.json is missing v3_run_path", path=run_dir / "run.json")
    v3_dir = resolve_v3_dir(v3_path)
    validate_v4_sentinel(run_dir, run_id, v3_dir)
    context = trusted_v3_context(v3_dir)
    expected_schedule, expected_packets, expected_prompts = build_schedule(context)
    schedule = read_json_obj(run_dir / "schedule.json", code="ERR_ORCH_ARTIFACT_MALFORMED", label="schedule.json")
    journal = read_json_obj(run_dir / "journal" / "0000.json", code="ERR_ORCH_ARTIFACT_MALFORMED", label="journal")
    invalidators: list[dict[str, Any]] = []
    if schedule != expected_schedule:
        invalidators.append({"code": "ERR_ORCH_ARTIFACT_MALFORMED", "message": "schedule does not match current inputs"})
    for packet, prompt in zip(expected_packets, expected_prompts, strict=True):
        stem = f"{packet['packet_index']:04d}.{packet['phase_id']}"
        actual_packet = read_json_obj(run_dir / "packets" / f"{stem}.packet.json", code="ERR_ORCH_ARTIFACT_MALFORMED", label="packet")
        prompt_path = run_dir / "packets" / f"{stem}.prompt.md"
        if not prompt_path.is_file() or prompt_path.is_symlink():
            raise OrchestrateError("ERR_ORCH_ARTIFACT_MALFORMED", "prompt is missing or symlinked", path=prompt_path)
        if actual_packet != packet:
            invalidators.append({"code": "ERR_ORCH_ARTIFACT_MALFORMED", "message": f"packet {stem} does not match current inputs"})
        if prompt_path.read_text() != prompt:
            invalidators.append({"code": "ERR_ORCH_ARTIFACT_MALFORMED", "message": f"prompt {stem} does not match current inputs"})
    expected_journal = journal_entry(context, expected_schedule)
    expected_journal["created_at"] = journal.get("created_at")
    if journal != expected_journal:
        invalidators.append({"code": "ERR_ORCH_ARTIFACT_MALFORMED", "message": "journal does not match current inputs"})
    status = build_status(
        run_id,
        context=context,
        schedule=expected_schedule,
        journal=expected_journal,
        status="scheduled" if not invalidators else "invalid",
        resume_state="resumable" if not invalidators else "invalidated",
        invalidators=invalidators,
    )
    write_status(run_dir, status)
    return {"status": status, "out_dir": run_dir}


def reset_owned(path: Path, sentinel_name: str) -> None:
    if not path.exists():
        return
    sentinel = read_sentinel(path, sentinel_name)
    if sentinel is None:
        raise OrchestrateError("ERR_ORCH_ARTIFACT_MALFORMED", "existing self-test output is not owned", path=path)
    shutil.rmtree(path)


def fanout_plan(base: dict[str, Any], *, cap: int = 2) -> dict[str, Any]:
    plan = json.loads(canonical_json_text(base))
    plan["plan_id"] = f"v4-self-test-fanout-cap-{cap}"
    plan["parallelism"]["concurrency_cap"] = cap
    base_handoff = plan["handoffs"][0]
    plan["handoffs"] = [
        {**base_handoff, "to_phase": "verify_a"},
        {**base_handoff, "to_phase": "verify_b"},
    ]
    plan["resume"]["cacheable_outputs"] = ["inventory.json", "verification-a.md", "verification-b.md", "synthesis.md"]
    plan["resume"]["restart_points"] = ["inventory", "verify_a", "verify_b", "synthesis"]
    plan["phases"] = [
        plan["phases"][0],
        {
            "id": "verify_a",
            "name": "Verify A",
            "depends_on": ["inventory"],
            "entry_criteria": ["inventory.json validates"],
            "exit_criteria": ["verification-a.md exists"],
            "outputs": ["verification-a.md"],
            "worker_ids": ["verify-worker"],
        },
        {
            "id": "verify_b",
            "name": "Verify B",
            "depends_on": ["inventory"],
            "entry_criteria": ["inventory.json validates"],
            "exit_criteria": ["verification-b.md exists"],
            "outputs": ["verification-b.md"],
            "worker_ids": ["verify-worker"],
        },
        {
            "id": "synthesis",
            "name": "Synthesis",
            "depends_on": ["verify_a", "verify_b"],
            "entry_criteria": ["verification outputs exist"],
            "exit_criteria": ["synthesis.md exists"],
            "outputs": ["synthesis.md"],
            "worker_ids": ["verify-worker"],
        },
    ]
    return plan


def prepare_v3_fixture(plan: dict[str, Any], run_id: str) -> Path:
    plan_dir = V4_OUT_ROOT / ".self-test-plans"
    plan_path = plan_dir / f"{run_id}.workflow.plan.json"
    plan_dir.mkdir(parents=True, exist_ok=True)
    write_exec_json(plan_path, plan, root=V4_OUT_ROOT)
    v1_run = V1_OUT_ROOT / run_id
    v2_run = V2_OUT_ROOT / run_id
    v3_run = V3_OUT_ROOT / run_id
    reset_owned(v2_run, ".execute_packet-owned.json")
    reset_owned(v3_run, ".run_workflow-owned.json")
    compile_plan(plan_path, v1_run, run_id=run_id)
    head = git_text(["rev-parse", "--short=12", "HEAD"], ROOT).strip()
    worktree = f"v4-{head}-{run_id}"
    inventory_path = worktree_path(worktree) / "inventory.json"
    if inventory_path.exists():
        if inventory_path.is_symlink() or not inventory_path.is_file():
            raise OrchestrateError("ERR_ORCH_ARTIFACT_MALFORMED", "fixture inventory is unsafe", path=inventory_path)
        inventory_path.unlink()
    execute_local_shell(
        v1_run,
        out_dir=v2_run,
        worktree=worktree,
        local_shell={"argv": ["python", "-c", "from pathlib import Path; Path('inventory.json').write_text('{}')"], "expected_exit_code": 0},
        verification_commands=[
            {
                "id": "verify-output",
                "argv": ["python", "-c", "from pathlib import Path; raise SystemExit(0 if Path('inventory.json').is_file() else 1)"],
                "expected_exit_code": 0,
            }
        ],
    )
    if inventory_path.exists():
        inventory_path.unlink()
    review_execution(v1_run, out_dir=v2_run)
    start_runtime(v2_run, out_dir=v3_run)
    return v3_run


def require(condition: bool, message: str) -> None:
    if not condition:
        raise OrchestrateError("ERR_ORCH_SELF_TEST_FAILED", message)


def self_test() -> None:
    base = read_json(ROOT / "fixtures" / "v1" / "plans" / "ready-readonly.workflow.plan.json")
    linear_v3 = prepare_v3_fixture(base, "orchestrate-self-test-linear")
    linear_out = V4_OUT_ROOT / "orchestrate-self-test-linear"
    reset_owned(linear_out, SENTINEL)
    linear = start_orchestration(linear_v3, out_dir=linear_out)
    require(linear["status"]["status"] == "scheduled", "linear V3 run should schedule")
    require(linear["status"]["selected_phase_ids"] == ["verify"], "linear run should select verify")
    require(resume_orchestration(linear_out)["status"]["resume_state"] == "resumable", "linear run should resume")

    fanout_v3 = prepare_v3_fixture(fanout_plan(base, cap=2), "orchestrate-self-test-fanout")
    fanout_out = V4_OUT_ROOT / "orchestrate-self-test-fanout"
    reset_owned(fanout_out, SENTINEL)
    fanout = start_orchestration(fanout_v3, out_dir=fanout_out)
    require(fanout["status"]["selected_phase_ids"] == ["verify_a", "verify_b"], "fanout should select both ready phases")
    require(len(list((fanout_out / "packets").glob("*.packet.json"))) == 2, "fanout should emit two packets")

    capped_v3 = prepare_v3_fixture(fanout_plan(base, cap=1), "orchestrate-self-test-capped")
    capped_out = V4_OUT_ROOT / "orchestrate-self-test-capped"
    reset_owned(capped_out, SENTINEL)
    capped = start_orchestration(capped_v3, out_dir=capped_out)
    require(capped["status"]["selected_phase_ids"] == ["verify_a"], "cap should limit selected phases")

    tampered_schedule = read_json_obj(fanout_out / "schedule.json", code="ERR_ORCH_ARTIFACT_MALFORMED", label="schedule")
    tampered_schedule["selected_phase_ids"] = ["verify_b"]
    write_json(fanout_out / "schedule.json", tampered_schedule, root=fanout_out)
    tampered = resume_orchestration(fanout_out)
    require(tampered["status"]["status"] == "invalid", "tampered schedule should invalidate resume")
    require(tampered["status"]["invalidators"][0]["code"] == "ERR_ORCH_ARTIFACT_MALFORMED", "tamper invalidator code mismatch")

    print("orchestrate_workflow self-test: pass")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", help="trusted V3 runtime directory under out/v3")
    parser.add_argument("--resume", help="V4 orchestration directory under out/v4")
    parser.add_argument("--out", help="V4 output directory")
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if args.self_test:
            self_test()
            return 0
        if args.start:
            result = start_orchestration(Path(args.start), out_dir=Path(args.out) if args.out else None)
            print(canonical_json_text(result["status"]))
            return 0 if result["status"]["status"] == "scheduled" else 1
        if args.resume:
            result = resume_orchestration(Path(args.resume))
            print(canonical_json_text(result["status"]))
            return 0 if result["status"]["status"] == "scheduled" else 1
        raise OrchestrateError("ERR_ORCH_MANIFEST_REQUIRED_FAILED", "expected --start, --resume, or --self-test")
    except OrchestrateError as exc:
        print(canonical_json_text(exc.to_record()), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
