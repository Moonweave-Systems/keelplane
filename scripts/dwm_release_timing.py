#!/usr/bin/env python3
"""V71 release command timing planner and bounded measurement recorder."""

from __future__ import annotations

import argparse
import json
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from compile_workflow import canonical_hash, read_json, write_json_atomic, write_text_atomic  # noqa: E402
from dwm import RELEASE_COMMANDS  # noqa: E402


TOOL = "dwm_release_timing.py"
SCHEMA_VERSION = "1.0"
TIMING_VERSION = "71.0.0"
TIMING_ROOT = ROOT / "out" / "release-timing"
SENTINEL = ".dwm_release_timing-owned.json"
DEFAULT_TIMEOUT_SECONDS = 30


class ReleaseTimingError(ValueError):
    """Structured V71 release timing failure."""

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
        raise ReleaseTimingError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise ReleaseTimingError(code, "path contains a symlink", path=current)


def resolve_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_RELEASE_TIMING_PATH_UNSAFE", message="timing output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = TIMING_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ReleaseTimingError("ERR_RELEASE_TIMING_PATH_UNSAFE", f"timing output must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise ReleaseTimingError("ERR_RELEASE_TIMING_PATH_UNSAFE", "timing output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_RELEASE_TIMING_PATH_SYMLINK")
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


def prepare_out_dir(path: Path, timing_id: str, *, source: Path | str) -> None:
    if path.exists():
        if path.is_symlink():
            raise ReleaseTimingError("ERR_RELEASE_TIMING_PATH_SYMLINK", "timing output is a symlink", path=path)
        if not path.is_dir():
            raise ReleaseTimingError("ERR_RELEASE_TIMING_PATH_UNSAFE", "timing output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("timing_id") != timing_id:
            raise ReleaseTimingError("ERR_RELEASE_TIMING_PATH_UNSAFE", "existing timing output is not timing-owned", path=path)
        shutil.rmtree(path)
    TIMING_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(
        path / SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "timing_version": TIMING_VERSION,
            "timing_id": timing_id,
            "source_path": str(source),
            "created_at": now_utc(),
        },
        root=path,
    )


def normalize_command(command: Any, *, fixture_id: str | None = None) -> list[str]:
    if isinstance(command, str):
        parts = shlex.split(command)
    elif isinstance(command, list) and all(isinstance(item, str) for item in command):
        parts = list(command)
    else:
        raise ReleaseTimingError("ERR_RELEASE_TIMING_COMMAND_INVALID", "command must be a string or string array", fixture_id=fixture_id)
    return [sys.executable if item == "{python}" else item for item in parts]


def release_command_list(limit: int | None = None) -> list[list[str]]:
    commands = [normalize_command(command) for command in RELEASE_COMMANDS]
    if limit is not None:
        return commands[:limit]
    return commands


def manifest_commands(fixture: dict[str, Any]) -> list[list[str]]:
    fixture_id = str(fixture.get("id", "fixture"))
    if fixture.get("source") == "release_commands":
        limit = fixture.get("limit")
        if limit is not None and (not isinstance(limit, int) or limit < 0):
            raise ReleaseTimingError("ERR_RELEASE_TIMING_MANIFEST_INVALID", "limit must be a non-negative integer", fixture_id=fixture_id)
        return release_command_list(limit)
    raw_commands = fixture.get("commands")
    if not isinstance(raw_commands, list):
        raise ReleaseTimingError("ERR_RELEASE_TIMING_MANIFEST_INVALID", "fixture must define commands or source=release_commands", fixture_id=fixture_id)
    return [normalize_command(command, fixture_id=fixture_id) for command in raw_commands]


def command_record(index: int, command: list[str], *, timeout_seconds: int, plan_only: bool) -> dict[str, Any]:
    record: dict[str, Any] = {
        "index": index,
        "command": command,
        "command_text": shlex.join(command),
        "command_hash": canonical_hash(command),
        "timeout_seconds": timeout_seconds,
        "plan_only": plan_only,
    }
    if plan_only:
        record.update(
            {
                "skipped": True,
                "duration_ms": None,
                "returncode": None,
                "timed_out": False,
                "stdout_hash": None,
                "stderr_hash": None,
            }
        )
        return record

    started = time.perf_counter()
    try:
        completed = subprocess.run(command, cwd=ROOT, check=False, text=True, capture_output=True, timeout=timeout_seconds)
        duration_ms = int(round((time.perf_counter() - started) * 1000))
        record.update(
            {
                "skipped": False,
                "duration_ms": duration_ms,
                "returncode": completed.returncode,
                "timed_out": False,
                "stdout_hash": canonical_hash(completed.stdout),
                "stderr_hash": canonical_hash(completed.stderr),
            }
        )
    except subprocess.TimeoutExpired as exc:
        duration_ms = int(round((time.perf_counter() - started) * 1000))
        record.update(
            {
                "skipped": False,
                "duration_ms": duration_ms,
                "returncode": None,
                "timed_out": True,
                "stdout_hash": canonical_hash(exc.stdout or ""),
                "stderr_hash": canonical_hash(exc.stderr or ""),
            }
        )
    return record


def timing_status(records: list[dict[str, Any]], *, plan_only: bool) -> str:
    if plan_only:
        return "release-timing-planned"
    blocked = any(record.get("timed_out") or record.get("returncode") not in (0, None) for record in records)
    return "release-timing-blocked" if blocked else "release-timing-recorded"


def source_hashes(commands: list[list[str]], *, source: str) -> dict[str, str]:
    hashes = {"commands": canonical_hash(commands), "source": canonical_hash(source)}
    if source == "release_commands":
        hashes["scripts/dwm.py:RELEASE_COMMANDS"] = canonical_hash(RELEASE_COMMANDS)
    return hashes


def build_timing(
    *,
    timing_id: str,
    commands: list[list[str]],
    mode: str,
    timeout_seconds: int,
    source: str,
) -> dict[str, Any]:
    if mode not in {"plan", "measure"}:
        raise ReleaseTimingError("ERR_RELEASE_TIMING_MODE_INVALID", "mode must be plan or measure")
    plan_only = mode == "plan"
    records = [
        command_record(index, command, timeout_seconds=timeout_seconds, plan_only=plan_only)
        for index, command in enumerate(commands, 1)
    ]
    measured = [record for record in records if not record.get("skipped")]
    slowest = sorted(
        [record for record in measured if isinstance(record.get("duration_ms"), int)],
        key=lambda record: int(record["duration_ms"]),
        reverse=True,
    )[:5]
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "timing_version": TIMING_VERSION,
        "timing_id": timing_id,
        "status": timing_status(records, plan_only=plan_only),
        "mode": mode,
        "command_count": len(records),
        "measured_count": len(measured),
        "timeout_seconds": timeout_seconds,
        "commands": records,
        "slowest": slowest,
        "source_hashes": source_hashes(commands, source=source),
    }


