#!/usr/bin/env python3
"""Prepare a deterministic V3 runtime step from trusted V2.5 evidence."""

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
    CompileError,
    canonical_hash,
    canonical_json_text,
    compile_plan,
    read_json,
    sha256_text,
    write_text_atomic,
)
from execute_packet import (  # noqa: E402
    ExecError,
    append_review_contract,
    execute_local_shell,
    git_text,
    prepare_repair,
    review_contract,
    review_execution,
    review_resume,
    worktree_path,
)


TOOL = "run_workflow.py"
SCHEMA_VERSION = "1.0"
RUNTIME_VERSION = "0.1.0"
V1_OUT_ROOT = ROOT / "out" / "v1"
V2_OUT_ROOT = ROOT / "out" / "v2"
V3_OUT_ROOT = ROOT / "out" / "v3"
SENTINEL = ".run_workflow-owned.json"
TRUSTED_V3_MANIFEST = ROOT / "fixtures" / "v3" / "manifest.json"
ACCEPTED_STATES = {"review-approved", "repair-verified"}
REJECTED_STATES = {"failed", "invalid", "review-pending", "changes-requested", "repair-prepared"}
ALLOWED_FIXTURE_TYPES = {
    "approved-advance",
    "reject-review-approved-manual",
    "reject-changes-requested",
    "reject-repair-prepared",
    "needs-human-requires-approval",
    "needs-human-approved",
    "resume-clean",
    "resume-stale-v25-status",
    "resume-tampered-next-packet",
    "resume-tampered-journal",
    "resume-non-owned-dir",
    "resume-human-approved-string",
    "reject-unmatched-first-slice",
}


