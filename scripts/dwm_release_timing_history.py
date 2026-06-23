#!/usr/bin/env python3
"""V72 release timing history ledger builder."""

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


TOOL = "dwm_release_timing_history.py"
SCHEMA_VERSION = "1.0"
HISTORY_VERSION = "72.0.0"
HISTORY_ROOT = ROOT / "out" / "release-timing-history"
TIMING_ROOT = ROOT / "out" / "release-timing"
SENTINEL = ".dwm_release_timing_history-owned.json"
ACCEPTED_TIMING_STATUSES = {
    "release-timing-planned",
    "release-timing-recorded",
    "release-timing-blocked",
}


class ReleaseTimingHistoryError(ValueError):
    """Structured V72 release timing history failure."""

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
        raise ReleaseTimingHistoryError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise ReleaseTimingHistoryError(code, "path contains a symlink", path=current)


def resolve_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_RELEASE_TIMING_HISTORY_PATH_UNSAFE", message="history output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = HISTORY_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ReleaseTimingHistoryError("ERR_RELEASE_TIMING_HISTORY_PATH_UNSAFE", f"history output must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise ReleaseTimingHistoryError("ERR_RELEASE_TIMING_HISTORY_PATH_UNSAFE", "history output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_RELEASE_TIMING_HISTORY_PATH_SYMLINK")
    return resolved


def resolve_timing_root(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_RELEASE_TIMING_HISTORY_SOURCE_UNSAFE", message="timing root must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    timing_root_resolved = TIMING_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(timing_root_resolved)
    except ValueError as exc:
        raise ReleaseTimingHistoryError("ERR_RELEASE_TIMING_HISTORY_SOURCE_UNSAFE", f"timing root must resolve under {timing_root_resolved}", path=value) from exc
    check_components_not_symlink(candidate, code="ERR_RELEASE_TIMING_HISTORY_PATH_SYMLINK")
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


def prepare_out_dir(path: Path, history_id: str, *, source: Path | str) -> None:
    if path.exists():
        if path.is_symlink():
            raise ReleaseTimingHistoryError("ERR_RELEASE_TIMING_HISTORY_PATH_SYMLINK", "history output is a symlink", path=path)
        if not path.is_dir():
            raise ReleaseTimingHistoryError("ERR_RELEASE_TIMING_HISTORY_PATH_UNSAFE", "history output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("history_id") != history_id:
            raise ReleaseTimingHistoryError("ERR_RELEASE_TIMING_HISTORY_PATH_UNSAFE", "existing history output is not history-owned", path=path)
        shutil.rmtree(path)
    HISTORY_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(
        path / SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "history_version": HISTORY_VERSION,
            "history_id": history_id,
            "source_path": str(source),
            "created_at": now_utc(),
        },
        root=path,
    )


def measured_duration_ms(timing: dict[str, Any]) -> int:
    total = 0
    commands = timing.get("commands")
    if not isinstance(commands, list):
        return total
    for command in commands:
        if isinstance(command, dict) and isinstance(command.get("duration_ms"), int):
            total += int(command["duration_ms"])
    return total


def validate_timing(timing: dict[str, Any], *, path: Path | str | None = None, fixture_id: str | None = None) -> dict[str, Any]:
    timing_id = timing.get("timing_id")
    status = timing.get("status")
    if not isinstance(timing_id, str) or not timing_id:
        raise ReleaseTimingHistoryError("ERR_RELEASE_TIMING_HISTORY_TIMING_INVALID", "timing_id is required", path=path, fixture_id=fixture_id)
    if status not in ACCEPTED_TIMING_STATUSES:
        raise ReleaseTimingHistoryError("ERR_RELEASE_TIMING_HISTORY_STATUS_INVALID", "timing status is not accepted", path=path, fixture_id=fixture_id)
    command_count = timing.get("command_count")
    measured_count = timing.get("measured_count")
    if not isinstance(command_count, int) or command_count < 0:
        raise ReleaseTimingHistoryError("ERR_RELEASE_TIMING_HISTORY_TIMING_INVALID", "command_count must be a non-negative integer", path=path, fixture_id=fixture_id)
    if not isinstance(measured_count, int) or measured_count < 0:
        raise ReleaseTimingHistoryError("ERR_RELEASE_TIMING_HISTORY_TIMING_INVALID", "measured_count must be a non-negative integer", path=path, fixture_id=fixture_id)
    return {
        "timing_id": timing_id,
        "status": status,
        "mode": timing.get("mode"),
        "command_count": command_count,
        "measured_count": measured_count,
        "measured_duration_ms": measured_duration_ms(timing),
        "source_hash": canonical_hash(timing),
        "path": str(path) if path is not None else None,
    }


def load_timing_files(timing_root: Path) -> list[dict[str, Any]]:
    if not timing_root.is_dir() or timing_root.is_symlink():
        raise ReleaseTimingHistoryError("ERR_RELEASE_TIMING_HISTORY_SOURCE_MISSING", "timing root is missing or symlinked", path=timing_root)
    records = []
    for timing_file in sorted(timing_root.rglob("release-timing.json")):
        timing = read_json(timing_file)
        records.append(validate_timing(timing, path=timing_file))
    if not records:
        raise ReleaseTimingHistoryError("ERR_RELEASE_TIMING_HISTORY_EMPTY", "no release-timing.json files found", path=timing_root)
    return records


def build_history(*, history_id: str, records: list[dict[str, Any]], source: str) -> dict[str, Any]:
    seen: set[str] = set()
    duplicate_ids = []
    for record in records:
        timing_id = str(record["timing_id"])
        if timing_id in seen:
            duplicate_ids.append(timing_id)
        seen.add(timing_id)
    if duplicate_ids:
        raise ReleaseTimingHistoryError("ERR_RELEASE_TIMING_HISTORY_DUPLICATE_ID", f"duplicate timing_id values: {duplicate_ids}")
    sorted_records = sorted(records, key=lambda record: str(record["timing_id"]))
    measured_records = [record for record in sorted_records if record["measured_count"] > 0]
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "history_version": HISTORY_VERSION,
        "history_id": history_id,
        "status": "release-timing-history-recorded",
        "record_count": len(sorted_records),
        "planned_count": sum(1 for record in sorted_records if record["status"] == "release-timing-planned"),
        "recorded_count": sum(1 for record in sorted_records if record["status"] == "release-timing-recorded"),
        "blocked_count": sum(1 for record in sorted_records if record["status"] == "release-timing-blocked"),
        "total_command_count": sum(int(record["command_count"]) for record in sorted_records),
        "total_measured_count": sum(int(record["measured_count"]) for record in sorted_records),
        "total_measured_duration_ms": sum(int(record["measured_duration_ms"]) for record in sorted_records),
        "slowest_record": max(measured_records, key=lambda record: int(record["measured_duration_ms"])) if measured_records else None,
        "records": sorted_records,
        "source_hashes": {
            "source": canonical_hash(source),
            "records": canonical_hash(sorted_records),
        },
    }


def render_markdown(history: dict[str, Any]) -> str:
    lines = [
        f"# Release Timing History {history['history_id']}",
        "",
        f"- Status: `{history['status']}`",
        f"- Records: `{history['record_count']}`",
        f"- Planned: `{history['planned_count']}`",
        f"- Recorded: `{history['recorded_count']}`",
        f"- Blocked: `{history['blocked_count']}`",
        f"- Total measured duration ms: `{history['total_measured_duration_ms']}`",
        "",
        "## Records",
        "",
        "| Timing | Status | Measured | Duration ms |",
        "| --- | --- | ---: | ---: |",
    ]
    for record in history["records"]:
        lines.append(
            f"| `{record['timing_id']}` | `{record['status']}` | {record['measured_count']} | {record['measured_duration_ms']} |"
        )
    lines.append("")
    return "\n".join(lines)


def write_history(out_dir: Path, history: dict[str, Any]) -> None:
    write_json_atomic(out_dir / "timing-history.json", history, root=out_dir)
    write_json_atomic(
        out_dir / "status.json",
        {
            "schema_version": SCHEMA_VERSION,
            "tool": TOOL,
            "history_id": history["history_id"],
            "status": history["status"],
            "record_count": history["record_count"],
            "blocked_count": history["blocked_count"],
            "source_hashes": history["source_hashes"],
        },
        root=out_dir,
    )
    write_text_atomic(out_dir / "timing-history.md", render_markdown(history), root=out_dir)


def run_build(*, timing_root: Path, out_dir: Path) -> dict[str, Any]:
    timing_root = resolve_timing_root(timing_root)
    out_dir = resolve_out(out_dir)
    prepare_out_dir(out_dir, out_dir.name, source=timing_root)
    records = load_timing_files(timing_root)
    history = build_history(history_id=out_dir.name, records=records, source=rel(timing_root))
    write_history(out_dir, history)
    return history


def fixture_records(fixture: dict[str, Any]) -> list[dict[str, Any]]:
    fixture_id = str(fixture.get("id", "fixture"))
    timings = fixture.get("timings")
    if not isinstance(timings, list):
        raise ReleaseTimingHistoryError("ERR_RELEASE_TIMING_HISTORY_MANIFEST_INVALID", "fixture timings must be a list", fixture_id=fixture_id)
    return [validate_timing(timing, fixture_id=fixture_id) for timing in timings if isinstance(timing, dict)]


def run_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    fixtures = manifest.get("fixtures")
    if not isinstance(fixtures, list):
        raise ReleaseTimingHistoryError("ERR_RELEASE_TIMING_HISTORY_MANIFEST_INVALID", "manifest fixtures must be a list", path=manifest_path)
    suite_id = str(manifest.get("suite_id", "v72-release-timing-history"))
    out_dir = resolve_out(out_dir)
    prepare_out_dir(out_dir, out_dir.name, source=manifest_path)
    records = []
    for fixture in fixtures:
        if not isinstance(fixture, dict):
            raise ReleaseTimingHistoryError("ERR_RELEASE_TIMING_HISTORY_MANIFEST_INVALID", "fixture must be an object", path=manifest_path)
        fixture_id = str(fixture.get("id", "fixture"))
        fixture_out = out_dir / fixture_id
        try:
            history = build_history(history_id=fixture_id, records=fixture_records(fixture), source=fixture_id)
            prepare_out_dir(fixture_out, fixture_id, source=manifest_path)
            write_history(fixture_out, history)
            expected_status = fixture.get("expected_status")
            status = "pass" if expected_status in (None, history["status"]) else "fail"
            error = None if status == "pass" else f"expected status {expected_status}, got {history['status']}"
            history_status = history["status"]
            record_count = history["record_count"]
        except ReleaseTimingHistoryError as exc:
            expected_error = fixture.get("expected_error")
            status = "pass" if expected_error == exc.code else "fail"
            error = None if status == "pass" else exc.code
            history_status = "error"
            record_count = 0
        records.append(
            {
                "id": fixture_id,
                "required": bool(fixture.get("required", True)),
                "status": status,
                "history_status": history_status,
                "record_count": record_count,
                "error": error,
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
        raise ReleaseTimingHistoryError("ERR_RELEASE_TIMING_HISTORY_FIXTURE_FAILED", "required timing history fixture failed", path=manifest_path)
    return summary


def sample_timing(timing_id: str, status: str, duration_ms: int, measured_count: int) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": "dwm_release_timing.py",
        "timing_id": timing_id,
        "status": status,
        "mode": "measure" if measured_count else "plan",
        "command_count": 1,
        "measured_count": measured_count,
        "commands": [
            {
                "duration_ms": duration_ms if measured_count else None,
                "returncode": 0 if status == "release-timing-recorded" else None,
                "timed_out": status == "release-timing-blocked",
            }
        ],
    }


def self_test() -> None:
    history = build_history(
        history_id="self-test-history",
        records=[
            validate_timing(sample_timing("b-run", "release-timing-recorded", 20, 1)),
            validate_timing(sample_timing("a-run", "release-timing-planned", 0, 0)),
            validate_timing(sample_timing("c-run", "release-timing-blocked", 10, 1)),
        ],
        source="self-test",
    )
    if history["record_count"] != 3 or history["blocked_count"] != 1:
        raise ReleaseTimingHistoryError("ERR_RELEASE_TIMING_HISTORY_SELF_TEST_FAILED", "history counts should be deterministic")
    if [record["timing_id"] for record in history["records"]] != ["a-run", "b-run", "c-run"]:
        raise ReleaseTimingHistoryError("ERR_RELEASE_TIMING_HISTORY_SELF_TEST_FAILED", "history records should be sorted")
    try:
        build_history(
            history_id="duplicate",
            records=[
                validate_timing(sample_timing("same", "release-timing-recorded", 1, 1)),
                validate_timing(sample_timing("same", "release-timing-recorded", 2, 1)),
            ],
            source="self-test",
        )
    except ReleaseTimingHistoryError as exc:
        if exc.code != "ERR_RELEASE_TIMING_HISTORY_DUPLICATE_ID":
            raise
    else:
        raise ReleaseTimingHistoryError("ERR_RELEASE_TIMING_HISTORY_SELF_TEST_FAILED", "duplicate timing ids should be blocked")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="run V72 release timing history self-test")
    parser.add_argument("--manifest", type=Path, help="run timing history fixtures from a manifest")
    parser.add_argument("--out", type=Path, help="output directory under out/release-timing-history")
    subparsers = parser.add_subparsers(dest="command")
    build_parser = subparsers.add_parser("build", help="build a history from release timing artifacts")
    build_parser.add_argument("--timing-root", type=Path, default=TIMING_ROOT)
    build_parser.add_argument("--out", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        if args.self_test:
            self_test()
            print("release timing history self-test: pass")
            return
        if args.manifest:
            if args.out is None:
                raise ReleaseTimingHistoryError("ERR_RELEASE_TIMING_HISTORY_ARGS_INVALID", "--manifest requires --out")
            summary = run_manifest(args.manifest, args.out)
            print(json.dumps(summary, sort_keys=True))
            return
        if args.command == "build":
            history = run_build(timing_root=args.timing_root, out_dir=args.out)
            print(json.dumps({"status": history["status"], "history_id": history["history_id"], "record_count": history["record_count"]}, sort_keys=True))
            return
        raise ReleaseTimingHistoryError("ERR_RELEASE_TIMING_HISTORY_ARGS_INVALID", "choose --self-test, --manifest, or build")
    except ReleaseTimingHistoryError as exc:
        print(json.dumps({"status": "error", "error": exc.to_record()}, sort_keys=True), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
