#!/usr/bin/env python3
"""Ingest one reviewed V5.5 worker result into the next runtime frontier."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from compile_workflow import canonical_hash, canonical_json_text, sha256_text, write_text_atomic  # noqa: E402
from dispatch_worker import resume_dispatch  # noqa: E402
from orchestrate_workflow import SENTINEL as V4_SENTINEL, resume_orchestration  # noqa: E402
from review_worker_result import (  # noqa: E402
    SENTINEL as REVIEW_SENTINEL,
    V55_OUT_ROOT,
    ReviewError,
    read_sentinel as read_review_sentinel,
    resume_review,
    start_review,
)
from run_worker_result import SENTINEL as V5_SENTINEL, V5_OUT_ROOT, WorkerError, read_sentinel as read_v5_sentinel, resolve_dispatch  # noqa: E402


TOOL = "ingest_worker_review.py"
SCHEMA_VERSION = "1.0"
INGEST_VERSION = "0.1.0"
V6_OUT_ROOT = ROOT / "out" / "v6"
V1_OUT_ROOT = ROOT / "out" / "v1"
V3_OUT_ROOT = ROOT / "out" / "v3"
SENTINEL = ".ingest_worker_review-owned.json"


class IngestError(ValueError):
    """Structured V6 ingestion failure."""

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
        raise IngestError(code, message, path=path)


def check_components_not_symlink(path: Path, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise IngestError(code, "path contains a symlink", path=current)


def resolve_under_out(value: str | Path, root: Path, *, label: str) -> Path:
    raw = Path(value)
    reject_traversal(raw, "ERR_INGEST_OUTSIDE_REPO", f"{label} path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    out_root = root.resolve(strict=False)
    forbidden = {ROOT.resolve(), (ROOT / "out").resolve(strict=False), out_root}
    if resolved in forbidden:
        raise IngestError("ERR_INGEST_OUTSIDE_REPO", f"{label} path must name a run directory", path=value)
    try:
        resolved.relative_to(out_root)
    except ValueError as exc:
        raise IngestError("ERR_INGEST_OUTSIDE_REPO", f"{label} path must resolve under {out_root}", path=value) from exc
    check_components_not_symlink(candidate, "ERR_INGEST_DIR_SYMLINK")
    return resolved


def resolve_review(value: str | Path) -> Path:
    return resolve_under_out(value, V55_OUT_ROOT, label="V5.5 review")


def resolve_v6_out(value: str | Path) -> Path:
    return resolve_under_out(value, V6_OUT_ROOT, label="V6 output")


def ensure_contained(root: Path, path: Path) -> None:
    target = path if path.is_absolute() else root / path
    reject_traversal(path, "ERR_INGEST_OUTSIDE_REPO", "artifact path escapes owned directory")
    try:
        target.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError as exc:
        raise IngestError("ERR_INGEST_OUTSIDE_REPO", "artifact path escapes owned directory", path=target) from exc


def ensure_artifact_parent(root: Path, path: Path) -> None:
    ensure_contained(root, path)
    current = root.resolve(strict=False)
    for part in path.resolve(strict=False).relative_to(current).parent.parts:
        current = current / part
        if current.exists():
            if current.is_symlink():
                raise IngestError("ERR_INGEST_DIR_SYMLINK", "artifact parent is symlinked", path=current)
            if not current.is_dir():
                raise IngestError("ERR_INGEST_OUTSIDE_REPO", "artifact parent is not a directory", path=current)
        else:
            current.mkdir()


def ensure_leaf_not_symlink(path: Path) -> None:
    if path.exists():
        if path.is_symlink():
            raise IngestError("ERR_INGEST_LEAF_SYMLINK", "refusing to overwrite symlinked file", path=path)
        if not path.is_file():
            raise IngestError("ERR_INGEST_OUTSIDE_REPO", "refusing to overwrite non-file leaf", path=path)


def write_text(path: Path, text: str, *, root: Path) -> None:
    ensure_artifact_parent(root, path)
    ensure_leaf_not_symlink(path)
    write_text_atomic(path, text, root=root)


def write_json(path: Path, data: Any, *, root: Path) -> None:
    write_text(path, canonical_json_text(data), root=root)


def read_json_obj(path: Path, *, code: str, label: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise IngestError(code, f"{label} is missing or symlinked", path=path)
    try:
        data = json.loads(path.read_text())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IngestError(code, f"{label} is malformed: {exc}", path=path) from exc
    if not isinstance(data, dict):
        raise IngestError(code, f"{label} root must be an object", path=path)
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


def sentinel_payload(run_id: str, review_dir: Path) -> dict[str, Any]:
    return {
        "tool": TOOL,
        "schema_version": SCHEMA_VERSION,
        "ingest_version": INGEST_VERSION,
        "run_id": run_id,
        "review_path": rel(review_dir),
        "created_at": now_utc(),
    }


def ensure_ingest_dir(path: Path, run_id: str, review_dir: Path) -> None:
    path = resolve_v6_out(path)
    if path.exists():
        if path.is_symlink():
            raise IngestError("ERR_INGEST_DIR_SYMLINK", "V6 output directory is a symlink", path=path)
        if not path.is_dir():
            raise IngestError("ERR_INGEST_OUTSIDE_REPO", "V6 output exists and is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None:
            raise IngestError("ERR_INGEST_ARTIFACT_MALFORMED", "existing V6 output is not owned", path=path)
        expected = sentinel_payload(run_id, review_dir)
        expected["created_at"] = sentinel.get("created_at")
        if sentinel != expected:
            raise IngestError("ERR_INGEST_ARTIFACT_MALFORMED", "V6 output sentinel does not match this review", path=path)
    path.mkdir(parents=True, exist_ok=True)
    if read_sentinel(path) is None:
        write_json(path / SENTINEL, sentinel_payload(run_id, review_dir), root=path)


def require_string_list(value: Any, *, code: str, message: str, path: Path) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise IngestError(code, message, path=path)
    return value


def resolve_v1_dir(value: str | Path) -> Path:
    raw = Path(value)
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(V1_OUT_ROOT.resolve(strict=False))
    except ValueError as exc:
        raise IngestError("ERR_INGEST_UNTRUSTED_LINEAGE", "V1 path escapes out/v1", path=value) from exc
    check_components_not_symlink(candidate, "ERR_INGEST_DIR_SYMLINK")
    return resolved


def resolve_v3_dir(value: str | Path) -> Path:
    raw = Path(value)
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(V3_OUT_ROOT.resolve(strict=False))
    except ValueError as exc:
        raise IngestError("ERR_INGEST_UNTRUSTED_LINEAGE", "V3 path escapes out/v3", path=value) from exc
    check_components_not_symlink(candidate, "ERR_INGEST_DIR_SYMLINK")
    return resolved


def v4_dir_from_dispatch(dispatch: dict[str, Any]) -> Path:
    source_packet_path = dispatch.get("source_packet_path")
    if not isinstance(source_packet_path, str):
        raise IngestError("ERR_INGEST_UNTRUSTED_LINEAGE", "dispatch is missing source_packet_path")
    packet_path = ROOT / source_packet_path
    if packet_path.name.endswith(".packet.json"):
        return packet_path.resolve(strict=False).parents[1]
    raise IngestError("ERR_INGEST_UNTRUSTED_LINEAGE", "dispatch source packet path is unsupported", path=source_packet_path)


def trusted_review_context(review_dir: Path) -> dict[str, Any]:
    review_dir = resolve_review(review_dir)
    if read_review_sentinel(review_dir, REVIEW_SENTINEL) is None:
        raise IngestError("ERR_INGEST_UNTRUSTED_REVIEW", "review is missing ownership sentinel", path=review_dir / REVIEW_SENTINEL)
    try:
        resumed = resume_review(review_dir)
    except ReviewError as exc:
        raise IngestError("ERR_INGEST_UNTRUSTED_REVIEW", exc.message, path=exc.path) from exc
    if resumed["status"]["status"] != "review-approved" or resumed["status"]["resume_state"] != "resumable":
        raise IngestError("ERR_INGEST_UNTRUSTED_REVIEW", "review is not approved and resumable", path=review_dir / "status.json")
    review = read_json_obj(review_dir / "review.json", code="ERR_INGEST_UNTRUSTED_REVIEW", label="review.json")
    if review.get("verdict") != "approve":
        raise IngestError("ERR_INGEST_ENTRY_REJECTED", "only approve verdicts can be ingested", path=review_dir / "review.json")
    phase_id = review.get("source_phase_id")
    if not isinstance(phase_id, str) or not phase_id:
        raise IngestError("ERR_INGEST_UNTRUSTED_REVIEW", "review is missing source_phase_id", path=review_dir / "review.json")
    approved_outputs = require_string_list(
        review.get("approved_outputs"),
        code="ERR_INGEST_UNTRUSTED_REVIEW",
        message="approved_outputs is malformed",
        path=review_dir / "review.json",
    )
    if not approved_outputs:
        raise IngestError("ERR_INGEST_ENTRY_REJECTED", "approved review has no approved outputs", path=review_dir / "review.json")
    source_result_path = review.get("source_result_path")
    if not isinstance(source_result_path, str):
        raise IngestError("ERR_INGEST_UNTRUSTED_REVIEW", "review is missing source_result_path", path=review_dir / "review.json")
    source_result_dir = (ROOT / source_result_path).resolve(strict=False)
    if not source_result_dir.is_dir():
        raise IngestError("ERR_INGEST_UNTRUSTED_LINEAGE", "source result directory is missing", path=source_result_dir)
    v5_sentinel = read_v5_sentinel(source_result_dir, V5_SENTINEL)
    dispatch_path = v5_sentinel.get("dispatch_path") if v5_sentinel else None
    if not isinstance(dispatch_path, str):
        raise IngestError("ERR_INGEST_UNTRUSTED_LINEAGE", "V5 result is missing dispatch_path", path=source_result_dir / V5_SENTINEL)
    try:
        dispatch_dir = resolve_dispatch(dispatch_path)
    except WorkerError as exc:
        raise IngestError("ERR_INGEST_UNTRUSTED_LINEAGE", exc.message, path=exc.path) from exc
    dispatch_resumed = resume_dispatch(dispatch_dir)
    if dispatch_resumed["status"]["status"] != "prepared" or dispatch_resumed["status"]["resume_state"] != "resumable":
        raise IngestError("ERR_INGEST_UNTRUSTED_LINEAGE", "dispatch is not prepared and resumable", path=dispatch_dir / "status.json")
    dispatch = read_json_obj(dispatch_dir / "dispatch.json", code="ERR_INGEST_UNTRUSTED_LINEAGE", label="dispatch.json")
    v4_dir = v4_dir_from_dispatch(dispatch)
    if read_sentinel(v4_dir, V4_SENTINEL) is None:
        raise IngestError("ERR_INGEST_UNTRUSTED_LINEAGE", "V4 run is missing ownership sentinel", path=v4_dir / V4_SENTINEL)
    v4_resumed = resume_orchestration(v4_dir)
    if v4_resumed["status"]["status"] != "scheduled" or v4_resumed["status"]["resume_state"] != "resumable":
        raise IngestError("ERR_INGEST_UNTRUSTED_LINEAGE", "V4 schedule is not resumable", path=v4_dir / "status.json")
    v4_run = read_json_obj(v4_dir / "run.json", code="ERR_INGEST_UNTRUSTED_LINEAGE", label="V4 run.json")
    v4_schedule = read_json_obj(v4_dir / "schedule.json", code="ERR_INGEST_UNTRUSTED_LINEAGE", label="V4 schedule.json")
    selected = require_string_list(
        v4_schedule.get("selected_phase_ids"),
        code="ERR_INGEST_UNTRUSTED_LINEAGE",
        message="V4 selected_phase_ids is malformed",
        path=v4_dir / "schedule.json",
    )
    completed = require_string_list(
        v4_schedule.get("completed_phase_ids"),
        code="ERR_INGEST_UNTRUSTED_LINEAGE",
        message="V4 completed_phase_ids is malformed",
        path=v4_dir / "schedule.json",
    )
    if phase_id not in selected:
        raise IngestError("ERR_INGEST_ENTRY_REJECTED", "reviewed phase was not selected by V4 schedule", path=v4_dir / "schedule.json")
    if phase_id in completed:
        raise IngestError("ERR_INGEST_ENTRY_REJECTED", "reviewed phase is already completed", path=v4_dir / "schedule.json")
    v3_path = v4_run.get("v3_run_path")
    if not isinstance(v3_path, str):
        raise IngestError("ERR_INGEST_UNTRUSTED_LINEAGE", "V4 run is missing v3_run_path", path=v4_dir / "run.json")
    v3_dir = resolve_v3_dir(v3_path)
    v3_status = read_json_obj(v3_dir / "status.json", code="ERR_INGEST_UNTRUSTED_LINEAGE", label="V3 status.json")
    v1_path = v3_status.get("v1_run_path")
    if not isinstance(v1_path, str):
        raise IngestError("ERR_INGEST_UNTRUSTED_LINEAGE", "V3 status is missing v1_run_path", path=v3_dir / "status.json")
    v1_dir = resolve_v1_dir(v1_path)
    plan = read_json_obj(v1_dir / "plan.snapshot.json", code="ERR_INGEST_UNTRUSTED_LINEAGE", label="plan.snapshot.json")
    expected_plan_hash = v4_schedule.get("source_hashes", {}).get("v1_plan_snapshot_hash") if isinstance(v4_schedule.get("source_hashes"), dict) else None
    if expected_plan_hash != canonical_hash(plan):
        raise IngestError("ERR_INGEST_UNTRUSTED_LINEAGE", "plan snapshot does not match V4 schedule", path=v1_dir / "plan.snapshot.json")
    return {
        "review_dir": review_dir,
        "review_status": resumed["status"],
        "review": review,
        "source_result_dir": source_result_dir,
        "dispatch_dir": dispatch_dir,
        "dispatch": dispatch,
        "v4_dir": v4_dir,
        "v4_run": v4_run,
        "v4_schedule": v4_schedule,
        "v3_dir": v3_dir,
        "v3_status": v3_status,
        "v1_dir": v1_dir,
        "plan": plan,
    }


def worker_index(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    workers = plan.get("workers")
    if not isinstance(workers, list):
        raise IngestError("ERR_INGEST_PLAN_MALFORMED", "plan workers must be a list")
    indexed: dict[str, dict[str, Any]] = {}
    for worker in workers:
        if not isinstance(worker, dict) or not isinstance(worker.get("id"), str):
            raise IngestError("ERR_INGEST_PLAN_MALFORMED", "worker is malformed")
        indexed[worker["id"]] = worker
    return indexed


def incoming_handoffs(plan: dict[str, Any], phase_id: str) -> list[dict[str, Any]]:
    handoffs = plan.get("handoffs")
    if not isinstance(handoffs, list):
        return []
    return [item for item in handoffs if isinstance(item, dict) and item.get("to_phase") == phase_id]


def concurrency_cap(plan: dict[str, Any]) -> int:
    parallelism = plan.get("parallelism")
    if isinstance(parallelism, dict) and isinstance(parallelism.get("concurrency_cap"), int):
        return max(1, parallelism["concurrency_cap"])
    return 1


def frontier_for_completed(context: dict[str, Any], completed: list[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    plan = context["plan"]
    phases = plan.get("phases")
    if not isinstance(phases, list):
        raise IngestError("ERR_INGEST_PLAN_MALFORMED", "plan phases must be a list")
    workers_by_id = worker_index(plan)
    completed_set = set(completed)
    ready: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for phase in phases:
        if not isinstance(phase, dict) or not isinstance(phase.get("id"), str):
            raise IngestError("ERR_INGEST_PLAN_MALFORMED", "phase is malformed")
        phase_id = phase["id"]
        if phase_id in completed_set:
            continue
        depends_on = require_string_list(
            phase.get("depends_on"),
            code="ERR_INGEST_PLAN_MALFORMED",
            message="phase depends_on is malformed",
            path=context["v1_dir"] / "plan.snapshot.json",
        )
        worker_ids = require_string_list(
            phase.get("worker_ids"),
            code="ERR_INGEST_PLAN_MALFORMED",
            message="phase worker_ids is malformed",
            path=context["v1_dir"] / "plan.snapshot.json",
        )
        unknown = [worker_id for worker_id in worker_ids if worker_id not in workers_by_id]
        if unknown:
            raise IngestError("ERR_INGEST_PLAN_MALFORMED", f"phase references unknown worker: {unknown[0]}")
        unmet = [dep for dep in depends_on if dep not in completed_set]
        if unmet:
            blocked.append({"phase_id": phase_id, "unmet_dependencies": unmet})
        else:
            ready.append(phase)
    return ready, blocked, concurrency_cap(plan)


def source_hashes(context: dict[str, Any]) -> dict[str, str]:
    return {
        "review_hash": canonical_hash(context["review"]),
        "v4_schedule_hash": canonical_hash(context["v4_schedule"]),
        "v4_run_hash": canonical_hash(context["v4_run"]),
        "v3_status_hash": canonical_hash(context["v3_status"]),
        "plan_snapshot_hash": canonical_hash(context["plan"]),
        "dispatch_hash": canonical_hash(context["dispatch"]),
    }


def build_frontier_packet(index: int, phase: dict[str, Any], context: dict[str, Any], source: dict[str, str]) -> dict[str, Any]:
    plan = context["plan"]
    workers_by_id = worker_index(plan)
    worker_ids = require_string_list(
        phase.get("worker_ids"),
        code="ERR_INGEST_PLAN_MALFORMED",
        message="phase worker_ids is malformed",
        path=context["v1_dir"] / "plan.snapshot.json",
    )
    phase_id = phase["id"]
    return {
        "schema_version": SCHEMA_VERSION,
        "ingest_version": INGEST_VERSION,
        "packet_id": f"v6-frontier-{index:04d}-{phase_id}",
        "packet_index": index,
        "source_plan_id": plan.get("plan_id"),
        "objective": plan.get("objective"),
        "phase_id": phase_id,
        "phase_name": phase.get("name", phase_id),
        "depends_on": phase.get("depends_on", []),
        "entry_criteria": phase.get("entry_criteria", []),
        "exit_criteria": phase.get("exit_criteria", []),
        "expected_outputs": phase.get("outputs", []),
        "worker_ids": worker_ids,
        "workers": [workers_by_id[worker_id] for worker_id in worker_ids],
        "handoff_inputs": incoming_handoffs(plan, phase_id),
        "completed_phase_ids": build_completed_phase_ids(context),
        "reviewed_phase_ids": [context["review"]["source_phase_id"]],
        "stop_conditions": [
            "do not execute this packet in V6 ingestion",
            "route any frontier worker result through V7.5 frontier result review before runtime ingestion",
            "stop before destructive, external, costly, production, secret, dependency, database, public API, delete, or history-rewrite actions",
        ],
        "source_hashes": source,
    }


def render_packet_prompt(packet: dict[str, Any]) -> str:
    lines = [
        "# V6 Frontier Packet",
        "",
        f"Packet: `{packet['packet_id']}`",
        f"Phase: `{packet['phase_id']}`",
        "",
        "## Objective",
        "",
        str(packet.get("objective", "")),
        "",
        "## Completed Phases",
    ]
    for phase_id in packet.get("completed_phase_ids", []):
        lines.append(f"- `{phase_id}`")
    lines.extend(["", "## Expected Outputs"])
    for output in packet.get("expected_outputs", []):
        lines.append(f"- {output}")
    lines.extend(["", "## Workers"])
    for worker in packet.get("workers", []):
        lines.append(f"- `{worker.get('id')}` {worker.get('role')}")
    lines.extend(["", "## Stop Conditions"])
    for item in packet.get("stop_conditions", []):
        lines.append(f"- {item}")
    return "\n".join(lines) + "\n"


def build_completed_phase_ids(context: dict[str, Any]) -> list[str]:
    completed = require_string_list(
        context["v4_schedule"].get("completed_phase_ids"),
        code="ERR_INGEST_UNTRUSTED_LINEAGE",
        message="V4 completed_phase_ids is malformed",
        path=context["v4_dir"] / "schedule.json",
    )
    phase_id = context["review"]["source_phase_id"]
    return [*completed, phase_id]


def build_state(context: dict[str, Any], packets: list[dict[str, Any]], prompts: list[str], ready: list[dict[str, Any]], blocked: list[dict[str, Any]], cap: int) -> dict[str, Any]:
    completed = build_completed_phase_ids(context)
    selected = ready[:cap]
    return {
        "schema_version": SCHEMA_VERSION,
        "ingest_version": INGEST_VERSION,
        "source_plan_id": context["plan"].get("plan_id"),
        "source_review_path": rel(context["review_dir"]),
        "source_v4_run_path": rel(context["v4_dir"]),
        "completed_phase_ids": completed,
        "reviewed_phase_ids": [context["review"]["source_phase_id"]],
        "ready_phase_ids": [phase["id"] for phase in ready],
        "selected_phase_ids": [phase["id"] for phase in selected],
        "blocked_phases": blocked,
        "concurrency_cap": cap,
        "reviewed_results": [
            {
                "review_path": rel(context["review_dir"]),
                "phase_id": context["review"]["source_phase_id"],
                "approved_outputs": context["review"].get("approved_outputs", []),
                "source_result_path": context["review"].get("source_result_path"),
            }
        ],
        "source_hashes": source_hashes(context),
        "packet_hashes": {packets[index]["packet_id"]: canonical_hash(packets[index]) for index in range(len(packets))},
        "prompt_hashes": {packets[index]["packet_id"]: sha256_text(prompts[index]) for index in range(len(prompts))},
    }


def build_outputs(context: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    completed = build_completed_phase_ids(context)
    ready, blocked, cap = frontier_for_completed(context, completed)
    selected = ready[:cap]
    source = source_hashes(context)
    packets = [build_frontier_packet(index, phase, context, source) for index, phase in enumerate(selected, start=1)]
    prompts = [render_packet_prompt(packet) for packet in packets]
    state = build_state(context, packets, prompts, ready, blocked, cap)
    return state, packets, prompts


def build_run(run_id: str, review_dir: Path, packets: list[dict[str, Any]], *, created_at: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "ingest_version": INGEST_VERSION,
        "run_id": run_id,
        "created_at": created_at or now_utc(),
        "review_path": rel(review_dir),
        "state_path": "state.json",
        "packet_paths": [f"packets/{packet['packet_index']:04d}.{packet['phase_id']}.packet.json" for packet in packets],
        "journal_paths": ["journal/0000.json"],
    }


def build_journal(context: dict[str, Any], state: dict[str, Any], *, created_at: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "ingest_version": INGEST_VERSION,
        "event_id": "0000",
        "event": "v6-frontier-created",
        "created_at": created_at or now_utc(),
        "review_path": rel(context["review_dir"]),
        "completed_phase_ids": state["completed_phase_ids"],
        "selected_phase_ids": state["selected_phase_ids"],
        "source_hashes": state["source_hashes"],
    }


def build_hashes(run: dict[str, Any], state: dict[str, Any], packets: list[dict[str, Any]], prompts: list[str], journal: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_hash": canonical_hash(run),
        "state_hash": canonical_hash(state),
        "packet_hashes": {packets[index]["packet_id"]: canonical_hash(packets[index]) for index in range(len(packets))},
        "prompt_hashes": {packets[index]["packet_id"]: sha256_text(prompts[index]) for index in range(len(prompts))},
        "journal_hash": canonical_hash(journal),
    }


def status_name(state: dict[str, Any]) -> str:
    return "frontier-ready" if state.get("selected_phase_ids") else "workflow-complete"


def build_status(
    run_id: str,
    *,
    state: dict[str, Any] | None,
    hashes: dict[str, Any] | None,
    status: str,
    resume_state: str,
    invalidators: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "ingest_version": INGEST_VERSION,
        "run_id": run_id,
        "status": status,
        "resume_state": resume_state,
        "state_path": "state.json" if state else None,
        "completed_phase_ids": state.get("completed_phase_ids", []) if state else [],
        "reviewed_phase_ids": state.get("reviewed_phase_ids", []) if state else [],
        "ready_phase_ids": state.get("ready_phase_ids", []) if state else [],
        "selected_phase_ids": state.get("selected_phase_ids", []) if state else [],
        "invalidators": invalidators or [],
        "snapshots": hashes or {},
        "checked_at": now_utc(),
    }


def render_resume(status: dict[str, Any]) -> str:
    lines = [
        "# V6 Runtime Ingestion Resume",
        "",
        f"Run: `{status['run_id']}`",
        f"Status: `{status['status']}`",
        f"Resume state: `{status['resume_state']}`",
        "",
        "## Completed Phases",
    ]
    for phase_id in status.get("completed_phase_ids", []):
        lines.append(f"- `{phase_id}`")
    lines.extend(["", "## Selected Frontier"])
    selected = status.get("selected_phase_ids", [])
    if selected:
        for phase_id in selected:
            lines.append(f"- `{phase_id}`")
    else:
        lines.append("- None")
    if status.get("invalidators"):
        lines.extend(["", "## Invalidators"])
        for item in status["invalidators"]:
            lines.append(f"- `{item.get('code')}` {item.get('message')}")
    return "\n".join(lines) + "\n"


def write_status(out_dir: Path, status: dict[str, Any]) -> None:
    write_json(out_dir / "status.json", status, root=out_dir)
    write_text(out_dir / "resume.md", render_resume(status), root=out_dir)


def write_error_status(out_dir: Path, run_id: str, review_dir: Path, error: IngestError) -> dict[str, Any]:
    ensure_ingest_dir(out_dir, run_id, review_dir)
    status = build_status(run_id, state=None, hashes=None, status="invalid", resume_state="invalid", invalidators=[error.to_record()])
    write_status(out_dir, status)
    return status


def start_ingestion(review_dir: Path, *, out_dir: Path | None = None) -> dict[str, Any]:
    review_dir = resolve_review(review_dir)
    out_dir = resolve_v6_out(out_dir) if out_dir is not None else V6_OUT_ROOT / review_dir.name
    run_id = out_dir.name
    try:
        ensure_ingest_dir(out_dir, run_id, review_dir)
        context = trusted_review_context(review_dir)
        state, packets, prompts = build_outputs(context)
        run = build_run(run_id, review_dir, packets)
        journal = build_journal(context, state)
        hashes = build_hashes(run, state, packets, prompts, journal)
        status = build_status(run_id, state=state, hashes=hashes, status=status_name(state), resume_state="fresh")
    except IngestError as exc:
        status = write_error_status(out_dir, run_id, review_dir, exc)
        return {"status": status, "out_dir": out_dir}
    write_json(out_dir / "run.json", run, root=out_dir)
    write_json(out_dir / "state.json", state, root=out_dir)
    for packet, prompt in zip(packets, prompts, strict=True):
        stem = f"{packet['packet_index']:04d}.{packet['phase_id']}"
        write_json(out_dir / "packets" / f"{stem}.packet.json", packet, root=out_dir)
        write_text(out_dir / "packets" / f"{stem}.prompt.md", prompt, root=out_dir)
    write_json(out_dir / "journal" / "0000.json", journal, root=out_dir)
    write_json(out_dir / "hashes.json", hashes, root=out_dir)
    write_status(out_dir, status)
    return {"status": status, "out_dir": out_dir, "state": state, "packets": packets}


def validate_ingest_sentinel(run_dir: Path, run_id: str, review_dir: Path) -> None:
    sentinel = read_sentinel(run_dir)
    if sentinel is None:
        raise IngestError("ERR_INGEST_ARTIFACT_MALFORMED", "V6 output is missing ownership sentinel", path=run_dir / SENTINEL)
    expected = sentinel_payload(run_id, review_dir)
    expected["created_at"] = sentinel.get("created_at")
    if sentinel != expected:
        raise IngestError("ERR_INGEST_ARTIFACT_MALFORMED", "V6 output sentinel does not match review", path=run_dir / SENTINEL)


def resume_ingestion(run_dir: Path) -> dict[str, Any]:
    run_dir = resolve_v6_out(run_dir)
    run_id = run_dir.name
    sentinel = read_sentinel(run_dir)
    if sentinel is None or not isinstance(sentinel.get("review_path"), str):
        raise IngestError("ERR_INGEST_ARTIFACT_MALFORMED", "sentinel is missing review_path", path=run_dir / SENTINEL)
    review_dir = resolve_review(sentinel["review_path"])
    validate_ingest_sentinel(run_dir, run_id, review_dir)
    try:
        run = read_json_obj(run_dir / "run.json", code="ERR_INGEST_ARTIFACT_MALFORMED", label="run.json")
        state = read_json_obj(run_dir / "state.json", code="ERR_INGEST_ARTIFACT_MALFORMED", label="state.json")
        journal = read_json_obj(run_dir / "journal" / "0000.json", code="ERR_INGEST_ARTIFACT_MALFORMED", label="journal")
        hashes = read_json_obj(run_dir / "hashes.json", code="ERR_INGEST_ARTIFACT_MALFORMED", label="hashes.json")
    except IngestError as exc:
        status = build_status(run_id, state=None, hashes=None, status="invalid", resume_state="invalidated", invalidators=[exc.to_record()])
        write_status(run_dir, status)
        return {"status": status, "out_dir": run_dir}

    invalidators: list[dict[str, Any]] = []
    expected_state = state
    expected_hashes: dict[str, Any] | None = None
    try:
        context = trusted_review_context(review_dir)
        expected_state, expected_packets, expected_prompts = build_outputs(context)
        expected_run = build_run(run_id, review_dir, expected_packets, created_at=str(run.get("created_at")))
        expected_journal = build_journal(context, expected_state, created_at=str(journal.get("created_at")))
        expected_hashes = build_hashes(expected_run, expected_state, expected_packets, expected_prompts, expected_journal)
        if run != expected_run:
            invalidators.append({"code": "ERR_INGEST_ARTIFACT_MALFORMED", "message": "run.json does not match current inputs"})
        if state != expected_state:
            invalidators.append({"code": "ERR_INGEST_ARTIFACT_MALFORMED", "message": "state.json does not match current inputs"})
        for packet, prompt in zip(expected_packets, expected_prompts, strict=True):
            stem = f"{packet['packet_index']:04d}.{packet['phase_id']}"
            actual_packet = read_json_obj(run_dir / "packets" / f"{stem}.packet.json", code="ERR_INGEST_ARTIFACT_MALFORMED", label="packet")
            prompt_path = run_dir / "packets" / f"{stem}.prompt.md"
            if not prompt_path.is_file() or prompt_path.is_symlink():
                raise IngestError("ERR_INGEST_ARTIFACT_MALFORMED", "prompt is missing or symlinked", path=prompt_path)
            if actual_packet != packet:
                invalidators.append({"code": "ERR_INGEST_ARTIFACT_MALFORMED", "message": f"packet {stem} does not match current inputs"})
            if prompt_path.read_text() != prompt:
                invalidators.append({"code": "ERR_INGEST_ARTIFACT_MALFORMED", "message": f"prompt {stem} does not match current inputs"})
        if journal != expected_journal:
            invalidators.append({"code": "ERR_INGEST_ARTIFACT_MALFORMED", "message": "journal does not match current inputs"})
        if hashes != expected_hashes:
            invalidators.append({"code": "ERR_INGEST_ARTIFACT_MALFORMED", "message": "hashes.json does not match current inputs"})
    except IngestError as exc:
        invalidators.append(exc.to_record())

    if invalidators:
        status = build_status(run_id, state=expected_state, hashes=expected_hashes, status="invalid", resume_state="invalidated", invalidators=invalidators)
    else:
        status = build_status(run_id, state=expected_state, hashes=expected_hashes, status=status_name(expected_state), resume_state="resumable")
    write_status(run_dir, status)
    return {"status": status, "out_dir": run_dir}


def reset_owned(path: Path, sentinel_name: str, tool: str) -> None:
    if not path.exists():
        return
    sentinel_path = path / sentinel_name
    if not sentinel_path.is_file() or sentinel_path.is_symlink():
        raise IngestError("ERR_INGEST_ARTIFACT_MALFORMED", "existing self-test output is not owned", path=path)
    try:
        sentinel = json.loads(sentinel_path.read_text())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IngestError("ERR_INGEST_ARTIFACT_MALFORMED", f"existing self-test sentinel is malformed: {exc}", path=sentinel_path) from exc
    if not isinstance(sentinel, dict) or sentinel.get("tool") != tool:
        raise IngestError("ERR_INGEST_ARTIFACT_MALFORMED", "existing self-test output is not owned by expected tool", path=path)
    shutil.rmtree(path)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise IngestError("ERR_INGEST_SELF_TEST_FAILED", message)


def self_test() -> None:
    review_dir = V55_OUT_ROOT / "ingest-self-test-review"
    out_dir = V6_OUT_ROOT / "ingest-self-test"
    reset_owned(review_dir, REVIEW_SENTINEL, "review_worker_result.py")
    reset_owned(out_dir, SENTINEL, TOOL)
    started_review = start_review(V5_OUT_ROOT / "v32-semantic-dogfood", out_dir=review_dir)
    require(started_review["status"]["status"] == "review-approved", "trusted review should approve")
    started = start_ingestion(review_dir, out_dir=out_dir)
    require(started["status"]["status"] == "frontier-ready", "reviewed phase should produce next frontier")
    require(started["status"]["completed_phase_ids"] == ["release_inventory", "evidence_review"], "completed phases should include reviewed phase")
    require(started["status"]["selected_phase_ids"] == ["release_decision"], "next frontier should select release_decision")
    resumed = resume_ingestion(out_dir)
    require(resumed["status"]["resume_state"] == "resumable", "clean ingestion should resume")
    state = read_json_obj(out_dir / "state.json", code="ERR_INGEST_ARTIFACT_MALFORMED", label="state.json")
    state["selected_phase_ids"] = ["tampered"]
    write_json(out_dir / "state.json", state, root=out_dir)
    tampered = resume_ingestion(out_dir)
    require(tampered["status"]["status"] == "invalid", "tampered state should invalidate")
    print("ingest_worker_review self-test: pass")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", help="trusted V5.5 review directory under out/v5.5")
    parser.add_argument("--resume", help="V6 ingestion output directory under out/v6")
    parser.add_argument("--out", help="V6 output directory")
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if args.self_test:
            self_test()
            return 0
        if args.review:
            result = start_ingestion(Path(args.review), out_dir=Path(args.out) if args.out else None)
            print(canonical_json_text(result["status"]))
            return 0 if result["status"]["status"] in {"frontier-ready", "workflow-complete"} else 1
        if args.resume:
            result = resume_ingestion(Path(args.resume))
            print(canonical_json_text(result["status"]))
            return 0 if result["status"]["status"] in {"frontier-ready", "workflow-complete"} else 1
        raise IngestError("ERR_INGEST_ARGUMENTS", "expected --review, --resume, or --self-test")
    except IngestError as exc:
        print(canonical_json_text(exc.to_record()), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
