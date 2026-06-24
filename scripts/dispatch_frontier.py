#!/usr/bin/env python3
"""Prepare a dispatch bundle from one trusted V6 frontier packet."""

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
from ingest_worker_review import (  # noqa: E402
    SENTINEL as V6_SENTINEL,
    V6_OUT_ROOT,
    IngestError,
    read_sentinel as read_v6_sentinel,
    resume_ingestion,
    start_ingestion,
)
from review_worker_result import V55_OUT_ROOT  # noqa: E402


TOOL = "dispatch_frontier.py"
SCHEMA_VERSION = "1.0"
FRONTIER_DISPATCH_VERSION = "0.1.0"
V65_OUT_ROOT = ROOT / "out" / "v6.5"
SENTINEL = ".dispatch_frontier-owned.json"


class FrontierDispatchError(ValueError):
    """Structured V6.5 frontier-dispatch failure."""

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
        raise FrontierDispatchError(code, message, path=path)


def check_components_not_symlink(path: Path, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise FrontierDispatchError(code, "path contains a symlink", path=current)


def resolve_under_out(value: str | Path, root: Path, *, label: str) -> Path:
    raw = Path(value)
    reject_traversal(raw, "ERR_FRONTIER_DISPATCH_OUTSIDE_REPO", f"{label} path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    out_root = root.resolve(strict=False)
    forbidden = {ROOT.resolve(), (ROOT / "out").resolve(strict=False), out_root}
    if resolved in forbidden:
        raise FrontierDispatchError("ERR_FRONTIER_DISPATCH_OUTSIDE_REPO", f"{label} path must name a run directory", path=value)
    try:
        resolved.relative_to(out_root)
    except ValueError as exc:
        raise FrontierDispatchError("ERR_FRONTIER_DISPATCH_OUTSIDE_REPO", f"{label} path must resolve under {out_root}", path=value) from exc
    check_components_not_symlink(candidate, "ERR_FRONTIER_DISPATCH_DIR_SYMLINK")
    return resolved


def resolve_v6(value: str | Path) -> Path:
    return resolve_under_out(value, V6_OUT_ROOT, label="V6 frontier")


def resolve_v65_out(value: str | Path) -> Path:
    return resolve_under_out(value, V65_OUT_ROOT, label="V6.5 output")


def ensure_contained(root: Path, path: Path) -> None:
    target = path if path.is_absolute() else root / path
    reject_traversal(path, "ERR_FRONTIER_DISPATCH_OUTSIDE_REPO", "artifact path escapes owned directory")
    try:
        target.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError as exc:
        raise FrontierDispatchError("ERR_FRONTIER_DISPATCH_OUTSIDE_REPO", "artifact path escapes owned directory", path=target) from exc


def ensure_artifact_parent(root: Path, path: Path) -> None:
    ensure_contained(root, path)
    current = root.resolve(strict=False)
    for part in path.resolve(strict=False).relative_to(current).parent.parts:
        current = current / part
        if current.exists():
            if current.is_symlink():
                raise FrontierDispatchError("ERR_FRONTIER_DISPATCH_DIR_SYMLINK", "artifact parent is symlinked", path=current)
            if not current.is_dir():
                raise FrontierDispatchError("ERR_FRONTIER_DISPATCH_OUTSIDE_REPO", "artifact parent is not a directory", path=current)
        else:
            current.mkdir()


def ensure_leaf_not_symlink(path: Path) -> None:
    if path.exists():
        if path.is_symlink():
            raise FrontierDispatchError("ERR_FRONTIER_DISPATCH_LEAF_SYMLINK", "refusing to overwrite symlinked file", path=path)
        if not path.is_file():
            raise FrontierDispatchError("ERR_FRONTIER_DISPATCH_OUTSIDE_REPO", "refusing to overwrite non-file leaf", path=path)


def write_text(path: Path, text: str, *, root: Path) -> None:
    ensure_artifact_parent(root, path)
    ensure_leaf_not_symlink(path)
    write_text_atomic(path, text, root=root)


def write_json(path: Path, data: Any, *, root: Path) -> None:
    write_text(path, canonical_json_text(data), root=root)


def read_json_obj(path: Path, *, code: str, label: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise FrontierDispatchError(code, f"{label} is missing or symlinked", path=path)
    try:
        data = json.loads(path.read_text())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FrontierDispatchError(code, f"{label} is malformed: {exc}", path=path) from exc
    if not isinstance(data, dict):
        raise FrontierDispatchError(code, f"{label} root must be an object", path=path)
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


def sentinel_payload(run_id: str, v6_dir: Path) -> dict[str, Any]:
    return {
        "tool": TOOL,
        "schema_version": SCHEMA_VERSION,
        "frontier_dispatch_version": FRONTIER_DISPATCH_VERSION,
        "run_id": run_id,
        "v6_run_path": rel(v6_dir),
        "created_at": now_utc(),
    }


def ensure_frontier_dispatch_dir(path: Path, run_id: str, v6_dir: Path) -> None:
    path = resolve_v65_out(path)
    if path.exists():
        if path.is_symlink():
            raise FrontierDispatchError("ERR_FRONTIER_DISPATCH_DIR_SYMLINK", "V6.5 output directory is a symlink", path=path)
        if not path.is_dir():
            raise FrontierDispatchError("ERR_FRONTIER_DISPATCH_OUTSIDE_REPO", "V6.5 output exists and is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None:
            raise FrontierDispatchError("ERR_FRONTIER_DISPATCH_ARTIFACT_MALFORMED", "existing V6.5 output is not owned", path=path)
        expected = sentinel_payload(run_id, v6_dir)
        expected["created_at"] = sentinel.get("created_at")
        if sentinel != expected:
            raise FrontierDispatchError("ERR_FRONTIER_DISPATCH_ARTIFACT_MALFORMED", "V6.5 output sentinel does not match this frontier", path=path)
    path.mkdir(parents=True, exist_ok=True)
    if read_sentinel(path) is None:
        write_json(path / SENTINEL, sentinel_payload(run_id, v6_dir), root=path)


def require_string_list(value: Any, *, code: str, message: str, path: Path) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise FrontierDispatchError(code, message, path=path)
    return value


def prompt_path_for_packet(packet_path: Path) -> Path:
    return packet_path.with_name(packet_path.name.removesuffix(".packet.json") + ".prompt.md")


def trusted_v6_context(v6_dir: Path) -> dict[str, Any]:
    v6_dir = resolve_v6(v6_dir)
    if read_v6_sentinel(v6_dir, V6_SENTINEL) is None:
        raise FrontierDispatchError("ERR_FRONTIER_DISPATCH_UNTRUSTED_V6", "V6 output is missing ownership sentinel", path=v6_dir / V6_SENTINEL)
    try:
        resumed = resume_ingestion(v6_dir)
    except IngestError as exc:
        raise FrontierDispatchError("ERR_FRONTIER_DISPATCH_UNTRUSTED_V6", exc.message, path=exc.path) from exc
    if resumed["status"]["status"] != "frontier-ready" or resumed["status"]["resume_state"] != "resumable":
        raise FrontierDispatchError("ERR_FRONTIER_DISPATCH_ENTRY_REJECTED", "V6 frontier is not ready and resumable", path=v6_dir / "status.json")

    run = read_json_obj(v6_dir / "run.json", code="ERR_FRONTIER_DISPATCH_UNTRUSTED_V6", label="V6 run.json")
    state = read_json_obj(v6_dir / "state.json", code="ERR_FRONTIER_DISPATCH_UNTRUSTED_V6", label="V6 state.json")
    status = read_json_obj(v6_dir / "status.json", code="ERR_FRONTIER_DISPATCH_UNTRUSTED_V6", label="V6 status.json")
    selected = require_string_list(
        state.get("selected_phase_ids"),
        code="ERR_FRONTIER_DISPATCH_UNTRUSTED_V6",
        message="selected_phase_ids is malformed",
        path=v6_dir / "state.json",
    )
    if len(selected) != 1:
        raise FrontierDispatchError("ERR_FRONTIER_DISPATCH_ENTRY_REJECTED", "first slice requires exactly one selected frontier phase", path=v6_dir / "state.json")
    packet_paths = require_string_list(
        run.get("packet_paths"),
        code="ERR_FRONTIER_DISPATCH_UNTRUSTED_V6",
        message="run packet_paths is malformed",
        path=v6_dir / "run.json",
    )
    if len(packet_paths) != 1:
        raise FrontierDispatchError("ERR_FRONTIER_DISPATCH_ENTRY_REJECTED", "first slice requires exactly one packet path", path=v6_dir / "run.json")
    packet_path = v6_dir / packet_paths[0]
    packet = read_json_obj(packet_path, code="ERR_FRONTIER_DISPATCH_UNTRUSTED_V6", label="frontier packet")
    prompt_path = prompt_path_for_packet(packet_path)
    if not prompt_path.is_file() or prompt_path.is_symlink():
        raise FrontierDispatchError("ERR_FRONTIER_DISPATCH_UNTRUSTED_V6", "frontier prompt is missing or symlinked", path=prompt_path)
    prompt = prompt_path.read_text()
    phase_id = packet.get("phase_id")
    packet_id = packet.get("packet_id")
    if phase_id != selected[0] or not isinstance(packet_id, str):
        raise FrontierDispatchError("ERR_FRONTIER_DISPATCH_UNTRUSTED_V6", "frontier packet does not match selected phase", path=packet_path)
    packet_hashes = state.get("packet_hashes")
    prompt_hashes = state.get("prompt_hashes")
    if not isinstance(packet_hashes, dict) or not isinstance(prompt_hashes, dict):
        raise FrontierDispatchError("ERR_FRONTIER_DISPATCH_UNTRUSTED_V6", "state packet or prompt hashes are malformed", path=v6_dir / "state.json")
    if packet_hashes.get(packet_id) != canonical_hash(packet):
        raise FrontierDispatchError("ERR_FRONTIER_DISPATCH_STALE_V6", "frontier packet hash does not match state", path=packet_path)
    if prompt_hashes.get(packet_id) != sha256_text(prompt):
        raise FrontierDispatchError("ERR_FRONTIER_DISPATCH_STALE_V6", "frontier prompt hash does not match state", path=prompt_path)
    snapshots = status.get("snapshots")
    if isinstance(snapshots, dict) and snapshots.get("state_hash") != canonical_hash(state):
        raise FrontierDispatchError("ERR_FRONTIER_DISPATCH_STALE_V6", "V6 state hash does not match status snapshot", path=v6_dir / "state.json")
    return {
        "v6_dir": v6_dir,
        "run": run,
        "state": state,
        "status": status,
        "packet_path": packet_path,
        "prompt_path": prompt_path,
        "packet": packet,
        "prompt": prompt,
    }


def build_dispatch(context: dict[str, Any], *, created_at: str | None = None) -> dict[str, Any]:
    packet = context["packet"]
    return {
        "schema_version": SCHEMA_VERSION,
        "frontier_dispatch_version": FRONTIER_DISPATCH_VERSION,
        "dispatch_id": "0000",
        "created_at": created_at or now_utc(),
        "status": "prepared",
        "mode": "emit-only",
        "backend": "manual-or-future-worker-adapter",
        "source_v6_run_path": rel(context["v6_dir"]),
        "source_packet_path": rel(context["packet_path"]),
        "source_prompt_path": rel(context["prompt_path"]),
        "packet_id": packet.get("packet_id"),
        "phase_id": packet.get("phase_id"),
        "completed_phase_ids": packet.get("completed_phase_ids", []),
        "reviewed_phase_ids": packet.get("reviewed_phase_ids", []),
        "worker_ids": packet.get("worker_ids", []),
        "expected_outputs": packet.get("expected_outputs", []),
        "stop_conditions": [
            "do not execute this dispatch bundle directly",
            "route any frontier worker result through V7.5 frontier result review before runtime ingestion",
            "stop before destructive, external, costly, production, secret, dependency, database, public API, delete, or history-rewrite actions",
        ],
        "artifacts": {
            "packet_copy_path": "packet.json",
            "prompt_copy_path": "prompt.md",
            "hashes_path": "hashes.json",
        },
    }


def build_hashes(context: dict[str, Any], dispatch: dict[str, Any]) -> dict[str, str]:
    return {
        "source_v6_run_hash": canonical_hash(context["run"]),
        "source_v6_state_hash": canonical_hash(context["state"]),
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
        "frontier_dispatch_version": FRONTIER_DISPATCH_VERSION,
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
        "# V6.5 Frontier Dispatch Resume",
        "",
        f"Run: `{status['run_id']}`",
        f"Status: `{status['status']}`",
        f"Resume state: `{status['resume_state']}`",
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


def write_error_status(out_dir: Path, run_id: str, v6_dir: Path, error: FrontierDispatchError) -> dict[str, Any]:
    ensure_frontier_dispatch_dir(out_dir, run_id, v6_dir)
    status = build_status(run_id, dispatch=None, hashes=None, status="invalid", resume_state="invalid", invalidators=[error.to_record()])
    write_status(out_dir, status)
    return status


def start_frontier_dispatch(v6_dir: Path, *, out_dir: Path | None = None) -> dict[str, Any]:
    v6_dir = resolve_v6(v6_dir)
    out_dir = resolve_v65_out(out_dir) if out_dir is not None else V65_OUT_ROOT / v6_dir.name
    run_id = out_dir.name
    try:
        context = trusted_v6_context(v6_dir)
        ensure_frontier_dispatch_dir(out_dir, run_id, v6_dir)
        dispatch = build_dispatch(context)
        hashes = build_hashes(context, dispatch)
        status = build_status(run_id, dispatch=dispatch, hashes=hashes, status="prepared", resume_state="fresh")
    except FrontierDispatchError as exc:
        status = write_error_status(out_dir, run_id, v6_dir, exc)
        return {"status": status, "out_dir": out_dir}
    write_json(out_dir / "dispatch.json", dispatch, root=out_dir)
    write_json(out_dir / "packet.json", context["packet"], root=out_dir)
    write_text(out_dir / "prompt.md", context["prompt"], root=out_dir)
    write_json(out_dir / "hashes.json", hashes, root=out_dir)
    write_status(out_dir, status)
    return {"status": status, "out_dir": out_dir, "dispatch": dispatch}


def validate_frontier_dispatch_sentinel(run_dir: Path, run_id: str, v6_dir: Path) -> None:
    sentinel = read_sentinel(run_dir)
    if sentinel is None:
        raise FrontierDispatchError("ERR_FRONTIER_DISPATCH_ARTIFACT_MALFORMED", "V6.5 output is missing ownership sentinel", path=run_dir / SENTINEL)
    expected = sentinel_payload(run_id, v6_dir)
    expected["created_at"] = sentinel.get("created_at")
    if sentinel != expected:
        raise FrontierDispatchError("ERR_FRONTIER_DISPATCH_ARTIFACT_MALFORMED", "V6.5 output sentinel does not match frontier", path=run_dir / SENTINEL)


def resume_frontier_dispatch(run_dir: Path) -> dict[str, Any]:
    run_dir = resolve_v65_out(run_dir)
    run_id = run_dir.name
    sentinel = read_sentinel(run_dir)
    if sentinel is None or not isinstance(sentinel.get("v6_run_path"), str):
        raise FrontierDispatchError("ERR_FRONTIER_DISPATCH_ARTIFACT_MALFORMED", "sentinel is missing v6_run_path", path=run_dir / SENTINEL)
    v6_dir = resolve_v6(sentinel["v6_run_path"])
    validate_frontier_dispatch_sentinel(run_dir, run_id, v6_dir)
    dispatch = read_json_obj(run_dir / "dispatch.json", code="ERR_FRONTIER_DISPATCH_ARTIFACT_MALFORMED", label="dispatch.json")
    hashes = read_json_obj(run_dir / "hashes.json", code="ERR_FRONTIER_DISPATCH_ARTIFACT_MALFORMED", label="hashes.json")
    packet_copy = read_json_obj(run_dir / "packet.json", code="ERR_FRONTIER_DISPATCH_ARTIFACT_MALFORMED", label="packet.json")
    prompt_path = run_dir / "prompt.md"
    if not prompt_path.is_file() or prompt_path.is_symlink():
        raise FrontierDispatchError("ERR_FRONTIER_DISPATCH_ARTIFACT_MALFORMED", "prompt.md is missing or symlinked", path=prompt_path)

    invalidators: list[dict[str, Any]] = []
    expected_dispatch = dispatch
    expected_hashes: dict[str, str] | None = None
    try:
        context = trusted_v6_context(v6_dir)
        expected_dispatch = build_dispatch(context, created_at=str(dispatch.get("created_at")))
        expected_hashes = build_hashes(context, expected_dispatch)
        if dispatch != expected_dispatch:
            invalidators.append({"code": "ERR_FRONTIER_DISPATCH_ARTIFACT_MALFORMED", "message": "dispatch does not match current frontier"})
        if hashes != expected_hashes:
            invalidators.append({"code": "ERR_FRONTIER_DISPATCH_ARTIFACT_MALFORMED", "message": "hashes do not match current frontier"})
        if packet_copy != context["packet"]:
            invalidators.append({"code": "ERR_FRONTIER_DISPATCH_ARTIFACT_MALFORMED", "message": "packet copy does not match current frontier"})
        if prompt_path.read_text() != context["prompt"]:
            invalidators.append({"code": "ERR_FRONTIER_DISPATCH_ARTIFACT_MALFORMED", "message": "prompt copy does not match current frontier"})
    except FrontierDispatchError as exc:
        invalidators.append(exc.to_record())

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


def reset_owned(path: Path, sentinel_name: str, tool: str) -> None:
    if not path.exists():
        return
    sentinel_path = path / sentinel_name
    if not sentinel_path.is_file() or sentinel_path.is_symlink():
        raise FrontierDispatchError("ERR_FRONTIER_DISPATCH_ARTIFACT_MALFORMED", "existing self-test output is not owned", path=path)
    try:
        sentinel = json.loads(sentinel_path.read_text())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FrontierDispatchError("ERR_FRONTIER_DISPATCH_ARTIFACT_MALFORMED", f"existing self-test sentinel is malformed: {exc}", path=sentinel_path) from exc
    if not isinstance(sentinel, dict) or sentinel.get("tool") != tool:
        raise FrontierDispatchError("ERR_FRONTIER_DISPATCH_ARTIFACT_MALFORMED", "existing self-test output is not owned by expected tool", path=path)
    shutil.rmtree(path)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise FrontierDispatchError("ERR_FRONTIER_DISPATCH_SELF_TEST_FAILED", message)


def self_test() -> None:
    source = V6_OUT_ROOT / "frontier-dispatch-self-test-source"
    out_dir = V65_OUT_ROOT / "frontier-dispatch-self-test"
    reset_owned(source, V6_SENTINEL, "ingest_worker_review.py")
    reset_owned(out_dir, SENTINEL, TOOL)
    started_source = start_ingestion(V55_OUT_ROOT / "v32-semantic-dogfood", out_dir=source)
    require(started_source["status"]["status"] == "frontier-ready", "trusted V6 source should be frontier-ready")
    started = start_frontier_dispatch(source, out_dir=out_dir)
    require(started["status"]["status"] == "prepared", "trusted frontier should prepare dispatch")
    require(started["status"]["phase_id"] == "release_decision", "dogfood frontier should dispatch release_decision")
    resumed = resume_frontier_dispatch(out_dir)
    require(resumed["status"]["resume_state"] == "resumable", "clean frontier dispatch should resume")
    packet = read_json_obj(out_dir / "packet.json", code="ERR_FRONTIER_DISPATCH_ARTIFACT_MALFORMED", label="packet.json")
    packet["phase_id"] = "tampered"
    write_json(out_dir / "packet.json", packet, root=out_dir)
    tampered = resume_frontier_dispatch(out_dir)
    require(tampered["status"]["status"] == "invalid", "tampered packet copy should invalidate")
    print("dispatch_frontier self-test: pass")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frontier", help="trusted V6 frontier directory under out/v6")
    parser.add_argument("--resume", help="V6.5 frontier dispatch output directory under out/v6.5")
    parser.add_argument("--out", help="V6.5 output directory")
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if args.self_test:
            self_test()
            return 0
        if args.frontier:
            result = start_frontier_dispatch(Path(args.frontier), out_dir=Path(args.out) if args.out else None)
            print(canonical_json_text(result["status"]))
            return 0 if result["status"]["status"] == "prepared" else 1
        if args.resume:
            result = resume_frontier_dispatch(Path(args.resume))
            print(canonical_json_text(result["status"]))
            return 0 if result["status"]["status"] == "prepared" else 1
        raise FrontierDispatchError("ERR_FRONTIER_DISPATCH_ARGUMENTS", "expected --frontier, --resume, or --self-test")
    except FrontierDispatchError as exc:
        print(canonical_json_text(exc.to_record()), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