class RuntimeErrorRecord(ValueError):
    """Structured V3 runtime failure."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        path: Path | str | None = None,
        fixture_id: str | None = None,
    ) -> None:
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
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def rel(path: Path) -> str:
    resolved = path.resolve(strict=False)
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return str(resolved)


def reject_traversal(path: Path, code: str, message: str) -> None:
    if any(part == ".." for part in path.parts):
        raise RuntimeErrorRecord(code, message, path=path)


def check_components_not_symlink(path: Path, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise RuntimeErrorRecord(code, "path contains a symlink", path=current)


def resolve_under_out(value: str | Path, root: Path, *, label: str) -> Path:
    raw = Path(value)
    reject_traversal(raw, "ERR_RUNTIME_OUTSIDE_REPO", f"{label} path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    out_root = root.resolve(strict=False)
    forbidden = {ROOT.resolve(), (ROOT / "out").resolve(strict=False), out_root}
    if resolved in forbidden:
        raise RuntimeErrorRecord("ERR_RUNTIME_OUTSIDE_REPO", f"{label} path must name a run directory", path=value)
    try:
        resolved.relative_to(out_root)
    except ValueError as exc:
        raise RuntimeErrorRecord("ERR_RUNTIME_OUTSIDE_REPO", f"{label} path must resolve under {out_root}", path=value) from exc
    check_components_not_symlink(candidate, "ERR_RUNTIME_DIR_SYMLINK")
    return resolved


def resolve_v2_dir(value: str | Path) -> Path:
    return resolve_under_out(value, V2_OUT_ROOT, label="V2.5 evidence")


def resolve_v3_out(value: str | Path) -> Path:
    return resolve_under_out(value, V3_OUT_ROOT, label="V3 output")


def ensure_contained(root: Path, path: Path) -> None:
    target = path if path.is_absolute() else root / path
    reject_traversal(path, "ERR_RUNTIME_OUTSIDE_REPO", "artifact path escapes owned directory")
    try:
        target.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError as exc:
        raise RuntimeErrorRecord("ERR_RUNTIME_OUTSIDE_REPO", "artifact path escapes owned directory", path=target) from exc


def ensure_artifact_parent(root: Path, path: Path) -> None:
    ensure_contained(root, path)
    current = root.resolve(strict=False)
    for part in path.resolve(strict=False).relative_to(current).parent.parts:
        current = current / part
        if current.exists():
            if current.is_symlink():
                raise RuntimeErrorRecord("ERR_RUNTIME_DIR_SYMLINK", "artifact parent is symlinked", path=current)
            if not current.is_dir():
                raise RuntimeErrorRecord("ERR_RUNTIME_OUTSIDE_REPO", "artifact parent is not a directory", path=current)
        else:
            current.mkdir()


def ensure_leaf_not_symlink(path: Path) -> None:
    if path.exists():
        if path.is_symlink():
            raise RuntimeErrorRecord("ERR_RUNTIME_LEAF_SYMLINK", "refusing to overwrite symlinked file", path=path)
        if not path.is_file():
            raise RuntimeErrorRecord("ERR_RUNTIME_OUTSIDE_REPO", "refusing to overwrite non-file leaf", path=path)


def write_text(path: Path, text: str, *, root: Path) -> None:
    ensure_artifact_parent(root, path)
    ensure_leaf_not_symlink(path)
    write_text_atomic(path, text, root=root)


def write_json(path: Path, data: Any, *, root: Path) -> None:
    write_text(path, canonical_json_text(data), root=root)


def read_json_obj(path: Path, *, code: str, label: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise RuntimeErrorRecord(code, f"{label} is missing or symlinked", path=path)
    try:
        data = json.loads(path.read_text())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeErrorRecord(code, f"{label} is malformed: {exc}", path=path) from exc
    if not isinstance(data, dict):
        raise RuntimeErrorRecord(code, f"{label} root must be an object", path=path)
    return data


def read_sentinel(path: Path) -> dict[str, Any] | None:
    sentinel = path / SENTINEL
    if not sentinel.is_file() or sentinel.is_symlink():
        return None
    try:
        data = json.loads(sentinel.read_text())
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def sentinel_payload(run_id: str, v2_dir: Path) -> dict[str, Any]:
    return {
        "tool": TOOL,
        "schema_version": SCHEMA_VERSION,
        "runtime_version": RUNTIME_VERSION,
        "run_id": run_id,
        "v2_run_path": rel(v2_dir),
        "created_at": now_utc(),
    }


def ensure_v3_dir(path: Path, run_id: str, v2_dir: Path) -> None:
    path = resolve_v3_out(path)
    if path.exists():
        if path.is_symlink():
            raise RuntimeErrorRecord("ERR_RUNTIME_DIR_SYMLINK", "V3 output directory is a symlink", path=path)
        if not path.is_dir():
            raise RuntimeErrorRecord("ERR_RUNTIME_OUTSIDE_REPO", "V3 output exists and is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None:
            raise RuntimeErrorRecord("ERR_RUNTIME_ARTIFACT_MALFORMED", "existing V3 output is not runtime-owned", path=path)
        if sentinel.get("tool") != TOOL or sentinel.get("run_id") != run_id or sentinel.get("v2_run_path") != rel(v2_dir):
            raise RuntimeErrorRecord("ERR_RUNTIME_ARTIFACT_MALFORMED", "existing V3 output sentinel does not match this run", path=path)
    path.mkdir(parents=True, exist_ok=True)
    if read_sentinel(path) is None:
        write_json(path / SENTINEL, sentinel_payload(run_id, v2_dir), root=path)


def prepare_manifest_suite(path: Path, suite_id: str) -> None:
    path = resolve_v3_out(path)
    if path.exists():
        if path.is_symlink():
            raise RuntimeErrorRecord("ERR_RUNTIME_DIR_SYMLINK", "manifest suite directory is a symlink", path=path)
        if not path.is_dir():
            raise RuntimeErrorRecord("ERR_RUNTIME_OUTSIDE_REPO", "manifest suite path is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("run_id") != suite_id or sentinel.get("mode") != "manifest":
            raise RuntimeErrorRecord("ERR_RUNTIME_ARTIFACT_MALFORMED", "existing manifest suite is not runtime-owned", path=path)
        shutil.rmtree(path)
    path.mkdir(parents=True)
    payload = sentinel_payload(suite_id, path)
    payload["mode"] = "manifest"
    write_json(path / SENTINEL, payload, root=path)


def v1_path_from_v25_status(status: dict[str, Any]) -> Path:
    value = status.get("v1_run_path")
    if not isinstance(value, str) or not value:
        raise RuntimeErrorRecord("ERR_RUNTIME_ENTRY_REJECTED", "V2.5 status is missing v1_run_path")
    path = Path(value)
    candidate = path if path.is_absolute() else ROOT / path
    try:
        candidate.resolve(strict=False).relative_to(V1_OUT_ROOT.resolve(strict=False))
    except ValueError as exc:
        raise RuntimeErrorRecord("ERR_RUNTIME_ENTRY_REJECTED", "v1_run_path does not resolve under out/v1", path=value) from exc
    return candidate.resolve(strict=False)


def load_plan_snapshot(v1_dir: Path) -> dict[str, Any]:
    return read_json_obj(v1_dir / "plan.snapshot.json", code="ERR_RUNTIME_ENTRY_REJECTED", label="plan.snapshot.json")


def load_v1_packet(v1_dir: Path) -> dict[str, Any]:
    return read_json_obj(v1_dir / "packets" / "001-first-slice.packet.json", code="ERR_RUNTIME_ENTRY_REJECTED", label="V1 first-slice packet")


def validate_terminal_state(status: dict[str, Any], *, human_approved: bool) -> None:
    state = status.get("status")
    if state in ACCEPTED_STATES:
        return
    if state in REJECTED_STATES or state == "needs-human":
        raise RuntimeErrorRecord("ERR_RUNTIME_ENTRY_REJECTED", f"V3 cannot advance from V2.5 state: {state}")
    raise RuntimeErrorRecord("ERR_RUNTIME_ENTRY_REJECTED", f"unsupported V2.5 state: {state}")


def latest_verified_attempt(status: dict[str, Any], *, human_approved: bool) -> dict[str, Any] | None:
    attempts = status.get("attempts")
    if not isinstance(attempts, list) or not attempts or not isinstance(attempts[-1], dict):
        raise RuntimeErrorRecord("ERR_RUNTIME_ENTRY_REJECTED", "V2.5 status is missing latest attempt evidence")
    latest = attempts[-1]
    if latest.get("status") != "verified" or latest.get("verification_result") != "pass":
        raise RuntimeErrorRecord("ERR_RUNTIME_ENTRY_REJECTED", "V3 requires reviewed V2 evidence with automatic verification pass")
    verification = latest.get("verification")
    if not isinstance(verification, list):
        raise RuntimeErrorRecord("ERR_RUNTIME_ENTRY_REJECTED", "V2.5 latest attempt verification is malformed")
    automatic = [item for item in verification if isinstance(item, dict) and item.get("mode") == "automatic"]
    if not automatic or any(item.get("result") != "pass" for item in automatic):
        raise RuntimeErrorRecord("ERR_RUNTIME_ENTRY_REJECTED", "V3 requires passing automatic verification evidence")
    return latest


def trusted_v25_context(v2_dir: Path, *, human_approved: bool) -> dict[str, Any]:
    v2_dir = resolve_v2_dir(v2_dir)
    existing_status = read_json_obj(v2_dir / "status.json", code="ERR_RUNTIME_ENTRY_REJECTED", label="V2.5 status.json")
    v1_dir = v1_path_from_v25_status(existing_status)
    try:
        resumed = review_resume(v1_dir, out_dir=v2_dir)
    except ExecError as exc:
        raise RuntimeErrorRecord("ERR_RUNTIME_STALE_V25", exc.message, path=exc.path) from exc
    status = resumed["status"]
    if status.get("status") == "invalid":
        invalidators = status.get("invalidators")
        message = "V2.5 resume is invalid"
        if isinstance(invalidators, list) and invalidators:
            first = invalidators[0]
            if isinstance(first, dict) and isinstance(first.get("message"), str):
                message = first["message"]
        raise RuntimeErrorRecord("ERR_RUNTIME_STALE_V25", message, path=v2_dir / "status.json")
    validate_terminal_state(status, human_approved=human_approved)
    verified_attempt = latest_verified_attempt(status, human_approved=human_approved)
    stable_status = dict(status)
    stable_status.pop("checked_at", None)
    plan = load_plan_snapshot(v1_dir)
    v1_packet = load_v1_packet(v1_dir)
    return {
        "v1_dir": v1_dir,
        "v2_dir": v2_dir,
        "v25_status": stable_status,
        "plan": plan,
        "v1_packet": v1_packet,
        "verified_attempt": verified_attempt,
        "human_approved": human_approved,
    }


def phase_by_id(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    phases = plan.get("phases")
    if not isinstance(phases, list) or not phases:
        raise RuntimeErrorRecord("ERR_RUNTIME_ENTRY_REJECTED", "plan snapshot has no phases")
    indexed = {}
    for phase in phases:
        if not isinstance(phase, dict) or not isinstance(phase.get("id"), str):
            raise RuntimeErrorRecord("ERR_RUNTIME_ENTRY_REJECTED", "plan phase is malformed")
        indexed[phase["id"]] = phase
    return indexed


def reviewed_evidence_text(context: dict[str, Any]) -> str:
    attempt = context.get("verified_attempt")
    if attempt is None:
        return ""
    attempt_id = attempt.get("attempt_id")
    if not isinstance(attempt_id, str) or not re.fullmatch(r"\d{4}", attempt_id):
        raise RuntimeErrorRecord("ERR_RUNTIME_ENTRY_REJECTED", "V2.5 latest attempt id is malformed")
    attempt_dir = context["v2_dir"] / "attempts" / attempt_id
    verification = attempt.get("verification")
    if not isinstance(verification, list):
        raise RuntimeErrorRecord("ERR_RUNTIME_ENTRY_REJECTED", "V2.5 latest verification evidence is malformed")
    parts = []
    for item in verification:
        if not isinstance(item, dict) or item.get("mode") != "automatic" or item.get("result") != "pass":
            continue
        checked_state_path = item.get("checked_state_path")
        if isinstance(checked_state_path, str):
            checked = read_json_obj(attempt_dir / checked_state_path, code="ERR_RUNTIME_ENTRY_REJECTED", label="verification checked state")
            parts.append(canonical_json_text(checked))
    return "\n".join(parts).lower()


def completed_first_slice_phase_ids(context: dict[str, Any]) -> set[str]:
    phase_context = context["v1_packet"].get("phase_context")
    if not isinstance(phase_context, list) or not phase_context:
        raise RuntimeErrorRecord("ERR_RUNTIME_ENTRY_REJECTED", "V1 packet phase context is malformed")
    first_slice = context["v1_packet"].get("source_first_slice")
    if not isinstance(first_slice, dict):
        raise RuntimeErrorRecord("ERR_RUNTIME_ENTRY_REJECTED", "V1 packet first-slice context is malformed")
    first_slice_text = " ".join(
        str(first_slice.get(key, ""))
        for key in ["instruction", "expected_output", "completion_check"]
    ).lower()
    evidence_text = reviewed_evidence_text(context)
    phases = phase_by_id(context["plan"])
    candidates = []
    for item in phase_context:
        if not isinstance(item, dict):
            continue
        phase_id = item.get("phase_id")
        depends_on = item.get("depends_on")
        if not isinstance(phase_id, str) or not isinstance(depends_on, list):
            continue
        phase = phases.get(phase_id)
        outputs = phase.get("outputs") if isinstance(phase, dict) else None
        if not isinstance(outputs, list):
            continue
        output_matches = any(
            isinstance(output, str)
            and output.lower() in first_slice_text
            and output.lower() in evidence_text
            for output in outputs
        )
        if output_matches:
            candidates.append(phase_id)
    if len(candidates) != 1:
        raise RuntimeErrorRecord("ERR_RUNTIME_ENTRY_REJECTED", "V1 first slice does not identify exactly one completed phase")
    return {candidates[0]}


def next_ready_phase(context: dict[str, Any]) -> dict[str, Any]:
    plan = context["plan"]
    phases = plan.get("phases")
    if not isinstance(phases, list):
        raise RuntimeErrorRecord("ERR_RUNTIME_ENTRY_REJECTED", "plan phases are malformed")
    completed = completed_first_slice_phase_ids(context)
    for phase in phases:
        if not isinstance(phase, dict):
            continue
        phase_id = phase.get("id")
        depends_on = phase.get("depends_on")
        if not isinstance(phase_id, str) or not isinstance(depends_on, list):
            raise RuntimeErrorRecord("ERR_RUNTIME_ENTRY_REJECTED", "plan phase dependency data is malformed")
        if phase_id not in completed and all(isinstance(item, str) and item in completed for item in depends_on):
            return phase
    raise RuntimeErrorRecord("ERR_RUNTIME_ENTRY_REJECTED", "plan has no next phase after the reviewed first slice")


def workers_for_phase(plan: dict[str, Any], phase: dict[str, Any]) -> list[dict[str, Any]]:
    worker_ids = phase.get("worker_ids")
    workers = plan.get("workers")
    if not isinstance(worker_ids, list) or not isinstance(workers, list):
        raise RuntimeErrorRecord("ERR_RUNTIME_ENTRY_REJECTED", "phase workers are malformed")
    indexed = {worker.get("id"): worker for worker in workers if isinstance(worker, dict)}
    selected = []
    for worker_id in worker_ids:
        if worker_id not in indexed:
            raise RuntimeErrorRecord("ERR_RUNTIME_ENTRY_REJECTED", f"phase references missing worker: {worker_id}")
        selected.append(indexed[worker_id])
    return selected


def next_packet(context: dict[str, Any]) -> dict[str, Any]:
    plan = context["plan"]
    phase = next_ready_phase(context)
    workers = workers_for_phase(plan, phase)
    status = context["v25_status"]
    return {
        "schema_version": SCHEMA_VERSION,
        "runtime_version": RUNTIME_VERSION,
        "packet_id": "v3-next-0001",
        "packet_index": 1,
        "source_plan_id": plan["plan_id"],
        "objective": plan["objective"],
        "phase_id": phase["id"],
        "phase_name": phase.get("name"),
        "entry_criteria": phase.get("entry_criteria", []),
        "exit_criteria": phase.get("exit_criteria", []),
        "expected_outputs": phase.get("outputs", []),
        "worker_ids": phase.get("worker_ids", []),
        "workers": [
            {
                "id": worker.get("id"),
                "role": worker.get("role"),
                "tool_permissions": worker.get("tool_permissions"),
                "prompt_contract": worker.get("prompt_contract"),
            }
            for worker in workers
        ],
        "depends_on": phase.get("depends_on", []),
        "completed_phase_ids": sorted(completed_first_slice_phase_ids(context)),
        "accepted_v25_state": status.get("status"),
        "source_hashes": {
            "v25_status_hash": canonical_hash(status),
            "plan_snapshot_hash": canonical_hash(plan),
            "v1_run_hash": canonical_hash(read_json_obj(context["v1_dir"] / "run.json", code="ERR_RUNTIME_ENTRY_REJECTED", label="V1 run.json")),
        },
        "stop_conditions": [
            "do not execute this packet in V3 entry runtime",
            "stop if V2.5 source state becomes stale",
            "stop before destructive, external, costly, production, secret, dependency, database, public API, delete, or history-rewrite actions",
        ],
    }


def render_next_prompt(packet: dict[str, Any]) -> str:
    lines = [
        "# V3 Next Packet",
        "",
        f"Packet: `{packet['packet_id']}`",
        f"Source plan: `{packet['source_plan_id']}`",
        f"Phase: `{packet['phase_id']}`",
        "",
        "## Objective",
        "",
        str(packet["objective"]),
        "",
        "## Entry Criteria",
    ]
    for item in packet.get("entry_criteria", []):
        lines.append(f"- {item}")
    lines.extend(["", "## Expected Outputs"])
    for item in packet.get("expected_outputs", []):
        lines.append(f"- {item}")
    lines.extend(["", "## Workers"])
    for worker in packet.get("workers", []):
        lines.append(f"- `{worker.get('id')}` {worker.get('role')}")
    lines.extend(["", "## Stop Conditions"])
    for item in packet.get("stop_conditions", []):
        lines.append(f"- {item}")
    return "\n".join(lines) + "\n"


def journal_entry(context: dict[str, Any], packet: dict[str, Any], prompt: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "runtime_version": RUNTIME_VERSION,
        "event_id": "0000",
        "event": "v3-entry-accepted",
        "created_at": now_utc(),
        "v1_run_path": rel(context["v1_dir"]),
        "v2_run_path": rel(context["v2_dir"]),
        "accepted_v25_state": context["v25_status"].get("status"),
        "human_approved": context["human_approved"],
        "next_packet_id": packet["packet_id"],
        "next_packet_hash": canonical_hash(packet),
        "next_prompt_hash": sha256_text(prompt),
        "source_hashes": packet["source_hashes"],
    }


def build_status(
    run_id: str,
    context: dict[str, Any],
    packet: dict[str, Any] | None,
    prompt: str | None,
    journal: dict[str, Any] | None,
    *,
    status: str,
    invalidators: list[dict[str, Any]] | None = None,
    resume_state: str = "fresh",
) -> dict[str, Any]:
    snapshots: dict[str, Any] = {}
    if packet is not None and prompt is not None and journal is not None:
        snapshots = {
            "v25_status_hash": canonical_hash(context["v25_status"]),
            "plan_snapshot_hash": canonical_hash(context["plan"]),
            "next_packet_hash": canonical_hash(packet),
            "next_prompt_hash": sha256_text(prompt),
            "journal_hash": canonical_hash(journal),
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "runtime_version": RUNTIME_VERSION,
        "run_id": run_id,
        "v1_run_path": rel(context["v1_dir"]),
        "v2_run_path": rel(context["v2_dir"]),
        "status": status,
        "resume_state": resume_state,
        "accepted_v25_state": context["v25_status"].get("status"),
        "human_approved": context["human_approved"],
        "next_packet_id": packet.get("packet_id") if packet else None,
        "next_packet_path": "next/0001.packet.json" if packet else None,
        "journal_path": "journal/0000.json" if journal else None,
        "snapshots": snapshots,
        "invalidators": invalidators or [],
        "checked_at": now_utc(),
    }


def render_resume(status: dict[str, Any]) -> str:
    lines = [
        "# V3 Runtime Resume",
        "",
        f"Run ID: `{status['run_id']}`",
        f"State: `{status['status']}`",
        f"Resume state: `{status['resume_state']}`",
        f"Accepted V2.5 state: `{status['accepted_v25_state']}`",
        "",
        "V3 entry runtime prepares the next packet candidate. It does not execute it.",
        "",
        "## Invalidators",
    ]
    invalidators = status.get("invalidators", [])
    if invalidators:
        for item in invalidators:
            lines.append(f"- `{item.get('code')}` {item.get('message')}")
    else:
        lines.append("- none")
    return "\n".join(lines) + "\n"


def write_status(out_dir: Path, status: dict[str, Any]) -> None:
    write_json(out_dir / "status.json", status, root=out_dir)
    write_text(out_dir / "resume.md", render_resume(status), root=out_dir)


def write_rejected_status(out_dir: Path, v2_dir: Path, error: RuntimeErrorRecord, *, human_approved: bool) -> dict[str, Any]:
    run_id = out_dir.name
    context = {
        "v1_dir": V1_OUT_ROOT / "unknown",
        "v2_dir": v2_dir,
        "v25_status": {"status": "untrusted"},
        "plan": {},
        "human_approved": human_approved,
    }
    try:
        raw_status = read_json_obj(v2_dir / "status.json", code="ERR_RUNTIME_ENTRY_REJECTED", label="V2.5 status.json")
        context["v1_dir"] = v1_path_from_v25_status(raw_status)
        context["v25_status"] = raw_status
        context["plan"] = load_plan_snapshot(context["v1_dir"])
    except RuntimeErrorRecord:
        pass
    ensure_v3_dir(out_dir, run_id, v2_dir)
    state = "invalid" if error.code in {"ERR_RUNTIME_ARTIFACT_MALFORMED", "ERR_RUNTIME_STALE_V25"} else "entry-rejected"
    status = build_status(run_id, context, None, None, None, status=state, invalidators=[error.to_record()])
    write_status(out_dir, status)
    return status


def validate_v3_sentinel(run_dir: Path, run_id: str, v2_dir: Path) -> None:
    sentinel = read_sentinel(run_dir)
    if sentinel is None:
        raise RuntimeErrorRecord("ERR_RUNTIME_ARTIFACT_MALFORMED", "V3 runtime directory is missing ownership sentinel", path=run_dir / SENTINEL)
    if sentinel.get("tool") != TOOL or sentinel.get("run_id") != run_id or sentinel.get("v2_run_path") != rel(v2_dir):
        raise RuntimeErrorRecord("ERR_RUNTIME_ARTIFACT_MALFORMED", "V3 runtime ownership sentinel does not match run.json", path=run_dir / SENTINEL)


def start_runtime(v2_dir: Path, *, out_dir: Path | None = None, human_approved: bool = False) -> dict[str, Any]:
    v2_dir = resolve_v2_dir(v2_dir)
    out_dir = resolve_v3_out(out_dir) if out_dir is not None else V3_OUT_ROOT / v2_dir.name
    try:
        context = trusted_v25_context(v2_dir, human_approved=human_approved)
        run_id = out_dir.name
        ensure_v3_dir(out_dir, run_id, v2_dir)
        packet = next_packet(context)
        prompt = render_next_prompt(packet)
        journal = journal_entry(context, packet, prompt)
        run = {
            "schema_version": SCHEMA_VERSION,
            "runtime_version": RUNTIME_VERSION,
            "run_id": run_id,
            "created_at": now_utc(),
            "v1_run_path": rel(context["v1_dir"]),
            "v2_run_path": rel(v2_dir),
            "human_approved": human_approved,
            "status_path": "status.json",
            "next_packet_paths": ["next/0001.packet.json"],
            "journal_paths": ["journal/0000.json"],
        }
        status = build_status(run_id, context, packet, prompt, journal, status="advanced")
    except RuntimeErrorRecord as exc:
        status = write_rejected_status(out_dir, v2_dir, exc, human_approved=human_approved)
        return {"status": status, "out_dir": out_dir}
    write_json(out_dir / "run.json", run, root=out_dir)
    write_json(out_dir / "next" / "0001.packet.json", packet, root=out_dir)
    write_text(out_dir / "next" / "0001.prompt.md", prompt, root=out_dir)
    write_json(out_dir / "journal" / "0000.json", journal, root=out_dir)
    write_status(out_dir, status)
    return {"status": status, "out_dir": out_dir, "packet": packet}


def resume_runtime(run_dir: Path) -> dict[str, Any]:
    run_dir = resolve_v3_out(run_dir)
    run = read_json_obj(run_dir / "run.json", code="ERR_RUNTIME_ARTIFACT_MALFORMED", label="run.json")
    run_id = run.get("run_id")
    if not isinstance(run_id, str) or run_id != run_dir.name:
        raise RuntimeErrorRecord("ERR_RUNTIME_ARTIFACT_MALFORMED", "run.json run_id must match runtime directory", path=run_dir / "run.json")
    v2_path = run.get("v2_run_path")
    if not isinstance(v2_path, str):
        raise RuntimeErrorRecord("ERR_RUNTIME_ARTIFACT_MALFORMED", "run.json is missing v2_run_path", path=run_dir / "run.json")
    v2_dir = resolve_v2_dir(v2_path)
    validate_v3_sentinel(run_dir, run_id, v2_dir)
    human_approved_raw = run.get("human_approved")
    if not isinstance(human_approved_raw, bool):
        error = RuntimeErrorRecord("ERR_RUNTIME_ARTIFACT_MALFORMED", "run.json human_approved must be boolean", path=run_dir / "run.json")
        status = write_rejected_status(run_dir, v2_dir, error, human_approved=False)
        return {"status": status, "out_dir": run_dir}
    human_approved = human_approved_raw
    try:
        context = trusted_v25_context(v2_dir, human_approved=human_approved)
    except RuntimeErrorRecord as exc:
        status = write_rejected_status(run_dir, v2_dir, exc, human_approved=human_approved)
        return {"status": status, "out_dir": run_dir}
    packet = read_json_obj(run_dir / "next" / "0001.packet.json", code="ERR_RUNTIME_ARTIFACT_MALFORMED", label="next packet")
    prompt_path = run_dir / "next" / "0001.prompt.md"
    if not prompt_path.is_file() or prompt_path.is_symlink():
        raise RuntimeErrorRecord("ERR_RUNTIME_ARTIFACT_MALFORMED", "next prompt is missing or symlinked", path=prompt_path)
    prompt = prompt_path.read_text()
    journal = read_json_obj(run_dir / "journal" / "0000.json", code="ERR_RUNTIME_ARTIFACT_MALFORMED", label="journal")
    previous_status = read_json_obj(run_dir / "status.json", code="ERR_RUNTIME_ARTIFACT_MALFORMED", label="status.json")
    expected_packet = next_packet(context)
    expected_prompt = render_next_prompt(expected_packet)
    expected_journal = journal_entry(context, expected_packet, expected_prompt)
    if isinstance(journal.get("created_at"), str):
        expected_journal["created_at"] = journal["created_at"]
    invalidators = []
    previous_snapshots = previous_status.get("snapshots")
    if not isinstance(previous_snapshots, dict) or previous_snapshots.get("journal_hash") != canonical_hash(journal):
        invalidators.append({"code": "ERR_RUNTIME_ARTIFACT_MALFORMED", "message": "journal does not match prior V3 status snapshot"})
    if packet != expected_packet:
        invalidators.append({"code": "ERR_RUNTIME_ARTIFACT_MALFORMED", "message": "next packet does not match current V3 inputs"})
    if prompt != expected_prompt:
        invalidators.append({"code": "ERR_RUNTIME_ARTIFACT_MALFORMED", "message": "next prompt does not match current V3 inputs"})
    if journal != expected_journal:
        invalidators.append({"code": "ERR_RUNTIME_ARTIFACT_MALFORMED", "message": "journal does not match current V3 inputs"})
    status_value = "invalid" if invalidators else "advanced"
    status = build_status(
        str(run.get("run_id", run_dir.name)),
        context,
        packet,
        prompt,
        journal,
        status=status_value,
        invalidators=invalidators,
        resume_state="invalidated" if invalidators else "resumable",
    )
    write_status(run_dir, status)
    return {"status": status, "out_dir": run_dir}


def validate_fixture_id(fixture_id: str) -> None:
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", fixture_id) or fixture_id in {".", ".."}:
        raise RuntimeErrorRecord("ERR_RUNTIME_OUTSIDE_REPO", "fixture ID must be one safe path segment", fixture_id=fixture_id)


def resolve_public_manifest(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, "ERR_RUNTIME_MANIFEST_REQUIRED_FAILED", "manifest path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    check_components_not_symlink(candidate, "ERR_RUNTIME_DIR_SYMLINK")
    resolved = candidate.resolve(strict=False)
    if resolved != TRUSTED_V3_MANIFEST.resolve(strict=False):
        raise RuntimeErrorRecord("ERR_RUNTIME_MANIFEST_REQUIRED_FAILED", "public --manifest is limited to fixtures/v3/manifest.json", path=value)
    return resolved


def validate_manifest(fixtures: list[Any], manifest_path: Path) -> None:
    seen = set()
    for fixture in fixtures:
        if not isinstance(fixture, dict):
            raise RuntimeErrorRecord("ERR_RUNTIME_MANIFEST_REQUIRED_FAILED", "fixture must be an object", path=manifest_path)
        fixture_id = fixture.get("id")
        if not isinstance(fixture_id, str):
            raise RuntimeErrorRecord("ERR_RUNTIME_MANIFEST_REQUIRED_FAILED", "fixture id must be a string", path=manifest_path)
        validate_fixture_id(fixture_id)
        if fixture_id in seen:
            raise RuntimeErrorRecord("ERR_RUNTIME_MANIFEST_REQUIRED_FAILED", "duplicate fixture ID", fixture_id=fixture_id)
        seen.add(fixture_id)
        fixture_type = fixture.get("type")
        if fixture_type not in ALLOWED_FIXTURE_TYPES:
            raise RuntimeErrorRecord("ERR_RUNTIME_MANIFEST_REQUIRED_FAILED", "unsupported fixture type", fixture_id=fixture_id)
        if "required" in fixture and not isinstance(fixture["required"], bool):
            raise RuntimeErrorRecord("ERR_RUNTIME_MANIFEST_REQUIRED_FAILED", "fixture required must be boolean", fixture_id=fixture_id)


def reset_owned_v2(path: Path) -> None:
    if path.exists():
        sentinel = path / ".execute_packet-owned.json"
        if not sentinel.is_file():
            raise RuntimeErrorRecord("ERR_RUNTIME_ARTIFACT_MALFORMED", "existing V2 fixture output is not execute_packet-owned", path=path)
        shutil.rmtree(path)


def reset_owned_v3(path: Path) -> None:
    if path.exists():
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("tool") != TOOL:
            raise RuntimeErrorRecord("ERR_RUNTIME_ARTIFACT_MALFORMED", "existing V3 fixture output is not runtime-owned", path=path)
        shutil.rmtree(path)


def fixture_worktree(suite_id: str, fixture_id: str, suffix: str = "run-v3-verified") -> str:
    head = git_text(["rev-parse", "--short=12", "HEAD"], ROOT).strip()
    return f"v3-{suite_id}-{head}-{fixture_id}-{suffix}"


def clear_fixture_inventory(worktree_name: str) -> None:
    path = worktree_path(worktree_name) / "inventory.json"
    if path.exists():
        if path.is_symlink() or not path.is_file():
            raise RuntimeErrorRecord("ERR_RUNTIME_MANIFEST_REQUIRED_FAILED", "fixture inventory artifact is unsafe", path=path)
        path.unlink()


def make_latest_review_needs_human(v2_run: Path) -> None:
    reviews_dir = v2_run / "reviews"
    review_dirs = sorted(path for path in reviews_dir.iterdir() if path.is_dir())
    if not review_dirs:
        raise RuntimeErrorRecord("ERR_RUNTIME_MANIFEST_REQUIRED_FAILED", "needs-human fixture has no review")
    review_dir = review_dirs[-1]
    review_path = review_dir / "review.json"
    hashes_path = review_dir / "hashes.json"
    review = json.loads(review_path.read_text())
    review["verdict"] = "needs_human_review"
    review["findings"] = [
        {
            "finding_id": "finding-0000",
            "severity": "warning",
            "file_or_artifact": f"attempts/{review.get('source_attempt_id')}/attempt.json",
            "line_or_pointer": "/status",
            "claim": "A human gate is required even though automatic evidence passed.",
            "evidence": "fixture forces a coherent needs-human review over verified automatic evidence",
            "falsifier": "A later human-override contract would define a distinct accepted state.",
            "suggested_fix": "Keep V3 stopped until that contract exists.",
            "repair_allowed": False,
        }
    ]
    review["summary"] = "Deterministic fixture marks verified evidence as needing human judgment."
    markdown = "\n".join(
        [
            "# V2.5 Review",
            "",
            f"Review ID: `{review['review_id']}`",
            f"Source attempt: `{review['source_attempt_id']}`",
            "Verdict: `needs_human_review`",
            "",
            review["summary"],
            "",
            "## Findings",
            "- `finding-0000` warning: A human gate is required even though automatic evidence passed.",
            "",
        ]
    )
    hashes = json.loads(hashes_path.read_text())
    hashes["review_hash"] = canonical_hash(review)
    hashes["markdown_hash"] = sha256_text(markdown)
    hashes["source_hashes_hash"] = canonical_hash(review["source_hashes"])
    write_json(review_path, review, root=v2_run)
    write_text(review_dir / str(review["markdown_path"]), markdown, root=v2_run)
    write_json(hashes_path, hashes, root=v2_run)
    contracts = read_json(v2_run / "review-contracts.json")
    entries = contracts.get("reviews")
    if not isinstance(entries, list):
        raise RuntimeErrorRecord("ERR_RUNTIME_MANIFEST_REQUIRED_FAILED", "review contract ledger is malformed")
    replacement = review_contract(review, hashes)
    for index, entry in enumerate(entries):
        if isinstance(entry, dict) and entry.get("review_id") == review["review_id"]:
            entries[index] = replacement
            break
    else:
        append_review_contract(v2_run, review, hashes)
        return
    write_json(v2_run / "review-contracts.json", contracts, root=v2_run)


def prepare_v25_fixture(suite_id: str, fixture_id: str, fixture_type: str) -> Path:
    ready_plan = ROOT / "fixtures" / "v1" / "plans" / "ready-readonly.workflow.plan.json"
    if fixture_type == "reject-unmatched-first-slice":
        ready_plan = ROOT / "fixtures" / "v3" / "plans" / "unmatched-first-slice.workflow.plan.json"
    run_id = f"v3-{suite_id}-{fixture_id}"
    v1_run = V1_OUT_ROOT / run_id
    v2_run = V2_OUT_ROOT / run_id
    reset_owned_v2(v2_run)
    compile_plan(ready_plan, v1_run, run_id=run_id)
    if fixture_type in {
        "approved-advance",
        "resume-clean",
        "resume-stale-v25-status",
        "resume-tampered-next-packet",
        "resume-tampered-journal",
        "resume-non-owned-dir",
        "resume-human-approved-string",
        "reject-unmatched-first-slice",
    }:
        worktree_name = fixture_worktree(suite_id, fixture_id)
        clear_fixture_inventory(worktree_name)
        execute_local_shell(
            v1_run,
            out_dir=v2_run,
            worktree=worktree_name,
            local_shell={"argv": ["python", "-c", "from pathlib import Path; Path('inventory.json').write_text('{}')"], "expected_exit_code": 0},
            verification_commands=[
                {
                    "id": "verify-output",
                    "argv": ["python", "-c", "from pathlib import Path; raise SystemExit(0 if Path('inventory.json').is_file() else 1)"],
                    "expected_exit_code": 0,
                }
            ],
        )
        review_execution(v1_run, out_dir=v2_run)
    elif fixture_type == "reject-review-approved-manual":
        execute_local_shell(
            v1_run,
            out_dir=v2_run,
            worktree=fixture_worktree(suite_id, fixture_id),
            local_shell={"argv": ["python", "-c", "print('inventory.json')"], "expected_exit_code": 0},
        )
        review_execution(v1_run, out_dir=v2_run)
    elif fixture_type == "reject-changes-requested":
        execute_local_shell(
            v1_run,
            out_dir=v2_run,
            worktree=fixture_worktree(suite_id, fixture_id),
            local_shell={"argv": ["python", "-c", "import sys; sys.exit(2)"], "expected_exit_code": 0},
        )
        review_execution(v1_run, out_dir=v2_run)
    elif fixture_type == "reject-repair-prepared":
        execute_local_shell(
            v1_run,
            out_dir=v2_run,
            worktree=fixture_worktree(suite_id, fixture_id),
            local_shell={"argv": ["python", "-c", "import sys; sys.exit(2)"], "expected_exit_code": 0},
        )
        review_execution(v1_run, out_dir=v2_run)
        prepare_repair(v1_run, out_dir=v2_run)
    elif fixture_type in {"needs-human-requires-approval", "needs-human-approved"}:
        worktree_name = fixture_worktree(suite_id, fixture_id)
        clear_fixture_inventory(worktree_name)
        execute_local_shell(
            v1_run,
            out_dir=v2_run,
            worktree=worktree_name,
            local_shell={"argv": ["python", "-c", "from pathlib import Path; Path('inventory.json').write_text('{}')"], "expected_exit_code": 0},
            verification_commands=[
                {
                    "id": "verify-output",
                    "argv": ["python", "-c", "from pathlib import Path; raise SystemExit(0 if Path('inventory.json').is_file() else 1)"],
                    "expected_exit_code": 0,
                }
            ],
        )
        review_execution(v1_run, out_dir=v2_run)
        make_latest_review_needs_human(v2_run)
    else:
        raise RuntimeErrorRecord("ERR_RUNTIME_MANIFEST_REQUIRED_FAILED", "unsupported fixture setup", fixture_id=fixture_id)
    return v2_run


def run_fixture(suite_id: str, fixture: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    fixture_id = fixture["id"]
    fixture_type = fixture["type"]
    fixture_out = out_dir / fixture_id
    reset_owned_v3(fixture_out)
    v2_run = prepare_v25_fixture(suite_id, fixture_id, fixture_type)
    human_approved = fixture_type in {"needs-human-approved", "resume-human-approved-string"}
    if fixture_type == "resume-clean":
        start_runtime(v2_run, out_dir=fixture_out)
        result = resume_runtime(fixture_out)
    elif fixture_type == "resume-stale-v25-status":
        start_runtime(v2_run, out_dir=fixture_out)
        v1_run = V1_OUT_ROOT / v2_run.name
        execute_local_shell(
            v1_run,
            out_dir=v2_run,
            worktree=fixture_worktree(suite_id, fixture_id, "stale"),
            local_shell={"argv": ["python", "-c", "import sys; sys.exit(2)"], "expected_exit_code": 0},
        )
        result = resume_runtime(fixture_out)
    elif fixture_type == "resume-tampered-next-packet":
        start_runtime(v2_run, out_dir=fixture_out)
        packet_path = fixture_out / "next" / "0001.packet.json"
        packet = json.loads(packet_path.read_text())
        packet["phase_id"] = "tampered"
        write_json(packet_path, packet, root=fixture_out)
        result = resume_runtime(fixture_out)
    elif fixture_type == "resume-tampered-journal":
        start_runtime(v2_run, out_dir=fixture_out)
        journal_path = fixture_out / "journal" / "0000.json"
        journal = json.loads(journal_path.read_text())
        journal["event"] = "tampered"
        write_json(journal_path, journal, root=fixture_out)
        result = resume_runtime(fixture_out)
    elif fixture_type == "resume-human-approved-string":
        start_runtime(v2_run, out_dir=fixture_out)
        run_path = fixture_out / "run.json"
        run = json.loads(run_path.read_text())
        run["human_approved"] = "false"
        write_json(run_path, run, root=fixture_out)
        result = resume_runtime(fixture_out)
    elif fixture_type == "resume-non-owned-dir":
        source_out = out_dir / f"{fixture_id}-owned-source"
        reset_owned_v3(source_out)
        start_runtime(v2_run, out_dir=source_out)
        fixture_out.mkdir(parents=True)
        shutil.copytree(source_out / "next", fixture_out / "next")
        shutil.copytree(source_out / "journal", fixture_out / "journal")
        for filename in ["run.json", "status.json", "resume.md"]:
            shutil.copy2(source_out / filename, fixture_out / filename)
        try:
            result = resume_runtime(fixture_out)
        except RuntimeErrorRecord as exc:
            return {"status": "invalid", "invalidators": [exc.to_record()]}
    else:
        result = start_runtime(v2_run, out_dir=fixture_out, human_approved=human_approved)
    return result["status"]


def run_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    try:
        manifest = read_json(manifest_path)
    except CompileError as exc:
        raise RuntimeErrorRecord("ERR_RUNTIME_MANIFEST_REQUIRED_FAILED", exc.message, path=exc.path) from exc
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise RuntimeErrorRecord("ERR_RUNTIME_MANIFEST_REQUIRED_FAILED", "manifest schema_version is missing or unsupported", path=manifest_path)
    fixtures = manifest.get("fixtures")
    if not isinstance(fixtures, list):
        raise RuntimeErrorRecord("ERR_RUNTIME_MANIFEST_REQUIRED_FAILED", "manifest fixtures must be a list", path=manifest_path)
    validate_manifest(fixtures, manifest_path)
    suite_id = out_dir.name
    prepare_manifest_suite(out_dir, suite_id)
    records = []
    passed = failed = skipped = required_passed = required_total = 0
    for fixture in fixtures:
        fixture_id = fixture["id"]
        required = fixture.get("required", True)
        if required:
            required_total += 1
        record: dict[str, Any] = {"id": fixture_id, "required": required}
        try:
            status = run_fixture(suite_id, fixture, out_dir)
            actual_status = status["status"]
            expected_status = fixture.get("expected_status")
            expected_error = fixture.get("expected_error")
            actual_codes = [item.get("code") for item in status.get("invalidators", [])]
            if actual_status != expected_status:
                raise RuntimeErrorRecord("ERR_RUNTIME_MANIFEST_REQUIRED_FAILED", f"expected status {expected_status}, got {actual_status}", fixture_id=fixture_id)
            if expected_error and expected_error not in actual_codes:
                raise RuntimeErrorRecord("ERR_RUNTIME_MANIFEST_REQUIRED_FAILED", f"expected error {expected_error}, got {actual_codes}", fixture_id=fixture_id)
            expected_phase_id = fixture.get("expected_phase_id")
            actual_phase_id = None
            packet_path = out_dir / fixture_id / "next" / "0001.packet.json"
            if expected_phase_id is not None:
                packet = read_json_obj(packet_path, code="ERR_RUNTIME_MANIFEST_REQUIRED_FAILED", label="next packet")
                actual_phase_id = packet.get("phase_id")
                if actual_phase_id != expected_phase_id:
                    raise RuntimeErrorRecord("ERR_RUNTIME_MANIFEST_REQUIRED_FAILED", f"expected phase {expected_phase_id}, got {actual_phase_id}", fixture_id=fixture_id)
            record.update({"status": "pass", "actual_status": actual_status, "invalidator_codes": actual_codes})
            if actual_phase_id is not None:
                record["actual_phase_id"] = actual_phase_id
            passed += 1
            if required:
                required_passed += 1
        except Exception as exc:  # noqa: BLE001 - manifest records structured failures.
            failed += 1
            record.update({"status": "fail", "error": str(exc)})
        records.append(record)
    decision = "keep" if skipped == 0 and required_passed == required_total else "kill"
    summary = {
        "suite_id": suite_id,
        "fixture_count": len(fixtures),
        "required_fixture_count": required_total,
        "required_passed": required_passed,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "decision": decision,
        "fixtures": records,
    }
    write_json(out_dir / "summary.json", summary, root=out_dir)
    return summary


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeErrorRecord("ERR_RUNTIME_SELF_TEST_FAILED", message)


def self_test() -> None:
    suite = "self-test"
    out_root = V3_OUT_ROOT
    for path in sorted(out_root.glob("runtime-self-test-*")):
        reset_owned_v3(path)
    approved_v2 = prepare_v25_fixture(suite, "runtime-self-test-approved", "approved-advance")
    approved_out = V3_OUT_ROOT / "runtime-self-test-approved"
    started = start_runtime(approved_v2, out_dir=approved_out)
    require(started["status"]["status"] == "advanced", "approved V2.5 state should advance")
    resumed = resume_runtime(approved_out)
    require(resumed["status"]["resume_state"] == "resumable", "approved V3 resume should be clean")

    changes_v2 = prepare_v25_fixture(suite, "runtime-self-test-changes", "reject-changes-requested")
    changes = start_runtime(changes_v2, out_dir=V3_OUT_ROOT / "runtime-self-test-changes")
    require(changes["status"]["status"] == "entry-rejected", "changes-requested should reject entry")
    require(changes["status"]["invalidators"][0]["code"] == "ERR_RUNTIME_ENTRY_REJECTED", "changes-requested wrong invalidator")

    human_v2 = prepare_v25_fixture(suite, "runtime-self-test-human", "needs-human-approved")
    human = start_runtime(human_v2, out_dir=V3_OUT_ROOT / "runtime-self-test-human", human_approved=True)
    require(human["status"]["status"] == "entry-rejected", "human-approved needs-human should not advance")

    tampered_out = V3_OUT_ROOT / "runtime-self-test-tampered"
    start_runtime(approved_v2, out_dir=tampered_out)
    packet_path = tampered_out / "next" / "0001.packet.json"
    packet = json.loads(packet_path.read_text())
    packet["phase_id"] = "tampered"
    write_json(packet_path, packet, root=tampered_out)
    tampered = resume_runtime(tampered_out)
    require(tampered["status"]["status"] == "invalid", "tampered next packet should invalidate resume")
    print("run_workflow self-test: pass")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", help="trusted V2.5 evidence directory under out/v2")
    parser.add_argument("--resume", help="V3 runtime directory under out/v3")
    parser.add_argument("--manifest", help="V3 fixture manifest")
    parser.add_argument("--out", help="V3 output directory")
    parser.add_argument("--human-approved", action="store_true", help="record explicit human approval; V3 still rejects needs-human in this slice")
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if args.self_test:
            self_test()
            return 0
        if args.manifest:
            if not args.out:
                raise RuntimeErrorRecord("ERR_RUNTIME_MANIFEST_REQUIRED_FAILED", "--manifest requires --out")
            summary = run_manifest(resolve_public_manifest(args.manifest), resolve_v3_out(args.out))
            print(canonical_json_text({key: value for key, value in summary.items() if key != "fixtures"}))
            return 0 if summary["decision"] == "keep" else 1
        if args.start:
            result = start_runtime(Path(args.start), out_dir=Path(args.out) if args.out else None, human_approved=args.human_approved)
            print(canonical_json_text(result["status"]))
            return 0 if result["status"]["status"] == "advanced" else 1
        if args.resume:
            result = resume_runtime(Path(args.resume))
            print(canonical_json_text(result["status"]))
            return 0 if result["status"]["status"] == "advanced" and result["status"]["resume_state"] == "resumable" else 1
        raise RuntimeErrorRecord("ERR_RUNTIME_MANIFEST_REQUIRED_FAILED", "expected --self-test, --manifest, --start, or --resume")
    except RuntimeErrorRecord as exc:
        print(canonical_json_text(exc.to_record()), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