def render_markdown(timing: dict[str, Any]) -> str:
    lines = [
        f"# Release Timing {timing['timing_id']}",
        "",
        f"- Status: `{timing['status']}`",
        f"- Mode: `{timing['mode']}`",
        f"- Commands: `{timing['command_count']}`",
        f"- Measured: `{timing['measured_count']}`",
        f"- Timeout seconds: `{timing['timeout_seconds']}`",
        "",
        "## Commands",
        "",
        "| # | Status | Duration ms | Command |",
        "| --- | --- | ---: | --- |",
    ]
    for record in timing["commands"]:
        if record["plan_only"]:
            status = "planned"
        elif record["timed_out"]:
            status = "timed-out"
        elif record["returncode"] == 0:
            status = "ok"
        else:
            status = f"exit-{record['returncode']}"
        duration = "" if record["duration_ms"] is None else str(record["duration_ms"])
        lines.append(f"| {record['index']} | {status} | {duration} | `{record['command_text']}` |")
    lines.append("")
    return "\n".join(lines)


def write_timing(out_dir: Path, timing: dict[str, Any]) -> None:
    write_json_atomic(out_dir / "release-timing.json", timing, root=out_dir)
    write_json_atomic(
        out_dir / "status.json",
        {
            "schema_version": SCHEMA_VERSION,
            "tool": TOOL,
            "timing_id": timing["timing_id"],
            "status": timing["status"],
            "command_count": timing["command_count"],
            "measured_count": timing["measured_count"],
            "source_hashes": timing["source_hashes"],
        },
        root=out_dir,
    )
    write_text_atomic(out_dir / "release-timing.md", render_markdown(timing), root=out_dir)


def run_single(
    *,
    timing_id: str,
    out_dir: Path,
    commands: list[list[str]],
    mode: str,
    timeout_seconds: int,
    source: str,
) -> dict[str, Any]:
    prepare_out_dir(out_dir, timing_id, source=source)
    timing = build_timing(
        timing_id=timing_id,
        commands=commands,
        mode=mode,
        timeout_seconds=timeout_seconds,
        source=source,
    )
    write_timing(out_dir, timing)
    return timing


