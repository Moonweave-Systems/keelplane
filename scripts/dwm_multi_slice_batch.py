#!/usr/bin/env python3
"""V81 multi-slice batch planner for safe DWM continuation."""

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


TOOL = "dwm_multi_slice_batch.py"
SCHEMA_VERSION = "1.0"
BATCH_VERSION = "81.0.0"
BATCH_ROOT = ROOT / "out" / "multi-slice-batches"
DEFAULT_BOUNDARY = ROOT / "out" / "continuation-boundaries" / "v80-canonical" / "continuation-boundary.json"
SENTINEL = ".dwm_multi_slice_batch-owned.json"

SAFE_COMMANDS = {
    "V80": "python scripts/dwm_continuation_boundary.py assess --preflight out/large-workflow-queue-preflight/v77-canonical/queue-preflight.json --timing out/graph-timing/v78-canonical/graph-timing.json --visibility out/readme-graph-visibility/v79-canonical/readme-graph-visibility.json --out out/continuation-boundaries/v80-canonical",
    "V81": "python scripts/dwm_multi_slice_batch.py plan --boundary out/continuation-boundaries/v80-canonical/continuation-boundary.json --out out/multi-slice-batches/v81-canonical",
    "V82": "python scripts/dwm_execution_receipt_schema.py --self-test",
    "V83": "python scripts/dwm_runner_receipt_dry_run.py --self-test",
}
FORBIDDEN_COMMAND_TERMS = ["git push", "git commit", "rm ", "curl ", "npm install", "pip install", "deploy", "secret", "network"]


class MultiSliceBatchError(ValueError):
    """Structured V81 multi-slice batch failure."""

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
        raise MultiSliceBatchError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise MultiSliceBatchError(code, "path contains a symlink", path=current)


