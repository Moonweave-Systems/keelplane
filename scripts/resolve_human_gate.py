#!/usr/bin/env python3
"""Resolve one explicit V8 human gate into final runtime state."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from compile_workflow import SENTINEL as V1_SENTINEL, canonical_hash, canonical_json_text, sha256_text, write_text_atomic  # noqa: E402
from ingest_frontier_review import (  # noqa: E402
    SENTINEL as V8_SENTINEL,
    V8_OUT_ROOT,
)
from ingest_worker_review import V1_OUT_ROOT, V3_OUT_ROOT  # noqa: E402
from orchestrate_workflow import SENTINEL as V4_SENTINEL, V3_SENTINEL  # noqa: E402


TOOL = "resolve_human_gate.py"
SCHEMA_VERSION = "1.0"
HUMAN_GATE_VERSION = "0.1.0"
V4_OUT_ROOT = ROOT / "out" / "v4"
V7_OUT_ROOT = ROOT / "out" / "v7"
V75_OUT_ROOT = ROOT / "out" / "v7.5"
V9_OUT_ROOT = ROOT / "out" / "v9"
APPROVAL_ROOT = ROOT / "fixtures" / "v9" / "approvals"
SENTINEL = ".resolve_human_gate-owned.json"
V75_SENTINEL = ".review_frontier_result-owned.json"
PHASE_ID = "human_gate"
APPROVED_OUTPUT = "human-approval.md"
SUCCESS_STATUSES = {"frontier-ready", "blocked", "workflow-complete"}
REQUIRED_NEGATIVE_ATTESTATION = "no worker execution, merge, deployment, external message, secret access, or dependency installation is approved by this artifact"
FORBIDDEN_ACTION_TERMS = (
    "worker",
    "workers",
    "worker execution",
    "run worker",
    "run workers",
    "running worker",
    "running workers",
    "execution",
    "merge",
    "worktree merge",
    "deployment",
    "deploy",
    "publish",
    "commit",
    "push",
    "shell",
    "shell use",
    "shell command",
    "codex cli",
    "omx",
    "subagent",
    "external message",
    "external messages",
    "slack",
    "email",
    "network api",
    "paid api",
    "secret access",
    "secret",
    "dependency installation",
    "dependency install",
    "database migration",
    "delete",
    "source file",
    "product source",
)
AUTHORIZATION_TERMS = (
    "approve",
    "approved",
    "approves",
    "authorize",
    "authorized",
    "authorizes",
    "allow",
    "allowed",
    "allows",
    "permit",
    "permitted",
    "permits",
    "grant",
    "granted",
    "grants",
    "enable",
    "enabled",
    "enables",
)


class HumanGateError(ValueError):
    """Structured V9 human-gate failure."""

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
        raise HumanGateError(code, message, path=path)


def check_components_not_symlink(path: Path, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise HumanGateError(code, "path contains a symlink", path=current)


def resolve_under(value: str | Path, root: Path, *, label: str, code: str = "ERR_HUMAN_GATE_OUTSIDE_REPO") -> Path:
    raw = Path(value)
    reject_traversal(raw, code, f"{label} path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = root.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise HumanGateError(code, f"{label} path must resolve under {root_resolved}", path=value) from exc
    check_components_not_symlink(candidate, "ERR_HUMAN_GATE_DIR_SYMLINK")
    return resolved


def resolve_v8(value: str | Path) -> Path:
    path = resolve_under(value, V8_OUT_ROOT, label="V8 frontier")
    if path.resolve(strict=False) == V8_OUT_ROOT.resolve(strict=False):
        raise HumanGateError("ERR_HUMAN_GATE_OUTSIDE_REPO", "V8 frontier path must name a run directory", path=value)
    return path


def resolve_v75(value: str | Path) -> Path:
    return resolve_under(value, V75_OUT_ROOT, label="V7.5 review", code="ERR_HUMAN_GATE_UNTRUSTED_FRONTIER")


def resolve_v7(value: str | Path) -> Path:
    return resolve_under(value, V7_OUT_ROOT, label="V7 result", code="ERR_HUMAN_GATE_UNTRUSTED_FRONTIER")


def resolve_v9_out(value: str | Path) -> Path:
    path = resolve_under(value, V9_OUT_ROOT, label="V9 output")
    if path.resolve(strict=False) == V9_OUT_ROOT.resolve(strict=False):
        raise HumanGateError("ERR_HUMAN_GATE_OUTSIDE_REPO", "V9 output path must name a run directory", path=value)
    return path


def resolve_approval(value: str | Path) -> Path:
    path = resolve_under(value, APPROVAL_ROOT, label="approval", code="ERR_HUMAN_GATE_UNTRUSTED_APPROVAL")
    if not path.is_file() or path.is_symlink():
        raise HumanGateError("ERR_HUMAN_GATE_UNTRUSTED_APPROVAL", "approval file is missing or symlinked", path=path)
    rel_path = rel(path)
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", rel_path],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        raise HumanGateError("ERR_HUMAN_GATE_UNTRUSTED_APPROVAL", "approval file must be tracked by git", path=path)
    return path


def resolve_v4(value: str | Path) -> Path:
    return resolve_under(value, V4_OUT_ROOT, label="V4 run", code="ERR_HUMAN_GATE_UNTRUSTED_FRONTIER")


def resolve_v3(value: str | Path) -> Path:
    return resolve_under(value, V3_OUT_ROOT, label="V3 run", code="ERR_HUMAN_GATE_UNTRUSTED_FRONTIER")


def resolve_v1(value: str | Path) -> Path:
    return resolve_under(value, V1_OUT_ROOT, label="V1 run", code="ERR_HUMAN_GATE_UNTRUSTED_FRONTIER")


def ensure_contained(root: Path, path: Path) -> None:
    target = path if path.is_absolute() else root / path
    reject_traversal(path, "ERR_HUMAN_GATE_OUTSIDE_REPO", "artifact path escapes owned directory")
    try:
        target.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError as exc:
        raise HumanGateError("ERR_HUMAN_GATE_OUTSIDE_REPO", "artifact path escapes owned directory", path=target) from exc


def ensure_artifact_parent(root: Path, path: Path) -> None:
    ensure_contained(root, path)
    current = root.resolve(strict=False)
    for part in path.resolve(strict=False).relative_to(current).parent.parts:
        current = current / part
        if current.exists():
            if current.is_symlink():
                raise HumanGateError("ERR_HUMAN_GATE_DIR_SYMLINK", "artifact parent is symlinked", path=current)
            if not current.is_dir():
                raise HumanGateError("ERR_HUMAN_GATE_OUTSIDE_REPO", "artifact parent is not a directory", path=current)
        else:
            current.mkdir()


def ensure_leaf_not_symlink(path: Path) -> None:
    if path.exists():
        if path.is_symlink():
            raise HumanGateError("ERR_HUMAN_GATE_LEAF_SYMLINK", "refusing to overwrite symlinked file", path=path)
        if not path.is_file():
            raise HumanGateError("ERR_HUMAN_GATE_OUTSIDE_REPO", "refusing to overwrite non-file leaf", path=path)


def write_text(path: Path, text: str, *, root: Path) -> None:
    ensure_artifact_parent(root, path)
    ensure_leaf_not_symlink(path)
    write_text_atomic(path, text, root=root)


def write_json(path: Path, data: Any, *, root: Path) -> None:
    write_text(path, canonical_json_text(data), root=root)


def read_json_obj(path: Path, *, code: str, label: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise HumanGateError(code, f"{label} is missing or symlinked", path=path)
    try:
        data = json.loads(path.read_text())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HumanGateError(code, f"{label} is malformed: {exc}", path=path) from exc
    if not isinstance(data, dict):
        raise HumanGateError(code, f"{label} root must be an object", path=path)
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


def require_owned_sentinel(path: Path, name: str, *, tool: str, run_id: str, code: str) -> dict[str, Any]:
    sentinel = read_sentinel(path, name)
    if sentinel is None:
        raise HumanGateError(code, "ownership sentinel is missing or malformed", path=path / name)
    if sentinel.get("tool") != tool or sentinel.get("run_id") != run_id:
        raise HumanGateError(code, "ownership sentinel does not match run", path=path / name)
    return sentinel


def require_string_list(value: Any, *, code: str, message: str, path: Path) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise HumanGateError(code, message, path=path)
    return value


def normalize_words(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


def contains_word(text: str, term: str) -> bool:
    return re.search(rf"(?<![a-z0-9_-]){re.escape(term)}(?![a-z0-9_-])", text) is not None


def validate_attestations(attestations: list[str], approval_path: Path) -> None:
    if not attestations:
        raise HumanGateError("ERR_HUMAN_GATE_ENTRY_REJECTED", "approval must include attestations", path=approval_path)
    normalized = [normalize_words(item) for item in attestations]
    required_negative = normalize_words(REQUIRED_NEGATIVE_ATTESTATION)
    if required_negative not in normalized:
        raise HumanGateError(
            "ERR_HUMAN_GATE_ENTRY_REJECTED",
            "approval must explicitly deny worker execution, merge, deployment, external message, secret access, and dependency installation",
            path=approval_path,
        )
    for item in normalized:
        if item == required_negative:
            continue
        has_forbidden_action = any(contains_word(item, term) for term in FORBIDDEN_ACTION_TERMS)
        has_authorization = any(contains_word(item, term) for term in AUTHORIZATION_TERMS)
        if has_forbidden_action or has_authorization:
            raise HumanGateError("ERR_HUMAN_GATE_ENTRY_REJECTED", "approval attestation exceeds human-gate resolution scope", path=approval_path)


def validate_review_provenance(review_path: str, v8_state: dict[str, Any]) -> None:
    review_dir = resolve_v75(review_path)
    sentinel = require_owned_sentinel(review_dir, V75_SENTINEL, tool="review_frontier_result.py", run_id=review_dir.name, code="ERR_HUMAN_GATE_UNTRUSTED_FRONTIER")
    review_status = read_json_obj(review_dir / "status.json", code="ERR_HUMAN_GATE_UNTRUSTED_FRONTIER", label="V7.5 status.json")
    if review_status.get("status") != "review-approved" or review_status.get("resume_state") != "resumable":
        raise HumanGateError("ERR_HUMAN_GATE_UNTRUSTED_FRONTIER", "V7.5 review is not approved and resumable", path=review_dir / "status.json")
    review_hashes = read_json_obj(review_dir / "hashes.json", code="ERR_HUMAN_GATE_UNTRUSTED_FRONTIER", label="V7.5 hashes.json")
    if review_status.get("snapshots") != review_hashes:
        raise HumanGateError("ERR_HUMAN_GATE_UNTRUSTED_FRONTIER", "V7.5 status snapshots do not match hashes", path=review_dir / "status.json")
    review = read_json_obj(review_dir / "review.json", code="ERR_HUMAN_GATE_UNTRUSTED_FRONTIER", label="V7.5 review.json")
    if review_hashes.get("review_hash") != canonical_hash(review):
        raise HumanGateError("ERR_HUMAN_GATE_UNTRUSTED_FRONTIER", "V7.5 review does not match hashes", path=review_dir / "review.json")
    source_result_path = review.get("source_result_path")
    status_source_result_path = review_status.get("source_result_path")
    sentinel_source_result_path = sentinel.get("source_result_path")
    if not isinstance(source_result_path, str) or not isinstance(status_source_result_path, str) or not isinstance(sentinel_source_result_path, str):
        raise HumanGateError("ERR_HUMAN_GATE_UNTRUSTED_FRONTIER", "V7.5 source result path metadata is missing", path=review_dir / V75_SENTINEL)
    source_result_dir = resolve_v7(source_result_path)
    if resolve_v7(status_source_result_path) != source_result_dir:
        raise HumanGateError("ERR_HUMAN_GATE_UNTRUSTED_FRONTIER", "V7.5 status source result does not match review", path=review_dir / "status.json")
    if resolve_v7(sentinel_source_result_path) != source_result_dir:
        raise HumanGateError("ERR_HUMAN_GATE_UNTRUSTED_FRONTIER", "V7.5 ownership sentinel source result does not match review", path=review_dir / V75_SENTINEL)
    reviewed_results = v8_state.get("reviewed_results")
    if not isinstance(reviewed_results, list):
        raise HumanGateError("ERR_HUMAN_GATE_UNTRUSTED_FRONTIER", "V8 state is missing reviewed_results", path=review_dir / "review.json")
    matched_reviewed_result = False
    for item in reviewed_results:
        if not isinstance(item, dict):
            raise HumanGateError("ERR_HUMAN_GATE_UNTRUSTED_FRONTIER", "V8 reviewed_results entry is malformed", path=review_dir / "review.json")
        item_review_path = item.get("review_path")
        item_source_result_path = item.get("source_result_path")
        if not isinstance(item_review_path, str) or not isinstance(item_source_result_path, str):
            raise HumanGateError("ERR_HUMAN_GATE_UNTRUSTED_FRONTIER", "V8 reviewed_results source metadata is malformed", path=review_dir / "review.json")
        if resolve_v75(item_review_path) == review_dir:
            if resolve_v7(item_source_result_path) != source_result_dir:
                raise HumanGateError("ERR_HUMAN_GATE_UNTRUSTED_FRONTIER", "V8 reviewed result does not match V7.5 source result", path=review_dir / "review.json")
            matched_reviewed_result = True
    if not matched_reviewed_result:
        raise HumanGateError("ERR_HUMAN_GATE_UNTRUSTED_FRONTIER", "V8 state does not reference the trusted V7.5 review", path=review_dir / "review.json")
    source_hashes = v8_state.get("source_hashes")
    if not isinstance(source_hashes, dict):
        raise HumanGateError("ERR_HUMAN_GATE_UNTRUSTED_FRONTIER", "V8 state is missing source_hashes", path=review_dir / "review.json")
    review_semantic = {key: value for key, value in review.items() if key != "created_at"}
    if source_hashes.get("frontier_review_semantic_hash") != canonical_hash(review_semantic):
        raise HumanGateError("ERR_HUMAN_GATE_UNTRUSTED_FRONTIER", "V8 state does not match V7.5 review", path=review_dir / "review.json")


def sentinel_payload(run_id: str, frontier_dir: Path, approval_path: Path) -> dict[str, Any]:
    return {
        "tool": TOOL,
        "schema_version": SCHEMA_VERSION,
        "human_gate_version": HUMAN_GATE_VERSION,
        "run_id": run_id,
        "source_v8_run_path": rel(frontier_dir),
        "approval_path": rel(approval_path),
        "created_at": now_utc(),
    }


def ensure_human_gate_dir(path: Path, run_id: str, frontier_dir: Path, approval_path: Path) -> None:
    path = resolve_v9_out(path)
    if path.exists():
        if path.is_symlink():
            raise HumanGateError("ERR_HUMAN_GATE_DIR_SYMLINK", "V9 output directory is a symlink", path=path)
        if not path.is_dir():
            raise HumanGateError("ERR_HUMAN_GATE_OUTSIDE_REPO", "V9 output exists and is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None:
            raise HumanGateError("ERR_HUMAN_GATE_ARTIFACT_MALFORMED", "existing V9 output is not owned", path=path)
        expected = sentinel_payload(run_id, frontier_dir, approval_path)
        expected["created_at"] = sentinel.get("created_at")
        if sentinel != expected:
            raise HumanGateError("ERR_HUMAN_GATE_ARTIFACT_MALFORMED", "V9 output sentinel does not match this source", path=path)
    path.mkdir(parents=True, exist_ok=True)
    if read_sentinel(path) is None:
        write_json(path / SENTINEL, sentinel_payload(run_id, frontier_dir, approval_path), root=path)


def load_plan_from_v8_state(v8_state: dict[str, Any]) -> tuple[Path, Path, dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    source_v4 = v8_state.get("source_v4_run_path")
    if not isinstance(source_v4, str):
        raise HumanGateError("ERR_HUMAN_GATE_UNTRUSTED_FRONTIER", "V8 state is missing source_v4_run_path")
    v4_dir = resolve_v4(source_v4)
    v4_sentinel = require_owned_sentinel(v4_dir, V4_SENTINEL, tool="orchestrate_workflow.py", run_id=v4_dir.name, code="ERR_HUMAN_GATE_UNTRUSTED_FRONTIER")
    v4_status = read_json_obj(v4_dir / "status.json", code="ERR_HUMAN_GATE_UNTRUSTED_FRONTIER", label="V4 status.json")
    if v4_status.get("status") != "scheduled" or v4_status.get("resume_state") != "resumable":
        raise HumanGateError("ERR_HUMAN_GATE_UNTRUSTED_FRONTIER", "V4 schedule is not resumable", path=v4_dir / "status.json")
    v4_run = read_json_obj(v4_dir / "run.json", code="ERR_HUMAN_GATE_UNTRUSTED_FRONTIER", label="V4 run.json")
    v4_schedule = read_json_obj(v4_dir / "schedule.json", code="ERR_HUMAN_GATE_UNTRUSTED_FRONTIER", label="V4 schedule.json")
    v4_snapshots = v4_status.get("snapshots")
    if not isinstance(v4_snapshots, dict):
        raise HumanGateError("ERR_HUMAN_GATE_UNTRUSTED_FRONTIER", "V4 status is missing snapshots", path=v4_dir / "status.json")
    if v4_snapshots.get("schedule_hash") != canonical_hash(v4_schedule):
        raise HumanGateError("ERR_HUMAN_GATE_UNTRUSTED_FRONTIER", "V4 schedule does not match V4 status", path=v4_dir / "schedule.json")
    source_hashes = v8_state.get("source_hashes")
    if not isinstance(source_hashes, dict):
        raise HumanGateError("ERR_HUMAN_GATE_UNTRUSTED_FRONTIER", "V8 state is missing source_hashes", path=v4_dir / "schedule.json")
    expected_v4_schedule_hash = source_hashes.get("v4_schedule_hash")
    if expected_v4_schedule_hash != canonical_hash(v4_schedule):
        raise HumanGateError("ERR_HUMAN_GATE_UNTRUSTED_FRONTIER", "V4 schedule does not match V8 state", path=v4_dir / "schedule.json")
    expected_v4_run_hash = source_hashes.get("v4_run_hash")
    if expected_v4_run_hash != canonical_hash(v4_run):
        raise HumanGateError("ERR_HUMAN_GATE_UNTRUSTED_FRONTIER", "V4 run does not match V8 state", path=v4_dir / "run.json")
    v3_path = v4_run.get("v3_run_path")
    if not isinstance(v3_path, str):
        raise HumanGateError("ERR_HUMAN_GATE_UNTRUSTED_FRONTIER", "V4 run is missing v3_run_path", path=v4_dir / "run.json")
    if v4_sentinel.get("v3_run_path") != v3_path:
        raise HumanGateError("ERR_HUMAN_GATE_UNTRUSTED_FRONTIER", "V4 ownership sentinel does not match run", path=v4_dir / V4_SENTINEL)
    v3_dir = resolve_v3(v3_path)
    v3_sentinel = require_owned_sentinel(v3_dir, V3_SENTINEL, tool="run_workflow.py", run_id=v3_dir.name, code="ERR_HUMAN_GATE_UNTRUSTED_FRONTIER")
    v3_status = read_json_obj(v3_dir / "status.json", code="ERR_HUMAN_GATE_UNTRUSTED_FRONTIER", label="V3 status.json")
    if v3_sentinel.get("v2_run_path") != v3_status.get("v2_run_path"):
        raise HumanGateError("ERR_HUMAN_GATE_UNTRUSTED_FRONTIER", "V3 ownership sentinel does not match status", path=v3_dir / V3_SENTINEL)
    if v4_snapshots.get("v3_status_hash") != canonical_hash(v3_status):
        raise HumanGateError("ERR_HUMAN_GATE_UNTRUSTED_FRONTIER", "V3 status does not match V4 status", path=v3_dir / "status.json")
    expected_v3_status_hash = source_hashes.get("v3_status_hash")
    if expected_v3_status_hash != canonical_hash(v3_status):
        raise HumanGateError("ERR_HUMAN_GATE_UNTRUSTED_FRONTIER", "V3 status does not match V8 state", path=v3_dir / "status.json")
    v1_path = v3_status.get("v1_run_path")
    if not isinstance(v1_path, str):
        raise HumanGateError("ERR_HUMAN_GATE_UNTRUSTED_FRONTIER", "V3 status is missing v1_run_path", path=v3_dir / "status.json")
    v1_dir = resolve_v1(v1_path)
    v1_sentinel = require_owned_sentinel(v1_dir, V1_SENTINEL, tool="compile_workflow.py", run_id=v1_dir.name, code="ERR_HUMAN_GATE_UNTRUSTED_FRONTIER")
    plan = read_json_obj(v1_dir / "plan.snapshot.json", code="ERR_HUMAN_GATE_UNTRUSTED_FRONTIER", label="plan.snapshot.json")
    if v1_sentinel.get("plan_hash") != canonical_hash(plan):
        raise HumanGateError("ERR_HUMAN_GATE_UNTRUSTED_FRONTIER", "V1 ownership sentinel does not match plan", path=v1_dir / V1_SENTINEL)
    expected_plan_hash = source_hashes.get("plan_snapshot_hash")
    if expected_plan_hash != canonical_hash(plan):
        raise HumanGateError("ERR_HUMAN_GATE_UNTRUSTED_FRONTIER", "plan snapshot does not match V8 state", path=v1_dir / "plan.snapshot.json")
    return v4_dir, v1_dir, v4_run, v4_schedule, v3_status, plan


def worker_index(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    workers = plan.get("workers")
    if not isinstance(workers, list):
        raise HumanGateError("ERR_HUMAN_GATE_PLAN_MALFORMED", "plan workers must be a list")
    indexed: dict[str, dict[str, Any]] = {}
    for worker in workers:
        if not isinstance(worker, dict) or not isinstance(worker.get("id"), str):
            raise HumanGateError("ERR_HUMAN_GATE_PLAN_MALFORMED", "worker is malformed")
        indexed[worker["id"]] = worker
    return indexed


def frontier_for_completed(plan: dict[str, Any], completed: list[str], plan_path: Path) -> tuple[list[str], list[str], list[dict[str, Any]]]:
    phases = plan.get("phases")
    if not isinstance(phases, list):
        raise HumanGateError("ERR_HUMAN_GATE_PLAN_MALFORMED", "plan phases must be a list", path=plan_path)
    workers_by_id = worker_index(plan)
    completed_set = set(completed)
    ready: list[str] = []
    blocked: list[dict[str, Any]] = []
    for phase in phases:
        if not isinstance(phase, dict) or not isinstance(phase.get("id"), str):
            raise HumanGateError("ERR_HUMAN_GATE_PLAN_MALFORMED", "phase is malformed", path=plan_path)
        phase_id = phase["id"]
        if phase_id in completed_set:
            continue
        depends_on = require_string_list(phase.get("depends_on"), code="ERR_HUMAN_GATE_PLAN_MALFORMED", message="phase depends_on is malformed", path=plan_path)
        worker_ids = require_string_list(phase.get("worker_ids"), code="ERR_HUMAN_GATE_PLAN_MALFORMED", message="phase worker_ids is malformed", path=plan_path)
        unknown = [worker_id for worker_id in worker_ids if worker_id not in workers_by_id]
        if unknown:
            raise HumanGateError("ERR_HUMAN_GATE_PLAN_MALFORMED", f"phase references unknown worker: {unknown[0]}", path=plan_path)
        unmet = [dep for dep in depends_on if dep not in completed_set]
        if unmet:
            blocked.append({"phase_id": phase_id, "unmet_dependencies": unmet})
        else:
            ready.append(phase_id)
    cap = 1
    parallelism = plan.get("parallelism")
    if isinstance(parallelism, dict) and isinstance(parallelism.get("concurrency_cap"), int):
        cap = max(1, parallelism["concurrency_cap"])
    return ready, ready[:cap], blocked


def phase_by_id(plan: dict[str, Any], phase_id: str, plan_path: Path) -> dict[str, Any]:
    phases = plan.get("phases")
    if not isinstance(phases, list):
        raise HumanGateError("ERR_HUMAN_GATE_PLAN_MALFORMED", "plan phases must be a list", path=plan_path)
    for phase in phases:
        if isinstance(phase, dict) and phase.get("id") == phase_id:
            return phase
    raise HumanGateError("ERR_HUMAN_GATE_PLAN_MALFORMED", f"plan is missing phase {phase_id}", path=plan_path)


def validate_frontier_packet(
    plan: dict[str, Any],
    completed: list[str],
    selected: list[str],
    packet: dict[str, Any],
    *,
    plan_path: Path,
    status_path: Path,
    packet_path: Path,
) -> None:
    _ready, recomputed_selected, _blocked = frontier_for_completed(plan, completed, plan_path)
    if recomputed_selected != [PHASE_ID] or selected != recomputed_selected:
        raise HumanGateError("ERR_HUMAN_GATE_ENTRY_REJECTED", "V8 selected frontier does not match recomputed plan frontier", path=status_path)
    phase = phase_by_id(plan, PHASE_ID, plan_path)
    phase_outputs = require_string_list(phase.get("outputs"), code="ERR_HUMAN_GATE_PLAN_MALFORMED", message="human_gate outputs are malformed", path=plan_path)
    phase_depends_on = require_string_list(phase.get("depends_on"), code="ERR_HUMAN_GATE_PLAN_MALFORMED", message="human_gate depends_on is malformed", path=plan_path)
    phase_worker_ids = require_string_list(phase.get("worker_ids"), code="ERR_HUMAN_GATE_PLAN_MALFORMED", message="human_gate worker_ids is malformed", path=plan_path)
    if packet.get("phase_id") != PHASE_ID:
        raise HumanGateError("ERR_HUMAN_GATE_ENTRY_REJECTED", "source packet is not human_gate", path=packet_path)
    if packet.get("completed_phase_ids") != completed:
        raise HumanGateError("ERR_HUMAN_GATE_ENTRY_REJECTED", "V8 packet completed phases do not match state", path=packet_path)
    if packet.get("depends_on") != phase_depends_on:
        raise HumanGateError("ERR_HUMAN_GATE_ENTRY_REJECTED", "V8 packet dependencies do not match plan", path=packet_path)
    if packet.get("expected_outputs") != phase_outputs:
        raise HumanGateError("ERR_HUMAN_GATE_ENTRY_REJECTED", "V8 packet outputs do not match plan", path=packet_path)
    if packet.get("worker_ids") != phase_worker_ids:
        raise HumanGateError("ERR_HUMAN_GATE_ENTRY_REJECTED", "V8 packet workers do not match plan", path=packet_path)


def trusted_context(frontier_dir: Path, approval_path: Path) -> dict[str, Any]:
    frontier_dir = resolve_v8(frontier_dir)
    approval_path = resolve_approval(approval_path)
    v8_sentinel = require_owned_sentinel(frontier_dir, V8_SENTINEL, tool="ingest_frontier_review.py", run_id=frontier_dir.name, code="ERR_HUMAN_GATE_UNTRUSTED_FRONTIER")
    status = read_json_obj(frontier_dir / "status.json", code="ERR_HUMAN_GATE_UNTRUSTED_FRONTIER", label="V8 status.json")
    if status.get("status") != "frontier-ready" or status.get("resume_state") != "resumable":
        raise HumanGateError("ERR_HUMAN_GATE_UNTRUSTED_FRONTIER", "V8 frontier is not ready and resumable", path=frontier_dir / "status.json")
    v8_hashes = read_json_obj(frontier_dir / "hashes.json", code="ERR_HUMAN_GATE_UNTRUSTED_FRONTIER", label="V8 hashes.json")
    if status.get("snapshots") != v8_hashes:
        raise HumanGateError("ERR_HUMAN_GATE_UNTRUSTED_FRONTIER", "V8 status snapshots do not match hashes", path=frontier_dir / "status.json")
    selected = require_string_list(status.get("selected_phase_ids"), code="ERR_HUMAN_GATE_UNTRUSTED_FRONTIER", message="V8 selected_phase_ids is malformed", path=frontier_dir / "status.json")
    if selected != [PHASE_ID]:
        raise HumanGateError("ERR_HUMAN_GATE_ENTRY_REJECTED", "V9 first slice accepts only a single human_gate frontier", path=frontier_dir / "status.json")
    v8_run = read_json_obj(frontier_dir / "run.json", code="ERR_HUMAN_GATE_UNTRUSTED_FRONTIER", label="V8 run.json")
    v8_state = read_json_obj(frontier_dir / "state.json", code="ERR_HUMAN_GATE_UNTRUSTED_FRONTIER", label="V8 state.json")
    if v8_sentinel.get("review_path") != v8_run.get("review_path") or not isinstance(v8_run.get("review_path"), str):
        raise HumanGateError("ERR_HUMAN_GATE_UNTRUSTED_FRONTIER", "V8 ownership sentinel does not match run", path=frontier_dir / V8_SENTINEL)
    validate_review_provenance(v8_run["review_path"], v8_state)
    if v8_hashes.get("run_hash") != canonical_hash(v8_run):
        raise HumanGateError("ERR_HUMAN_GATE_UNTRUSTED_FRONTIER", "V8 run does not match hashes", path=frontier_dir / "run.json")
    if v8_hashes.get("state_hash") != canonical_hash(v8_state):
        raise HumanGateError("ERR_HUMAN_GATE_UNTRUSTED_FRONTIER", "V8 state does not match hashes", path=frontier_dir / "state.json")
    packet_paths = v8_run.get("packet_paths")
    if not isinstance(packet_paths, list) or len(packet_paths) != 1 or not isinstance(packet_paths[0], str):
        raise HumanGateError("ERR_HUMAN_GATE_UNTRUSTED_FRONTIER", "V8 run must contain exactly one packet path", path=frontier_dir / "run.json")
    packet_path = frontier_dir / packet_paths[0]
    packet = read_json_obj(packet_path, code="ERR_HUMAN_GATE_UNTRUSTED_FRONTIER", label="V8 packet")
    packet_hashes = v8_hashes.get("packet_hashes")
    packet_id = packet.get("packet_id")
    if not isinstance(packet_hashes, dict) or not isinstance(packet_id, str) or packet_hashes.get(packet_id) != canonical_hash(packet):
        raise HumanGateError("ERR_HUMAN_GATE_UNTRUSTED_FRONTIER", "V8 packet does not match hashes", path=packet_path)
    if packet.get("source_hashes") != v8_state.get("source_hashes"):
        raise HumanGateError("ERR_HUMAN_GATE_UNTRUSTED_FRONTIER", "V8 packet source hashes do not match state", path=packet_path)
    expected_outputs = require_string_list(packet.get("expected_outputs"), code="ERR_HUMAN_GATE_UNTRUSTED_FRONTIER", message="V8 packet expected_outputs is malformed", path=frontier_dir / packet_paths[0])
    if expected_outputs != [APPROVED_OUTPUT]:
        raise HumanGateError("ERR_HUMAN_GATE_ENTRY_REJECTED", "human_gate packet must expect only human-approval.md", path=packet_path)
    completed = require_string_list(v8_state.get("completed_phase_ids"), code="ERR_HUMAN_GATE_UNTRUSTED_FRONTIER", message="V8 completed_phase_ids is malformed", path=frontier_dir / "state.json")
    if PHASE_ID in completed:
        raise HumanGateError("ERR_HUMAN_GATE_ENTRY_REJECTED", "human_gate is already completed", path=frontier_dir / "state.json")
    v4_dir, v1_dir, v4_run, v4_schedule, v3_status, plan = load_plan_from_v8_state(v8_state)
    validate_frontier_packet(
        plan,
        completed,
        selected,
        packet,
        plan_path=v1_dir / "plan.snapshot.json",
        status_path=frontier_dir / "status.json",
        packet_path=packet_path,
    )

    approval = read_json_obj(approval_path, code="ERR_HUMAN_GATE_UNTRUSTED_APPROVAL", label="approval.json")
    if approval.get("decision") != "approve":
        raise HumanGateError("ERR_HUMAN_GATE_ENTRY_REJECTED", "approval decision must be approve", path=approval_path)
    if approval.get("phase_id") != PHASE_ID or approval.get("source_packet_id") != packet.get("packet_id"):
        raise HumanGateError("ERR_HUMAN_GATE_UNTRUSTED_APPROVAL", "approval does not match the V8 packet", path=approval_path)
    if approval.get("source_v8_run_path") != rel(frontier_dir):
        raise HumanGateError("ERR_HUMAN_GATE_UNTRUSTED_APPROVAL", "approval does not match the V8 run", path=approval_path)
    approved_outputs = require_string_list(approval.get("approved_outputs"), code="ERR_HUMAN_GATE_UNTRUSTED_APPROVAL", message="approved_outputs is malformed", path=approval_path)
    if approved_outputs != [APPROVED_OUTPUT]:
        raise HumanGateError("ERR_HUMAN_GATE_ENTRY_REJECTED", "approval must approve only human-approval.md", path=approval_path)
    attestations = require_string_list(approval.get("attestations"), code="ERR_HUMAN_GATE_UNTRUSTED_APPROVAL", message="attestations is malformed", path=approval_path)
    validate_attestations(attestations, approval_path)

    return {
        "frontier_dir": frontier_dir,
        "approval_path": approval_path,
        "approval": approval,
        "v8_status": status,
        "v8_run": v8_run,
        "v8_state": v8_state,
        "v8_packet": packet,
        "v4_dir": v4_dir,
        "v4_run": v4_run,
        "v4_schedule": v4_schedule,
        "v3_status": v3_status,
        "v1_dir": v1_dir,
        "plan": plan,
    }


def source_hashes(context: dict[str, Any]) -> dict[str, str]:
    v8_run_semantic = {key: value for key, value in context["v8_run"].items() if key != "created_at"}
    return {
        "approval_hash": canonical_hash(context["approval"]),
        "v8_run_semantic_hash": canonical_hash(v8_run_semantic),
        "v8_state_hash": canonical_hash(context["v8_state"]),
        "v8_packet_hash": canonical_hash(context["v8_packet"]),
        "v4_run_hash": canonical_hash(context["v4_run"]),
        "v4_schedule_hash": canonical_hash(context["v4_schedule"]),
        "v3_status_hash": canonical_hash(context["v3_status"]),
        "plan_snapshot_hash": canonical_hash(context["plan"]),
    }


def completed_phase_ids(context: dict[str, Any]) -> list[str]:
    completed = require_string_list(
        context["v8_state"].get("completed_phase_ids"),
        code="ERR_HUMAN_GATE_UNTRUSTED_FRONTIER",
        message="V8 completed_phase_ids is malformed",
        path=context["frontier_dir"] / "state.json",
    )
    return completed if PHASE_ID in completed else [*completed, PHASE_ID]


def build_state(context: dict[str, Any]) -> dict[str, Any]:
    completed = completed_phase_ids(context)
    ready, selected, blocked = frontier_for_completed(context["plan"], completed, context["v1_dir"] / "plan.snapshot.json")
    if selected or blocked:
        raise HumanGateError("ERR_HUMAN_GATE_ENTRY_REJECTED", "V9 first slice only supports terminal human_gate completion", path=context["frontier_dir"] / "state.json")
    reviewed = require_string_list(
        context["v8_state"].get("reviewed_phase_ids"),
        code="ERR_HUMAN_GATE_UNTRUSTED_FRONTIER",
        message="V8 reviewed_phase_ids is malformed",
        path=context["frontier_dir"] / "state.json",
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "human_gate_version": HUMAN_GATE_VERSION,
        "source_plan_id": context["plan"].get("plan_id"),
        "source_v8_run_path": rel(context["frontier_dir"]),
        "source_approval_path": rel(context["approval_path"]),
        "source_v4_run_path": rel(context["v4_dir"]),
        "completed_phase_ids": completed,
        "reviewed_phase_ids": reviewed,
        "human_approved_phase_ids": [PHASE_ID],
        "ready_phase_ids": ready,
        "selected_phase_ids": selected,
        "blocked_phases": blocked,
        "approval_records": [
            {
                "approval_path": rel(context["approval_path"]),
                "approval_id": context["approval"].get("approval_id"),
                "phase_id": PHASE_ID,
                "decision": context["approval"].get("decision"),
                "approved_outputs": context["approval"].get("approved_outputs", []),
            }
        ],
        "source_hashes": source_hashes(context),
    }


def status_name(state: dict[str, Any]) -> str:
    if state.get("selected_phase_ids"):
        return "frontier-ready"
    if state.get("blocked_phases"):
        return "blocked"
    return "workflow-complete"


def render_approval_markdown(context: dict[str, Any], state: dict[str, Any]) -> str:
    approval = context["approval"]
    lines = [
        "# V9 Human Gate Approval",
        "",
        f"Approval: `{approval.get('approval_id')}`",
        f"Decision: `{approval.get('decision')}`",
        f"Source V8 run: `{rel(context['frontier_dir'])}`",
        f"Phase: `{PHASE_ID}`",
        "",
        "## Approved Outputs",
        f"- `{APPROVED_OUTPUT}`",
        "",
        "## Attestations",
    ]
    for item in approval.get("attestations", []):
        lines.append(f"- {item}")
    lines.extend(["", "## Result", "", f"Status after approval: `{status_name(state)}`"])
    return "\n".join(lines) + "\n"


def build_run(run_id: str, frontier_dir: Path, approval_path: Path, *, created_at: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "human_gate_version": HUMAN_GATE_VERSION,
        "run_id": run_id,
        "created_at": created_at or now_utc(),
        "source_v8_run_path": rel(frontier_dir),
        "approval_path": rel(approval_path),
        "state_path": "state.json",
        "approval_markdown_path": "human-approval.md",
        "journal_paths": ["journal/0000.json"],
    }


def build_journal(context: dict[str, Any], state: dict[str, Any], *, created_at: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "human_gate_version": HUMAN_GATE_VERSION,
        "event_id": "0000",
        "event": "v9-human-gate-resolved",
        "created_at": created_at or now_utc(),
        "source_v8_run_path": rel(context["frontier_dir"]),
        "approval_path": rel(context["approval_path"]),
        "completed_phase_ids": state["completed_phase_ids"],
        "selected_phase_ids": state["selected_phase_ids"],
        "source_hashes": state["source_hashes"],
    }


def build_hashes(run: dict[str, Any], state: dict[str, Any], approval_markdown: str, journal: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_hash": canonical_hash(run),
        "state_hash": canonical_hash(state),
        "approval_markdown_hash": sha256_text(approval_markdown),
        "journal_hash": canonical_hash(journal),
    }


def build_status(run_id: str, *, state: dict[str, Any] | None, hashes: dict[str, Any] | None, status: str, resume_state: str, invalidators: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "human_gate_version": HUMAN_GATE_VERSION,
        "run_id": run_id,
        "status": status,
        "resume_state": resume_state,
        "state_path": "state.json" if state else None,
        "completed_phase_ids": state.get("completed_phase_ids", []) if state else [],
        "reviewed_phase_ids": state.get("reviewed_phase_ids", []) if state else [],
        "human_approved_phase_ids": state.get("human_approved_phase_ids", []) if state else [],
        "ready_phase_ids": state.get("ready_phase_ids", []) if state else [],
        "selected_phase_ids": state.get("selected_phase_ids", []) if state else [],
        "invalidators": invalidators or [],
        "snapshots": hashes or {},
        "checked_at": now_utc(),
    }


def render_resume(status: dict[str, Any]) -> str:
    lines = [
        "# V9 Human Gate Resume",
        "",
        f"Run: `{status['run_id']}`",
        f"Status: `{status['status']}`",
        f"Resume state: `{status['resume_state']}`",
        "",
        "## Completed Phases",
    ]
    for phase_id in status.get("completed_phase_ids", []):
        lines.append(f"- `{phase_id}`")
    lines.extend(["", "## Human Approved Phases"])
    approved = status.get("human_approved_phase_ids", [])
    if approved:
        for phase_id in approved:
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


def write_error_status(out_dir: Path, run_id: str, frontier_dir: Path, approval_path: Path, error: HumanGateError) -> dict[str, Any]:
    ensure_human_gate_dir(out_dir, run_id, frontier_dir, approval_path)
    status = build_status(run_id, state=None, hashes=None, status="invalid", resume_state="invalid", invalidators=[error.to_record()])
    write_status(out_dir, status)
    return status


def start_resolution(frontier_dir: Path, approval_path: Path, *, out_dir: Path | None = None) -> dict[str, Any]:
    frontier_dir = resolve_v8(frontier_dir)
    approval_path = resolve_approval(approval_path)
    out_dir = resolve_v9_out(out_dir) if out_dir is not None else V9_OUT_ROOT / frontier_dir.name
    run_id = out_dir.name
    try:
        ensure_human_gate_dir(out_dir, run_id, frontier_dir, approval_path)
        context = trusted_context(frontier_dir, approval_path)
        state = build_state(context)
        approval_markdown = render_approval_markdown(context, state)
        run = build_run(run_id, frontier_dir, approval_path)
        journal = build_journal(context, state)
        hashes = build_hashes(run, state, approval_markdown, journal)
        status = build_status(run_id, state=state, hashes=hashes, status=status_name(state), resume_state="fresh")
    except HumanGateError as exc:
        status = write_error_status(out_dir, run_id, frontier_dir, approval_path, exc)
        return {"status": status, "out_dir": out_dir}
    write_json(out_dir / "run.json", run, root=out_dir)
    write_json(out_dir / "state.json", state, root=out_dir)
    write_text(out_dir / "human-approval.md", approval_markdown, root=out_dir)
    write_json(out_dir / "journal" / "0000.json", journal, root=out_dir)
    write_json(out_dir / "hashes.json", hashes, root=out_dir)
    write_status(out_dir, status)
    return {"status": status, "out_dir": out_dir, "state": state}


def validate_sentinel(run_dir: Path, run_id: str, frontier_dir: Path, approval_path: Path) -> None:
    sentinel = read_sentinel(run_dir)
    if sentinel is None:
        raise HumanGateError("ERR_HUMAN_GATE_ARTIFACT_MALFORMED", "V9 output is missing ownership sentinel", path=run_dir / SENTINEL)
    expected = sentinel_payload(run_id, frontier_dir, approval_path)
    expected["created_at"] = sentinel.get("created_at")
    if sentinel != expected:
        raise HumanGateError("ERR_HUMAN_GATE_ARTIFACT_MALFORMED", "V9 output sentinel does not match sources", path=run_dir / SENTINEL)


def resume_resolution(run_dir: Path) -> dict[str, Any]:
    run_dir = resolve_v9_out(run_dir)
    run_id = run_dir.name
    sentinel = read_sentinel(run_dir)
    if sentinel is None or not isinstance(sentinel.get("source_v8_run_path"), str) or not isinstance(sentinel.get("approval_path"), str):
        raise HumanGateError("ERR_HUMAN_GATE_ARTIFACT_MALFORMED", "sentinel is missing source paths", path=run_dir / SENTINEL)
    try:
        frontier_dir = resolve_v8(sentinel["source_v8_run_path"])
        approval_path = resolve_approval(sentinel["approval_path"])
        validate_sentinel(run_dir, run_id, frontier_dir, approval_path)
    except HumanGateError as exc:
        status = build_status(run_id, state=None, hashes=None, status="invalid", resume_state="invalidated", invalidators=[exc.to_record()])
        write_status(run_dir, status)
        return {"status": status, "out_dir": run_dir}
    try:
        run = read_json_obj(run_dir / "run.json", code="ERR_HUMAN_GATE_ARTIFACT_MALFORMED", label="run.json")
        state = read_json_obj(run_dir / "state.json", code="ERR_HUMAN_GATE_ARTIFACT_MALFORMED", label="state.json")
        approval_markdown_path = run_dir / "human-approval.md"
        if not approval_markdown_path.is_file() or approval_markdown_path.is_symlink():
            raise HumanGateError("ERR_HUMAN_GATE_ARTIFACT_MALFORMED", "human-approval.md is missing or symlinked", path=approval_markdown_path)
        approval_markdown = approval_markdown_path.read_text()
        journal = read_json_obj(run_dir / "journal" / "0000.json", code="ERR_HUMAN_GATE_ARTIFACT_MALFORMED", label="journal")
        hashes = read_json_obj(run_dir / "hashes.json", code="ERR_HUMAN_GATE_ARTIFACT_MALFORMED", label="hashes.json")
    except HumanGateError as exc:
        status = build_status(run_id, state=None, hashes=None, status="invalid", resume_state="invalidated", invalidators=[exc.to_record()])
        write_status(run_dir, status)
        return {"status": status, "out_dir": run_dir}

    invalidators: list[dict[str, Any]] = []
    expected_state = state
    expected_hashes: dict[str, Any] | None = None
    try:
        context = trusted_context(frontier_dir, approval_path)
        expected_state = build_state(context)
        expected_markdown = render_approval_markdown(context, expected_state)
        expected_run = build_run(run_id, frontier_dir, approval_path, created_at=str(run.get("created_at")))
        expected_journal = build_journal(context, expected_state, created_at=str(journal.get("created_at")))
        expected_hashes = build_hashes(expected_run, expected_state, expected_markdown, expected_journal)
        if run != expected_run:
            invalidators.append({"code": "ERR_HUMAN_GATE_ARTIFACT_MALFORMED", "message": "run.json does not match current inputs"})
        if state != expected_state:
            invalidators.append({"code": "ERR_HUMAN_GATE_ARTIFACT_MALFORMED", "message": "state.json does not match current inputs"})
        if approval_markdown != expected_markdown:
            invalidators.append({"code": "ERR_HUMAN_GATE_ARTIFACT_MALFORMED", "message": "human-approval.md does not match current inputs"})
        if journal != expected_journal:
            invalidators.append({"code": "ERR_HUMAN_GATE_ARTIFACT_MALFORMED", "message": "journal does not match current inputs"})
        if hashes != expected_hashes:
            invalidators.append({"code": "ERR_HUMAN_GATE_ARTIFACT_MALFORMED", "message": "hashes.json does not match current inputs"})
    except HumanGateError as exc:
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
        raise HumanGateError("ERR_HUMAN_GATE_ARTIFACT_MALFORMED", "existing self-test output is not owned", path=path)
    try:
        sentinel = json.loads(sentinel_path.read_text())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HumanGateError("ERR_HUMAN_GATE_ARTIFACT_MALFORMED", f"existing self-test sentinel is malformed: {exc}", path=sentinel_path) from exc
    if not isinstance(sentinel, dict) or sentinel.get("tool") != tool:
        raise HumanGateError("ERR_HUMAN_GATE_ARTIFACT_MALFORMED", "existing self-test output is not owned by expected tool", path=path)
    shutil.rmtree(path)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise HumanGateError("ERR_HUMAN_GATE_SELF_TEST_FAILED", message)


def self_test() -> None:
    frontier_dir = V8_OUT_ROOT / "v32-semantic-dogfood"
    approval_path = APPROVAL_ROOT / "dogfood-human-approval.json"
    unsafe_approval_path = APPROVAL_ROOT / "unsafe-authorizes-execution.json"
    punctuated_approval_path = APPROVAL_ROOT / "unsafe-punctuated-approval.json"
    out_dir = V9_OUT_ROOT / "human-gate-self-test"
    unsafe_out_dir = V9_OUT_ROOT / "human-gate-unsafe-self-test"
    punctuated_out_dir = V9_OUT_ROOT / "human-gate-punctuated-self-test"
    mismatched_review_dir = V75_OUT_ROOT / "human-gate-review-sentinel-mismatch"
    reset_owned(out_dir, SENTINEL, TOOL)
    reset_owned(unsafe_out_dir, SENTINEL, TOOL)
    reset_owned(punctuated_out_dir, SENTINEL, TOOL)
    reset_owned(mismatched_review_dir, V75_SENTINEL, "review_frontier_result.py")
    started = start_resolution(frontier_dir, approval_path, out_dir=out_dir)
    require(started["status"]["status"] == "workflow-complete", "human gate approval should complete the dogfood workflow")
    require(started["status"]["completed_phase_ids"] == ["release_inventory", "evidence_review", "release_decision", "human_gate"], "completed phases should include human_gate")
    require(started["status"]["human_approved_phase_ids"] == ["human_gate"], "human_gate should be recorded as human-approved")
    require(started["status"]["selected_phase_ids"] == [], "completed dogfood workflow should not select a new frontier")
    resumed = resume_resolution(out_dir)
    require(resumed["status"]["resume_state"] == "resumable", "clean human gate resolution should resume")
    state = read_json_obj(out_dir / "state.json", code="ERR_HUMAN_GATE_ARTIFACT_MALFORMED", label="state.json")
    state["completed_phase_ids"] = ["tampered"]
    write_json(out_dir / "state.json", state, root=out_dir)
    tampered = resume_resolution(out_dir)
    require(tampered["status"]["status"] == "invalid", "tampered V9 state should invalidate")
    unsafe = start_resolution(frontier_dir, unsafe_approval_path, out_dir=unsafe_out_dir)
    require(unsafe["status"]["status"] == "invalid", "approval that authorizes forbidden actions should be rejected")
    require(
        unsafe["status"]["invalidators"][0]["code"] == "ERR_HUMAN_GATE_ENTRY_REJECTED",
        "unsafe approval should fail at the human-gate entry boundary",
    )
    punctuated = start_resolution(frontier_dir, punctuated_approval_path, out_dir=punctuated_out_dir)
    require(punctuated["status"]["status"] == "invalid", "punctuated unsafe approval should be rejected")
    trusted = trusted_context(frontier_dir, approval_path)

    shutil.copytree(V75_OUT_ROOT / "v32-semantic-dogfood", mismatched_review_dir)
    mismatched_sentinel = read_json_obj(mismatched_review_dir / V75_SENTINEL, code="ERR_HUMAN_GATE_ARTIFACT_MALFORMED", label="mismatched review sentinel")
    mismatched_sentinel["run_id"] = mismatched_review_dir.name
    mismatched_sentinel["source_result_path"] = "out/v7/not-the-reviewed-result"
    write_json(mismatched_review_dir / V75_SENTINEL, mismatched_sentinel, root=mismatched_review_dir)
    try:
        validate_review_provenance(rel(mismatched_review_dir), trusted["v8_state"])
    except HumanGateError:
        pass
    else:
        raise HumanGateError("ERR_HUMAN_GATE_SELF_TEST_FAILED", "mismatched V7.5 sentinel source should be rejected")

    post_gate_plan = {
        "workers": [{"id": "human-reviewer"}],
        "parallelism": {"concurrency_cap": 1},
        "phases": [
            {"id": "done", "depends_on": [], "worker_ids": ["human-reviewer"], "outputs": ["done.md"]},
            {"id": PHASE_ID, "depends_on": ["done"], "worker_ids": ["human-reviewer"], "outputs": [APPROVED_OUTPUT]},
            {"id": "after_gate", "depends_on": [PHASE_ID], "worker_ids": ["human-reviewer"], "outputs": ["after.md"]},
        ],
    }
    _ready, selected, blocked = frontier_for_completed(post_gate_plan, ["done"], frontier_dir / "synthetic-plan.json")
    require(selected == [PHASE_ID] and blocked == [{"phase_id": "after_gate", "unmet_dependencies": [PHASE_ID]}], "synthetic pre-approval frontier should select human_gate and block downstream work")
    validate_frontier_packet(
        post_gate_plan,
        ["done"],
        [PHASE_ID],
        {
            "phase_id": PHASE_ID,
            "completed_phase_ids": ["done"],
            "depends_on": ["done"],
            "expected_outputs": [APPROVED_OUTPUT],
            "worker_ids": ["human-reviewer"],
        },
        plan_path=frontier_dir / "synthetic-plan.json",
        status_path=frontier_dir / "synthetic-status.json",
        packet_path=frontier_dir / "synthetic-packet.json",
    )

    tampered_packet = dict(trusted["v8_packet"])
    tampered_packet["completed_phase_ids"] = ["release_inventory"]
    try:
        validate_frontier_packet(
            trusted["plan"],
            ["release_inventory", "evidence_review", "release_decision"],
            ["human_gate"],
            tampered_packet,
            plan_path=trusted["v1_dir"] / "plan.snapshot.json",
            status_path=frontier_dir / "status.json",
            packet_path=frontier_dir / "packets" / "0001.human_gate.packet.json",
        )
    except HumanGateError:
        pass
    else:
        raise HumanGateError("ERR_HUMAN_GATE_SELF_TEST_FAILED", "tampered V8 frontier packet should be rejected")
    print("resolve_human_gate self-test: pass")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frontier", help="trusted V8 frontier directory under out/v8")
    parser.add_argument("--approval", help="tracked approval JSON under fixtures/v9/approvals")
    parser.add_argument("--resume", help="V9 output directory under out/v9")
    parser.add_argument("--out", help="V9 output directory")
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if args.self_test:
            self_test()
            return 0
        if args.frontier and args.approval:
            result = start_resolution(Path(args.frontier), Path(args.approval), out_dir=Path(args.out) if args.out else None)
            print(canonical_json_text(result["status"]))
            return 0 if result["status"]["status"] in SUCCESS_STATUSES else 1
        if args.resume:
            result = resume_resolution(Path(args.resume))
            print(canonical_json_text(result["status"]))
            return 0 if result["status"]["status"] in SUCCESS_STATUSES else 1
        raise HumanGateError("ERR_HUMAN_GATE_ARGUMENTS", "expected --frontier with --approval, --resume, or --self-test")
    except HumanGateError as exc:
        print(canonical_json_text(exc.to_record()), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