def run_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    fixtures = manifest.get("fixtures")
    if not isinstance(fixtures, list):
        raise ReleaseTimingError("ERR_RELEASE_TIMING_MANIFEST_INVALID", "manifest fixtures must be a list", path=manifest_path)
    suite_id = str(manifest.get("suite_id", "v71-release-timing"))
    out_dir = resolve_out(out_dir)
    prepare_out_dir(out_dir, out_dir.name, source=manifest_path)
    records = []
    for fixture in fixtures:
        if not isinstance(fixture, dict):
            raise ReleaseTimingError("ERR_RELEASE_TIMING_MANIFEST_INVALID", "fixture must be an object", path=manifest_path)
        fixture_id = str(fixture.get("id", "fixture"))
        mode = str(fixture.get("mode", "plan"))
        timeout_seconds = int(fixture.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS))
        commands = manifest_commands(fixture)
        source = str(fixture.get("source", "manifest"))
        fixture_out = out_dir / fixture_id
        timing = run_single(
            timing_id=fixture_id,
            out_dir=fixture_out,
            commands=commands,
            mode=mode,
            timeout_seconds=timeout_seconds,
            source=source,
        )
        expected_status = fixture.get("expected_status")
        status = "pass" if expected_status in (None, timing["status"]) else "fail"
        error = None if status == "pass" else f"expected status {expected_status}, got {timing['status']}"
        records.append(
            {
                "id": fixture_id,
                "required": bool(fixture.get("required", True)),
                "status": status,
                "timing_status": timing["status"],
                "command_count": timing["command_count"],
                "measured_count": timing["measured_count"],
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
        raise ReleaseTimingError("ERR_RELEASE_TIMING_FIXTURE_FAILED", "required timing fixture failed", path=manifest_path)
    return summary


def self_test() -> None:
    plan = build_timing(
        timing_id="self-test-plan",
        commands=release_command_list(2),
        mode="plan",
        timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
        source="release_commands",
    )
    if plan["status"] != "release-timing-planned" or plan["measured_count"] != 0:
        raise ReleaseTimingError("ERR_RELEASE_TIMING_SELF_TEST_FAILED", "plan mode should not execute commands")
    measured = build_timing(
        timing_id="self-test-measure",
        commands=[[sys.executable, "-c", "print('ok')"]],
        mode="measure",
        timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
        source="self-test",
    )
    if measured["status"] != "release-timing-recorded" or measured["measured_count"] != 1:
        raise ReleaseTimingError("ERR_RELEASE_TIMING_SELF_TEST_FAILED", "measure mode should record a passing command")
    timed_out = build_timing(
        timing_id="self-test-timeout",
        commands=[[sys.executable, "-c", "import time; time.sleep(2)"]],
        mode="measure",
        timeout_seconds=1,
        source="self-test",
    )
    if timed_out["status"] != "release-timing-blocked" or timed_out["commands"][0]["timed_out"] is not True:
        raise ReleaseTimingError("ERR_RELEASE_TIMING_SELF_TEST_FAILED", "timeout should be recorded as blocked")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="run V71 release timing self-test")
    parser.add_argument("--manifest", type=Path, help="run timing fixtures from a manifest")
    parser.add_argument("--out", type=Path, help="output directory under out/release-timing")
    subparsers = parser.add_subparsers(dest="command")
    plan_parser = subparsers.add_parser("plan", help="write a plan-only release command inventory")
    plan_parser.add_argument("--out", type=Path, required=True)
    plan_parser.add_argument("--limit", type=int)
    measure_parser = subparsers.add_parser("measure", help="measure a bounded release command prefix")
    measure_parser.add_argument("--out", type=Path, required=True)
    measure_parser.add_argument("--limit", type=int, default=3)
    measure_parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        if args.self_test:
            self_test()
            print("release timing self-test: pass")
            return
        if args.manifest:
            if args.out is None:
                raise ReleaseTimingError("ERR_RELEASE_TIMING_ARGS_INVALID", "--manifest requires --out")
            summary = run_manifest(args.manifest, args.out)
            print(json.dumps(summary, sort_keys=True))
            return
        if args.command == "plan":
            out_dir = resolve_out(args.out)
            timing = run_single(
                timing_id=out_dir.name,
                out_dir=out_dir,
                commands=release_command_list(args.limit),
                mode="plan",
                timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
                source="release_commands",
            )
            print(json.dumps({"status": timing["status"], "timing_id": timing["timing_id"], "command_count": timing["command_count"]}, sort_keys=True))
            return
        if args.command == "measure":
            out_dir = resolve_out(args.out)
            timing = run_single(
                timing_id=out_dir.name,
                out_dir=out_dir,
                commands=release_command_list(args.limit),
                mode="measure",
                timeout_seconds=args.timeout_seconds,
                source="release_commands",
            )
            print(json.dumps({"status": timing["status"], "timing_id": timing["timing_id"], "measured_count": timing["measured_count"]}, sort_keys=True))
            return
        raise ReleaseTimingError("ERR_RELEASE_TIMING_ARGS_INVALID", "choose --self-test, --manifest, plan, or measure")
    except ReleaseTimingError as exc:
        print(json.dumps({"status": "error", "error": exc.to_record()}, sort_keys=True), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