def resolve_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_MULTI_SLICE_BATCH_PATH_UNSAFE", message="batch output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = BATCH_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise MultiSliceBatchError("ERR_MULTI_SLICE_BATCH_PATH_UNSAFE", f"batch output must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise MultiSliceBatchError("ERR_MULTI_SLICE_BATCH_PATH_UNSAFE", "batch output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_MULTI_SLICE_BATCH_PATH_SYMLINK")
    return resolved


def resolve_boundary(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_MULTI_SLICE_BATCH_BOUNDARY_UNSAFE", message="boundary path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to((ROOT / "out" / "continuation-boundaries").resolve(strict=False))
    except ValueError as exc:
        raise MultiSliceBatchError("ERR_MULTI_SLICE_BATCH_BOUNDARY_UNSAFE", "boundary path must resolve under out/continuation-boundaries", path=value) from exc
    check_components_not_symlink(candidate, code="ERR_MULTI_SLICE_BATCH_PATH_SYMLINK")
    if not resolved.is_file() or resolved.is_symlink():
        raise MultiSliceBatchError("ERR_MULTI_SLICE_BATCH_BOUNDARY_MISSING", "boundary artifact is missing or unsafe", path=value)
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


def prepare_out_dir(path: Path, batch_id: str, *, source: Path | str) -> None:
    if path.exists():
        if path.is_symlink():
            raise MultiSliceBatchError("ERR_MULTI_SLICE_BATCH_PATH_SYMLINK", "batch output is a symlink", path=path)
        if not path.is_dir():
            raise MultiSliceBatchError("ERR_MULTI_SLICE_BATCH_PATH_UNSAFE", "batch output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("batch_id") != batch_id:
            raise MultiSliceBatchError("ERR_MULTI_SLICE_BATCH_PATH_UNSAFE", "existing batch output is not batch-owned", path=path)
        shutil.rmtree(path)
    BATCH_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(
        path / SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "batch_version": BATCH_VERSION,
            "batch_id": batch_id,
            "source_path": str(source),
            "created_at": now_utc(),
        },
        root=path,
    )


def command_is_safe(command: str) -> bool:
    lower = command.lower()
    return not any(term in lower for term in FORBIDDEN_COMMAND_TERMS)


def make_batch(batch_id: str, boundary: dict[str, Any], *, boundary_path: Path | None = None) -> dict[str, Any]:
    blockers: list[dict[str, str]] = []
    if boundary.get("decision") != "continue_source_control_plane":
        blockers.append({"code": "ERR_MULTI_SLICE_BATCH_BOUNDARY_BLOCKED", "message": "continuation boundary is not ready"})
    if boundary.get("can_continue_without_human") is not True:
        blockers.append({"code": "ERR_MULTI_SLICE_BATCH_HUMAN_REQUIRED", "message": "boundary requires human input"})

    slices = []
    for item in boundary.get("safe_batchable_slices", []):
        if not isinstance(item, dict):
            continue
        slice_id = str(item.get("id", ""))
        if slice_id == "V80":
            continue
        command = SAFE_COMMANDS.get(slice_id)
        if not command:
            blockers.append({"code": "ERR_MULTI_SLICE_BATCH_COMMAND_MISSING", "message": f"no safe command registered for {slice_id}"})
            continue
        if not command_is_safe(command):
            blockers.append({"code": "ERR_MULTI_SLICE_BATCH_COMMAND_UNSAFE", "message": f"unsafe command registered for {slice_id}"})
            continue
        slices.append(
            {
                "id": slice_id,
                "name": item.get("name"),
                "risk": item.get("risk"),
                "command": command,
                "execution_mode": "plan-only" if slice_id in {"V82", "V83"} else "source-only",
            }
        )

    ready = not blockers and bool(slices)
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "batch_version": BATCH_VERSION,
        "batch_id": batch_id,
        "status": "multi-slice-batch-ready" if ready else "multi-slice-batch-blocked",
        "decision": "batch_ready" if ready else "blocked",
        "batchable_until": boundary.get("continuous_until"),
        "first_human_gate": boundary.get("first_human_gate"),
        "slices": slices,
        "blocked_by": blockers,
        "source_paths": {"boundary": rel(boundary_path) if boundary_path is not None else None},
        "source_hashes": {"boundary": canonical_hash(boundary)},
    }


def render_markdown(batch: dict[str, Any]) -> str:
    lines = [
        f"# Multi-Slice Batch {batch['batch_id']}",
        "",
        f"- Status: `{batch['status']}`",
        f"- Decision: `{batch['decision']}`",
        f"- Batchable until: {batch['batchable_until']}",
        "",
        "## Slices",
        "",
    ]
    for item in batch["slices"]:
        lines.append(f"- `{item['id']}` {item['name']}: `{item['command']}`")
    lines.extend(["", "## Blockers", ""])
    if batch["blocked_by"]:
        for item in batch["blocked_by"]:
            lines.append(f"- `{item['code']}`: {item['message']}")
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def write_batch(out_dir: Path, batch: dict[str, Any]) -> None:
    write_json_atomic(out_dir / "multi-slice-batch.json", batch, root=out_dir)
    write_json_atomic(out_dir / "status.json", batch, root=out_dir)
    write_text_atomic(out_dir / "multi-slice-batch.md", render_markdown(batch), root=out_dir)


def run_plan(boundary_path: Path, out_dir: Path) -> dict[str, Any]:
    boundary_path = resolve_boundary(boundary_path)
    out_dir = resolve_out(out_dir)
    prepare_out_dir(out_dir, out_dir.name, source=boundary_path)
    boundary = read_json(boundary_path)
    batch = make_batch(out_dir.name, boundary, boundary_path=boundary_path)
    write_batch(out_dir, batch)
    return batch


def run_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    fixtures = manifest.get("fixtures")
    if not isinstance(fixtures, list):
        raise MultiSliceBatchError("ERR_MULTI_SLICE_BATCH_MANIFEST_INVALID", "manifest fixtures must be a list", path=manifest_path)
    suite_id = str(manifest.get("suite_id", "v81-multi-slice-batch"))
    out_dir = resolve_out(out_dir)
    prepare_out_dir(out_dir, out_dir.name, source=manifest_path)
    records = []
    for fixture in fixtures:
        if not isinstance(fixture, dict):
            raise MultiSliceBatchError("ERR_MULTI_SLICE_BATCH_MANIFEST_INVALID", "fixture must be an object", path=manifest_path)
        fixture_id = str(fixture.get("id", "fixture"))
        fixture_out = out_dir / fixture_id
        prepare_out_dir(fixture_out, fixture_id, source=manifest_path)
        batch = make_batch(fixture_id, fixture.get("boundary") if isinstance(fixture.get("boundary"), dict) else {})
        write_batch(fixture_out, batch)
        expected_decision = fixture.get("expected_decision")
        status = "pass" if expected_decision in (None, batch["decision"]) else "fail"
        records.append({"id": fixture_id, "required": bool(fixture.get("required", True)), "status": status, "decision": batch["decision"], "error": None if status == "pass" else f"expected {expected_decision}, got {batch['decision']}"})
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
        raise MultiSliceBatchError("ERR_MULTI_SLICE_BATCH_FIXTURE_FAILED", "required multi-slice batch fixture failed", path=manifest_path)
    return summary


def ready_boundary() -> dict[str, Any]:
    return {
        "decision": "continue_source_control_plane",
        "can_continue_without_human": True,
        "continuous_until": "V83 source-only control-plane and receipt-schema work",
        "first_human_gate": {"id": "V84", "reason": "actual execution"},
        "safe_batchable_slices": [
            {"id": "V80", "name": "continuation boundary gate", "risk": "source-only"},
            {"id": "V81", "name": "multi-slice batch planner", "risk": "source-only"},
            {"id": "V82", "name": "execution receipt schema preflight", "risk": "source-only"},
            {"id": "V83", "name": "runner receipt dry-run gate", "risk": "fixture-only"},
        ],
    }


def self_test() -> None:
    ready = make_batch("self-test", ready_boundary())
    if ready["decision"] != "batch_ready" or len(ready["slices"]) != 3:
        raise MultiSliceBatchError("ERR_MULTI_SLICE_BATCH_SELF_TEST_FAILED", "ready boundary should produce three planned slices")
    blocked = ready_boundary()
    blocked["can_continue_without_human"] = False
    if make_batch("self-test-blocked", blocked)["decision"] != "blocked":
        raise MultiSliceBatchError("ERR_MULTI_SLICE_BATCH_SELF_TEST_FAILED", "human-required boundary should block")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--out", type=Path)
    subparsers = parser.add_subparsers(dest="command")
    plan_parser = subparsers.add_parser("plan")
    plan_parser.add_argument("--boundary", type=Path, default=DEFAULT_BOUNDARY)
    plan_parser.add_argument("--out", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        if args.self_test:
            self_test()
            print("multi-slice batch self-test: pass")
            return
        if args.manifest:
            if args.out is None:
                raise MultiSliceBatchError("ERR_MULTI_SLICE_BATCH_ARGS_INVALID", "--manifest requires --out")
            print(json.dumps(run_manifest(args.manifest, args.out), sort_keys=True))
            return
        if args.command == "plan":
            batch = run_plan(args.boundary, args.out)
            print(json.dumps({"status": batch["status"], "decision": batch["decision"], "batch_id": batch["batch_id"]}, sort_keys=True))
            return
        raise MultiSliceBatchError("ERR_MULTI_SLICE_BATCH_ARGS_INVALID", "choose --self-test, --manifest, or plan")
    except MultiSliceBatchError as exc:
        print(json.dumps({"status": "error", "error": exc.to_record()}, sort_keys=True), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
