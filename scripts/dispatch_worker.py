#!/usr/bin/env python3
"""Prepare a deterministic dispatch bundle for one trusted V4 packet."""

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

from compile_workflow import canonical_hash, canonical_json_text, sha256_text, write_text_atomic  # noqa: E402
from orchestrate_workflow import self_test as orchestrator_self_test  # noqa: E402


TOOL = "dispatch_worker.py"
SCHEMA_VERSION = "1.0"
DISPATCH_VERSION = "0.1.0"
V4_OUT_ROOT = ROOT / "out" / "v4"
V45_OUT_ROOT = ROOT / "out" / "v4.5"
SENTINEL = ".dispatch_worker-owned.json"
V4_SENTINEL = ".orchestrate_workflow-owned.json"


class DispatchError(ValueError):
    """Structured V4.5 dispatch failure."""

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
        raise DispatchError(code, message, path=path)


def check_components_not_symlink(path: Path, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise DispatchError(code, "path contains a symlink", path=current)


def resolve_under_out(value: str | Path, root: Path, *, label: str) -> Path:
    raw = Path(value)
    reject_traversal(raw, "ERR_DISPATCH_OUTSIDE_REPO", f"{label} path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    out_root = root.resolve(strict=False)
    forbidden = {ROOT.resolve(), (ROOT / "out").resolve(strict=False), out_root}
    if resolved in forbidden:
        raise DispatchError("ERR_DISPATCH_OUTSIDE_REPO", f"{label} path must name a run artifact", path=value)
    try:
        resolved.relative_to(out_root)
    except ValueError as exc:
        raise DispatchError("ERR_DISPATCH_OUTSIDE_REPO", f"{label} path must resolve under {out_root}", path=value) from exc
    check_components_not_symlink(candidate, "ERR_DISPATCH_DIR_SYMLINK")
    return resolved


def resolve_v4_packet(value: str | Path) -> Path:
    path = resolve_under_out(value, V4_OUT_ROOT, label="V4 packet")
    if path.name.endswith(".packet.json"):
        return path
    raise DispatchError("ERR_DISPATCH_UNTRUSTED_V4", "V4 packet path must end with .packet.json", path=path)


def resolve_v45_out(value: str | Path) -> Path:
    return resolve_under_out(value, V45_OUT_ROOT, label="V4.5 output")


def ensure_contained(root: Path, path: Path) -> None:
    target = path if path.is_absolute() else root / path
    reject_traversal(path, "ERR_DISPATCH_OUTSIDE_REPO", "artifact path escapes owned directory")
    try:
        target.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError as exc:
        raise DispatchError("ERR_DISPATCH_OUTSIDE_REPO", "artifact path escapes owned directory", path=target) from exc


def ensure_artifact_parent(root: Path, path: Path) -> None:
    ensure_contained(root, path)
    current = root.resolve(strict=False)
    for part in path.resolve(strict=False).relative_to(current).parent.parts:
        current = current / part
        if current.exists():
            if current.is_symlink():
                raise DispatchError("ERR_DISPATCH_DIR_SYMLINK", "artifact parent is symlinked", path=current)
            if not current.is_dir():
                raise DispatchError("ERR_DISPATCH_OUTSIDE_REPO", "artifact parent is not a directory", path=current)
        else:
            current.mkdir()


def ensure_leaf_not_symlink(path: Path) -> None:
    if path.exists():
        if path.is_symlink():
            raise DispatchError("ERR_DISPATCH_LEAF_SYMLINK", "refusing to overwrite symlinked file", path=path)
        if not path.is_file():
            raise DispatchError("ERR_DISPATCH_OUTSIDE_REPO", "refusing to overwrite non-file leaf", path=path)


def write_text(path: Path, text: str, *, root: Path) -> None:
    ensure_artifact_parent(root, path)
    ensure_leaf_not_symlink(path)
    write_text_atomic(path, text, root=root)


def write_json(path: Path, data: Any, *, root: Path) -> None:
    write_text(path, canonical_json_text(data), root=root)


def read_json_obj(path: Path, *, code: str, label: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise DispatchError(code, f"{label} is missing or symlinked", path=path)
    try:
        data = json.loads(path.read_text())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DispatchError(code, f"{label} is malformed: {exc}", path=path) from exc
    if not isinstance(data, dict):
        raise DispatchError(code, f"{label} root must be an object", path=path)
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


def sentinel_payload(run_id: str, source_packet: Path) -> dict[str, Any]:
    v4_dir = source_packet.parents[1]
    return {
        "tool": TOOL,
        "schema_version": SCHEMA_VERSION,
        "dispatch_version": DISPATCH_VERSION,
        "run_id": run_id,
        "source_v4_run_path": rel(v4_dir),
        "source_packet_path": rel(source_packet),
        "created_at": now_utc(),
    }


def ensure_dispatch_dir(path: Path, run_id: str, source_packet: Path) -> None:
    path = resolve_v45_out(path)
    if path.exists():
        if path.is_symlink():
            raise DispatchError("ERR_DISPATCH_DIR_SYMLINK", "dispatch output directory is a symlink", path=path)
        if not path.is_dir():
            raise DispatchError("ERR_DISPATCH_OUTSIDE_REPO", "dispatch output exists and is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None:
            raise DispatchError("ERR_DISPATCH_ARTIFACT_MALFORMED", "existing dispatch output is not owned", path=path)
        expected = sentinel_payload(run_id, source_packet)
        expected["created_at"] = sentinel.get("created_at")
        if sentinel != expected:
            raise DispatchError("ERR_DISPATCH_ARTIFACT_MALFORMED", "dispatch output sentinel does not match this packet", path=path)
    path.mkdir(parents=True, exist_ok=True)
    if read_sentinel(path) is None:
        write_json(path / SENTINEL, sentinel_payload(run_id, source_packet), root=path)


def prompt_path_for_packet(packet_path: Path) -> Path:
    name = packet_path.name
    return packet_path.with_name(name.removesuffix(".packet.json") + ".prompt.md")


def trusted_v4_context(packet_path: Path) -> dict[str, Any]:
    packet_path = resolve_v4_packet(packet_path)
    v4_dir = packet_path.parents[1]
    if read_sentinel(v4_dir, V4_SENTINEL) is None:
        raise DispatchError("ERR_DISPATCH_UNTRUSTED_V4", "V4 run is missing ownership sentinel", path=v4_dir / V4_SENTINEL)
    run = read_json_obj(v4_dir / "run.json", code="ERR_DISPATCH_UNTRUSTED_V4", label="V4 run.json")
    status = read_json_obj(v4_dir / "status.json", code="ERR_DISPATCH_UNTRUSTED_V4", label="V4 status.json")
    schedule = read_json_obj(v4_dir / "schedule.json", code="ERR_DISPATCH_UNTRUSTED_V4", label="V4 schedule.json")
    packet = read_json_obj(packet_path, code="ERR_DISPATCH_UNTRUSTED_V4", label="V4 packet")
    prompt_path = prompt_path_for_packet(packet_path)
    if not prompt_path.is_file() or prompt_path.is_symlink():
        raise DispatchError("ERR_DISPATCH_UNTRUSTED_V4", "V4 prompt is missing or symlinked", path=prompt_path)
    prompt = prompt_path.read_text()
    run_id = run.get("run_id")
    if not isinstance(run_id, str) or run_id != v4_dir.name:
        raise DispatchError("ERR_DISPATCH_UNTRUSTED_V4", "V4 run_id must match directory", path=v4_dir / "run.json")
    sentinel = read_sentinel(v4_dir, V4_SENTINEL)
    if sentinel is None or sentinel.get("run_id") != run_id:
        raise DispatchError("ERR_DISPATCH_UNTRUSTED_V4", "V4 ownership sentinel does not match run", path=v4_dir / V4_SENTINEL)
    if status.get("status") != "scheduled":
        raise DispatchError("ERR_DISPATCH_ENTRY_REJECTED", "dispatch requires scheduled V4 status", path=v4_dir / "status.json")
    packet_id = packet.get("packet_id")
    if not isinstance(packet_id, str) or not packet_id:
        raise DispatchError("ERR_DISPATCH_UNTRUSTED_V4", "V4 packet is missing packet_id", path=packet_path)
    snapshots = status.get("snapshots")
    if not isinstance(snapshots, dict):
        raise DispatchError("ERR_DISPATCH_UNTRUSTED_V4", "V4 status snapshots are malformed", path=v4_dir / "status.json")
    packet_hashes = snapshots.get("packet_hashes")
    prompt_hashes = snapshots.get("prompt_hashes")
    if not isinstance(packet_hashes, dict) or not isinstance(prompt_hashes, dict):
        raise DispatchError("ERR_DISPATCH_UNTRUSTED_V4", "V4 status packet hashes are malformed", path=v4_dir / "status.json")
    if packet_hashes.get(packet_id) != canonical_hash(packet):
        raise DispatchError("ERR_DISPATCH_STALE_V4", "V4 packet hash does not match status", path=packet_path)
    if prompt_hashes.get(packet_id) != sha256_text(prompt):
        raise DispatchError("ERR_DISPATCH_STALE_V4", "V4 prompt hash does not match status", path=prompt_path)
    selected = schedule.get("selected_phase_ids")
    phase_id = packet.get("phase_id")
    if not isinstance(selected, list) or phase_id not in selected:
        raise DispatchError("ERR_DISPATCH_UNTRUSTED_V4", "V4 packet phase is not selected in schedule", path=v4_dir / "schedule.json")
    return {
        "v4_dir": v4_dir,
        "packet_path": packet_path,
        "prompt_path": prompt_path,
        "run": run,
        "status": status,
        "schedule": schedule,
        "packet": packet,
        "prompt": prompt,
    }


def build_dispatch(context: dict[str, Any], *, created_at: str | None = None) -> dict[str, Any]:
    packet = context["packet"]
    return {
        "schema_version": SCHEMA_VERSION,
        "dispatch_version": DISPATCH_VERSION,
        "dispatch_id": "0000",
        "created_at": created_at or now_utc(),
        "status": "prepared",
        "mode": "emit-only",
        "backend": "manual-or-future-v2-adapter",
        "source_v4_run_path": rel(context["v4_dir"]),
        "source_packet_path": rel(context["packet_path"]),
        "source_prompt_path": rel(context["prompt_path"]),
        "packet_id": packet.get("packet_id"),
        "phase_id": packet.get("phase_id"),
        "worker_ids": packet.get("worker_ids", []),
        "expected_outputs": packet.get("expected_outputs", []),
        "stop_conditions": [
            "do not execute this dispatch bundle directly",
            "route any worker result through reviewed evidence before runtime advancement",
            "stop before destructive, external, costly, production, secret, dependency, database, public API, delete, or history-rewrite actions",
        ],
        "artifacts": {
            "packet_copy_path": "packet.json",
            "prompt_copy_path": "prompt.md",
            "hashes_path": "hashes.json",
        },
    }


def build_hashes(context: dict[str, Any], dispatch: dict[str, Any]) -> dict[str, str]:
    source_status = dict(context["status"])
    source_status.pop("checked_at", None)
    return {
        "source_v4_status_hash": canonical_hash(source_status),
        "source_v4_schedule_hash": canonical_hash(context["schedule"]),
        "source_packet_hash": canonical_hash(context["packet"]),
        "source_prompt_hash": sha256_text(context["prompt"]),
        "dispatch_hash": canonical_hash(dispatch),
    }


def build_status(
    run_id: str,
    *,
    dispatch: dict[str, Any] | None,
    hashes: dict[str, str] | None,
    status: str,
    resume_state: str,
    invalidators: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "dispatch_version": DISPATCH_VERSION,
        "run_id": run_id,
        "status": status,
        "resume_state": resume_state,
        "dispatch_path": "dispatch.json" if dispatch else None,
        "packet_id": dispatch.get("packet_id") if dispatch else None,
        "phase_id": dispatch.get("phase_id") if dispatch else None,
        "worker_ids": dispatch.get("worker_ids", []) if dispatch else [],
        "invalidators": invalidators or [],
        "snapshots": hashes or {},
        "checked_at": now_utc(),
    }


def render_resume(status: dict[str, Any]) -> str:
    lines = [
        "# V4.5 Dispatch Resume",
        "",
        f"Run: `{status['run_id']}`",
        f"Status: `{status['status']}`",
        f"Resume state: `{status['resume_state']}`",
        "",
        f"Packet: `{status.get('packet_id')}`",
        f"Phase: `{status.get('phase_id')}`",
    ]
    if status.get("invalidators"):
        lines.extend(["", "## Invalidators"])
        for item in status["invalidators"]:
            lines.append(f"- `{item.get('code')}` {item.get('message')}")
    return "\n".join(lines) + "\n"


def write_status(out_dir: Path, status: dict[str, Any]) -> None:
    write_json(out_dir / "status.json", status, root=out_dir)
    write_text(out_dir / "resume.md", render_resume(status), root=out_dir)


def write_error_status(out_dir: Path, run_id: str, packet_path: Path, error: DispatchError) -> dict[str, Any]:
    ensure_dispatch_dir(out_dir, run_id, packet_path)
    status = build_status(run_id, dispatch=None, hashes=None, status="blocked", resume_state="invalid", invalidators=[error.to_record()])
    write_status(out_dir, status)
    return status


def start_dispatch(packet_path: Path, *, out_dir: Path | None = None) -> dict[str, Any]:
    packet_path = resolve_v4_packet(packet_path)
    out_dir = resolve_v45_out(out_dir) if out_dir is not None else V45_OUT_ROOT / packet_path.parents[1].name
    run_id = out_dir.name
    try:
        context = trusted_v4_context(packet_path)
        ensure_dispatch_dir(out_dir, run_id, packet_path)
        dispatch = build_dispatch(context)
        hashes = build_hashes(context, dispatch)
        status = build_status(run_id, dispatch=dispatch, hashes=hashes, status="prepared", resume_state="fresh")
    except DispatchError as exc:
        status = write_error_status(out_dir, run_id, packet_path, exc)
        return {"status": status, "out_dir": out_dir}
    write_json(out_dir / "dispatch.json", dispatch, root=out_dir)
    write_json(out_dir / "packet.json", context["packet"], root=out_dir)
    write_text(out_dir / "prompt.md", context["prompt"], root=out_dir)
    write_json(out_dir / "hashes.json", hashes, root=out_dir)
    write_status(out_dir, status)
    return {"status": status, "out_dir": out_dir, "dispatch": dispatch}


def validate_dispatch_sentinel(run_dir: Path, run_id: str, packet_path: Path) -> None:
    sentinel = read_sentinel(run_dir)
    if sentinel is None:
        raise DispatchError("ERR_DISPATCH_ARTIFACT_MALFORMED", "dispatch output is missing ownership sentinel", path=run_dir / SENTINEL)
    expected = sentinel_payload(run_id, packet_path)
    expected["created_at"] = sentinel.get("created_at")
    if sentinel != expected:
        raise DispatchError("ERR_DISPATCH_ARTIFACT_MALFORMED", "dispatch ownership sentinel does not match run.json", path=run_dir / SENTINEL)


def resume_dispatch(run_dir: Path) -> dict[str, Any]:
    run_dir = resolve_v45_out(run_dir)
    dispatch = read_json_obj(run_dir / "dispatch.json", code="ERR_DISPATCH_ARTIFACT_MALFORMED", label="dispatch.json")
    run_id = run_dir.name
    source_packet_path = dispatch.get("source_packet_path")
    if not isinstance(source_packet_path, str):
        raise DispatchError("ERR_DISPATCH_ARTIFACT_MALFORMED", "dispatch is missing source_packet_path", path=run_dir / "dispatch.json")
    packet_path = resolve_v4_packet(source_packet_path)
    validate_dispatch_sentinel(run_dir, run_id, packet_path)
    context = trusted_v4_context(packet_path)
    expected_dispatch = build_dispatch(context, created_at=str(dispatch.get("created_at")))
    expected_hashes = build_hashes(context, expected_dispatch)
    hashes = read_json_obj(run_dir / "hashes.json", code="ERR_DISPATCH_ARTIFACT_MALFORMED", label="hashes.json")
    packet_copy = read_json_obj(run_dir / "packet.json", code="ERR_DISPATCH_ARTIFACT_MALFORMED", label="packet copy")
    prompt_path = run_dir / "prompt.md"
    if not prompt_path.is_file() or prompt_path.is_symlink():
        raise DispatchError("ERR_DISPATCH_ARTIFACT_MALFORMED", "prompt copy is missing or symlinked", path=prompt_path)
    invalidators: list[dict[str, Any]] = []
    if dispatch != expected_dispatch:
        invalidators.append({"code": "ERR_DISPATCH_ARTIFACT_MALFORMED", "message": "dispatch does not match current source packet"})
    if hashes != expected_hashes:
        invalidators.append({"code": "ERR_DISPATCH_ARTIFACT_MALFORMED", "message": "hashes do not match current source packet"})
    if packet_copy != context["packet"]:
        invalidators.append({"code": "ERR_DISPATCH_ARTIFACT_MALFORMED", "message": "packet copy does not match current source packet"})
    if prompt_path.read_text() != context["prompt"]:
        invalidators.append({"code": "ERR_DISPATCH_ARTIFACT_MALFORMED", "message": "prompt copy does not match current source prompt"})
    status = build_status(
        run_id,
        dispatch=expected_dispatch,
        hashes=expected_hashes,
        status="prepared" if not invalidators else "invalid",
        resume_state="resumable" if not invalidators else "invalidated",
        invalidators=invalidators,
    )
    write_status(run_dir, status)
    return {"status": status, "out_dir": run_dir}


def reset_owned(path: Path) -> None:
    if not path.exists():
        return
    sentinel = read_sentinel(path)
    if sentinel is None or sentinel.get("tool") != TOOL:
        raise DispatchError("ERR_DISPATCH_ARTIFACT_MALFORMED", "existing self-test output is not dispatch-owned", path=path)
    shutil.rmtree(path)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise DispatchError("ERR_DISPATCH_SELF_TEST_FAILED", message)


def self_test() -> None:
    orchestrator_self_test()
    packet = V4_OUT_ROOT / "orchestrate-self-test-linear" / "packets" / "0001.verify.packet.json"
    out_dir = V45_OUT_ROOT / "dispatch-self-test-linear"
    reset_owned(out_dir)
    started = start_dispatch(packet, out_dir=out_dir)
    require(started["status"]["status"] == "prepared", "trusted V4 packet should prepare dispatch")
    resumed = resume_dispatch(out_dir)
    require(resumed["status"]["resume_state"] == "resumable", "clean dispatch should resume")
    packet_copy = read_json_obj(out_dir / "packet.json", code="ERR_DISPATCH_ARTIFACT_MALFORMED", label="packet")
    packet_copy["phase_id"] = "tampered"
    write_json(out_dir / "packet.json", packet_copy, root=out_dir)
    tampered = resume_dispatch(out_dir)
    require(tampered["status"]["status"] == "invalid", "tampered packet copy should invalidate")
    require(tampered["status"]["invalidators"][0]["code"] == "ERR_DISPATCH_ARTIFACT_MALFORMED", "tamper invalidator mismatch")
    print("dispatch_worker self-test: pass")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", help="trusted V4 packet path under out/v4")
    parser.add_argument("--resume", help="V4.5 dispatch output directory under out/v4.5")
    parser.add_argument("--out", help="V4.5 output directory")
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if args.self_test:
            self_test()
            return 0
        if args.packet:
            result = start_dispatch(Path(args.packet), out_dir=Path(args.out) if args.out else None)
            print(canonical_json_text(result["status"]))
            return 0 if result["status"]["status"] == "prepared" else 1
        if args.resume:
            result = resume_dispatch(Path(args.resume))
            print(canonical_json_text(result["status"]))
            return 0 if result["status"]["status"] == "prepared" else 1
        raise DispatchError("ERR_DISPATCH_ARGUMENTS", "expected --packet, --resume, or --self-test")
    except DispatchError as exc:
        print(canonical_json_text(exc.to_record()), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
