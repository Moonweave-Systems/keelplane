#!/usr/bin/env python3
"""V41 benchmark snapshot series builder."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from compile_workflow import canonical_hash, canonical_json_text, read_json, write_json_atomic  # noqa: E402
from dwm_benchmark_history import HISTORY_ROOT, build_history_from_snapshots  # noqa: E402
from dwm_benchmark_snapshot import SNAPSHOT_ROOT, make_report_dir, record_snapshot  # noqa: E402


TOOL = "dwm_benchmark_series.py"
SCHEMA_VERSION = "1.0"
SERIES_VERSION = "41.0.0"
SERIES_ROOT = ROOT / "out" / "benchmark-series"
SENTINEL = ".dwm_benchmark_series-owned.json"


class BenchmarkSeriesError(ValueError):
    """Structured V41 benchmark series failure."""

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
        raise BenchmarkSeriesError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise BenchmarkSeriesError(code, "path contains a symlink", path=current)


def resolve_series_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_BENCHMARK_SERIES_PATH_UNSAFE", message="benchmark series output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = SERIES_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise BenchmarkSeriesError("ERR_BENCHMARK_SERIES_PATH_UNSAFE", f"benchmark series output must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise BenchmarkSeriesError("ERR_BENCHMARK_SERIES_PATH_UNSAFE", "benchmark series output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_BENCHMARK_SERIES_PATH_SYMLINK")
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


def prepare_out_dir(path: Path, series_id: str, *, source: Path) -> None:
    if path.exists():
        if path.is_symlink():
            raise BenchmarkSeriesError("ERR_BENCHMARK_SERIES_PATH_SYMLINK", "benchmark series output is a symlink", path=path)
        if not path.is_dir():
            raise BenchmarkSeriesError("ERR_BENCHMARK_SERIES_PATH_UNSAFE", "benchmark series output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("series_id") != series_id:
            raise BenchmarkSeriesError("ERR_BENCHMARK_SERIES_PATH_UNSAFE", "existing benchmark series output is not series-owned", path=path)
        shutil.rmtree(path)
    SERIES_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(
        path / SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "series_version": SERIES_VERSION,
            "series_id": series_id,
            "source_path": rel(source),
            "created_at": now_utc(),
        },
        root=path,
    )


def snapshot_dirs_from_root(snapshot_root: Path) -> list[Path]:
    if not snapshot_root.is_dir() or snapshot_root.is_symlink():
        raise BenchmarkSeriesError("ERR_BENCHMARK_SERIES_SNAPSHOT_ROOT_INVALID", "snapshot root is not a directory", path=snapshot_root)
    dirs = [path for path in sorted(snapshot_root.iterdir()) if path.is_dir() and not path.is_symlink() and (path / "snapshot.json").is_file()]
    if not dirs:
        raise BenchmarkSeriesError("ERR_BENCHMARK_SERIES_INSUFFICIENT_SNAPSHOTS", "no benchmark snapshots found", path=snapshot_root)
    return dirs


def load_snapshot(snapshot_dir: Path) -> dict[str, Any]:
    snapshot_path = snapshot_dir / "snapshot.json"
    status_path = snapshot_dir / "status.json"
    if not snapshot_path.is_file() or snapshot_path.is_symlink() or not status_path.is_file() or status_path.is_symlink():
        raise BenchmarkSeriesError("ERR_BENCHMARK_SERIES_ARTIFACT_MISSING", "snapshot artifacts are missing", path=snapshot_dir)
    snapshot = read_json(snapshot_path)
    status = read_json(status_path)
    if snapshot != status or snapshot.get("status") != "snapshot-recorded":
        raise BenchmarkSeriesError("ERR_BENCHMARK_SERIES_STALE_SNAPSHOT", "snapshot status and artifact do not match", path=snapshot_dir)
    if snapshot.get("source_kind") != "release":
        raise BenchmarkSeriesError("ERR_BENCHMARK_SERIES_SOURCE_NOT_RELEASE", "series accepts only release snapshots", path=snapshot_dir)
    if not snapshot.get("release_id"):
        raise BenchmarkSeriesError("ERR_BENCHMARK_SERIES_RELEASE_ID_MISSING", "snapshot release_id is missing", path=snapshot_dir)
    report_hash = snapshot.get("source_hashes", {}).get("report")
    if not isinstance(report_hash, str) or not report_hash:
        raise BenchmarkSeriesError("ERR_BENCHMARK_SERIES_HASH_MISMATCH", "snapshot report hash is missing", path=snapshot_dir)
    return snapshot


def sort_snapshot_dirs(snapshot_dirs: list[Path]) -> list[Path]:
    loaded = [(load_snapshot(path), path) for path in snapshot_dirs]
    release_ids = [str(snapshot["release_id"]) for snapshot, _ in loaded]
    if len(set(release_ids)) != len(release_ids):
        raise BenchmarkSeriesError("ERR_BENCHMARK_SERIES_DUPLICATE_RELEASE", "snapshot release ids must be unique")
    report_hashes = [str(snapshot["source_hashes"]["report"]) for snapshot, _ in loaded]
    if len(set(report_hashes)) != len(report_hashes):
        raise BenchmarkSeriesError("ERR_BENCHMARK_SERIES_DUPLICATE_REPORT", "snapshot report hashes must be unique")
    return [path for _, path in sorted(loaded, key=lambda item: str(item[0]["release_id"]))]


def build_series(snapshot_dirs: list[Path], out_dir: Path, *, series_id: str, min_snapshots: int = 3) -> dict[str, Any]:
    if len(snapshot_dirs) < min_snapshots:
        raise BenchmarkSeriesError("ERR_BENCHMARK_SERIES_INSUFFICIENT_SNAPSHOTS", "not enough snapshots for a benchmark series")
    ordered = sort_snapshot_dirs(snapshot_dirs)
    prepare_out_dir(out_dir, series_id, source=ordered[0])
    history_id = f"{out_dir.parent.name}-{series_id}-history"
    history_dir = HISTORY_ROOT / history_id
    history = build_history_from_snapshots(ordered, history_dir, history_id=history_dir.name)
    snapshot_hashes = [canonical_hash(load_snapshot(path)) for path in ordered]
    series = {
        "status": "series-recorded",
        "series_id": series_id,
        "source": "benchmark release snapshots",
        "snapshot_paths": [rel(path) for path in ordered],
        "history_path": rel(history_dir),
        "release_ids": [entry["label"] for entry in history["entries"]],
        "trend_metrics": history["trend_metrics"],
        "source_hashes": {
            "history": canonical_hash(history),
            "snapshots": snapshot_hashes,
            **history.get("source_hashes", {}),
        },
    }
    write_json_atomic(out_dir / "series.json", series, root=out_dir)
    write_json_atomic(out_dir / "status.json", series, root=out_dir)
    (out_dir / "README-snippet.md").write_text(f"History: `{series['history_path']}`\n")
    return series


def make_snapshot_dir(base_name: str, release_id: str, *, publish_claim: bool = True, failed: bool = False) -> Path:
    report_dir = make_report_dir(f"{base_name}-{release_id}", publish_claim=publish_claim and not failed, failed=failed)
    snapshot_dir = SNAPSHOT_ROOT / f"{base_name}-{release_id}-snapshot"
    record_snapshot(report_dir, snapshot_dir, snapshot_id=snapshot_dir.name, release_id=release_id, git_commit_value=f"{release_id}-commit")
    return snapshot_dir


def blocked_fixture_status(kind: str, fixture: dict[str, Any], suite_id: str) -> dict[str, Any]:
    try:
        if kind == "insufficient-snapshots":
            snapshots = [
                make_snapshot_dir(f"{suite_id}-insufficient", "r1", failed=True),
                make_snapshot_dir(f"{suite_id}-insufficient", "r2"),
            ]
            build_series(snapshots, SERIES_ROOT / f"{suite_id}-insufficient", series_id=f"{suite_id}-insufficient")
        elif kind == "duplicate-release":
            first = make_snapshot_dir(f"{suite_id}-duplicate-release-a", "r1", failed=True)
            second = make_snapshot_dir(f"{suite_id}-duplicate-release-b", "r1")
            third = make_snapshot_dir(f"{suite_id}-duplicate-release-c", "r3")
            build_series([first, second, third], SERIES_ROOT / f"{suite_id}-duplicate-release", series_id=f"{suite_id}-duplicate-release")
        elif kind == "duplicate-report":
            first = make_snapshot_dir(f"{suite_id}-duplicate-report-a", "r1", failed=True)
            second = make_snapshot_dir(f"{suite_id}-duplicate-report-b", "r2")
            third = make_snapshot_dir(f"{suite_id}-duplicate-report-c", "r3")
            second_status = read_json(second / "status.json")
            second_status["source_hashes"]["report"] = read_json(first / "status.json")["source_hashes"]["report"]
            write_json_atomic(second / "snapshot.json", second_status, root=second)
            write_json_atomic(second / "status.json", second_status, root=second)
            build_series([first, second, third], SERIES_ROOT / f"{suite_id}-duplicate-report", series_id=f"{suite_id}-duplicate-report")
        elif kind == "stale-snapshot":
            first = make_snapshot_dir(f"{suite_id}-stale-a", "r1", failed=True)
            second = make_snapshot_dir(f"{suite_id}-stale-b", "r2")
            third = make_snapshot_dir(f"{suite_id}-stale-c", "r3")
            status = read_json(second / "status.json")
            status["release_id"] = "r2-stale"
            write_json_atomic(second / "status.json", status, root=second)
            build_series([first, second, third], SERIES_ROOT / f"{suite_id}-stale", series_id=f"{suite_id}-stale")
        elif kind == "source-not-release":
            first = make_snapshot_dir(f"{suite_id}-source-a", "r1", failed=True)
            second = make_snapshot_dir(f"{suite_id}-source-b", "r2")
            third = make_snapshot_dir(f"{suite_id}-source-c", "r3")
            status = read_json(second / "status.json")
            status["source_kind"] = "fixture"
            write_json_atomic(second / "snapshot.json", status, root=second)
            write_json_atomic(second / "status.json", status, root=second)
            build_series([first, second, third], SERIES_ROOT / f"{suite_id}-source", series_id=f"{suite_id}-source")
        else:
            raise BenchmarkSeriesError("ERR_BENCHMARK_SERIES_FIXTURE_FAILED", f"unknown blocked fixture kind: {kind}")
    except BenchmarkSeriesError as exc:
        if fixture.get("expected_error") != exc.code:
            raise
        return {"status": "blocked", "error": exc.to_record()}
    raise BenchmarkSeriesError("ERR_BENCHMARK_SERIES_FIXTURE_FAILED", f"{kind} unexpectedly passed")


def run_fixture(fixture: dict[str, Any], suite_dir: Path) -> dict[str, Any]:
    fixture_id = fixture["id"]
    try:
        kind = fixture["kind"]
        if kind == "series-recorded":
            snapshots = [
                make_snapshot_dir(f"{suite_dir.name}-{fixture_id}", "r1", failed=True),
                make_snapshot_dir(f"{suite_dir.name}-{fixture_id}", "r2", failed=True),
                make_snapshot_dir(f"{suite_dir.name}-{fixture_id}", "r3"),
            ]
            status = build_series(snapshots, suite_dir / fixture_id, series_id=fixture_id)
        elif kind == "series-from-root":
            root = SNAPSHOT_ROOT / f"{suite_dir.name}-{fixture_id}-root"
            if root.exists():
                shutil.rmtree(root)
            root.mkdir(parents=True)
            for release_id, failed in [("r1", True), ("r2", True), ("r3", False)]:
                source = make_snapshot_dir(f"{suite_dir.name}-{fixture_id}", release_id, failed=failed)
                shutil.copytree(source, root / source.name)
            status = build_series(snapshot_dirs_from_root(root), suite_dir / fixture_id, series_id=fixture_id)
        elif kind in {"insufficient-snapshots", "duplicate-release", "duplicate-report", "stale-snapshot", "source-not-release"}:
            status = blocked_fixture_status(kind, fixture, suite_dir.name)
        else:
            raise BenchmarkSeriesError("ERR_BENCHMARK_SERIES_FIXTURE_FAILED", f"unknown fixture kind: {kind}")
        expected_status = fixture.get("expected_status")
        if expected_status is not None and status.get("status") != expected_status:
            raise BenchmarkSeriesError("ERR_BENCHMARK_SERIES_FIXTURE_FAILED", f"expected status {expected_status}, got {status.get('status')}")
        expected_error = fixture.get("expected_error")
        actual_error = status.get("error", {}).get("code") if isinstance(status.get("error"), dict) else None
        if expected_error is not None and actual_error != expected_error:
            raise BenchmarkSeriesError("ERR_BENCHMARK_SERIES_FIXTURE_FAILED", f"expected error {expected_error}, got {actual_error}")
        return {"id": fixture_id, "status": "pass", "observed_status": status.get("status"), "required": fixture.get("required", True)}
    except BenchmarkSeriesError as exc:
        record = exc.to_record()
        record["fixture_id"] = fixture_id
        return {"id": fixture_id, "status": "fail", "required": fixture.get("required", True), "error": record}


def evaluate_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    suite_id = Path(out_dir).name
    suite_dir = resolve_series_out(out_dir)
    if suite_dir.exists():
        sentinel = read_sentinel(suite_dir)
        if sentinel is None or sentinel.get("series_id") != suite_id:
            raise BenchmarkSeriesError("ERR_BENCHMARK_SERIES_PATH_UNSAFE", "existing benchmark series suite is not series-owned", path=suite_dir)
        shutil.rmtree(suite_dir)
    prepare_out_dir(suite_dir, suite_id, source=manifest_path)
    fixtures = manifest["fixtures"]
    required_ids = set(manifest["required_fixture_ids"])
    results = [run_fixture(fixture, suite_dir) for fixture in fixtures]
    passed = sum(1 for item in results if item["status"] == "pass")
    failures = [item["error"] for item in results if item["status"] == "fail"]
    required_passed = sum(1 for item in results if item["id"] in required_ids and item["status"] == "pass")
    required_failed = [item for item in results if item["id"] in required_ids and item["status"] == "fail"]
    summary = {
        "suite_id": suite_id,
        "fixture_count": len(fixtures),
        "required_fixture_count": len(required_ids),
        "required_passed": required_passed,
        "passed": passed,
        "failed": len(failures),
        "skipped": 0,
        "decision": "keep" if not required_failed and required_ids <= {item["id"] for item in results} else "kill",
        "failures": failures,
        "fixtures": results,
        "source_hashes": {"manifest": canonical_hash(manifest)},
    }
    write_json_atomic(suite_dir / "summary.json", summary, root=suite_dir)
    if summary["decision"] != "keep":
        raise BenchmarkSeriesError("ERR_BENCHMARK_SERIES_FIXTURE_FAILED", "manifest decision is kill", path=manifest_path)
    return summary


def self_test() -> None:
    SERIES_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dwm-benchmark-series-self-test-", dir=SERIES_ROOT) as tmp:
        summary = evaluate_manifest(ROOT / "fixtures" / "v41" / "manifest.json", Path(tmp) / "benchmark-series-self-test")
    if summary["decision"] != "keep":
        raise BenchmarkSeriesError("ERR_BENCHMARK_SERIES_FIXTURE_FAILED", "benchmark series self-test manifest did not keep")
    print("dwm_benchmark_series self-test: pass")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", choices=["build"])
    parser.add_argument("--manifest")
    parser.add_argument("--min-snapshots", type=int, default=3)
    parser.add_argument("--out")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--snapshot", action="append")
    parser.add_argument("--snapshot-root")
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
        elif args.manifest:
            if not args.out:
                raise BenchmarkSeriesError("ERR_BENCHMARK_SERIES_PATH_UNSAFE", "--manifest requires --out")
            summary = evaluate_manifest(Path(args.manifest), Path(args.out))
            print(canonical_json_text({key: summary[key] for key in ["suite_id", "fixture_count", "required_fixture_count", "required_passed", "passed", "failed", "skipped", "decision"]}))
        elif args.command == "build":
            if not args.out:
                raise BenchmarkSeriesError("ERR_BENCHMARK_SERIES_PATH_UNSAFE", "build requires --out")
            if bool(args.snapshot) == bool(args.snapshot_root):
                raise BenchmarkSeriesError("ERR_BENCHMARK_SERIES_PATH_UNSAFE", "build requires exactly one of --snapshot or --snapshot-root")
            snapshots = [Path(path) for path in args.snapshot] if args.snapshot else snapshot_dirs_from_root(Path(args.snapshot_root))
            status = build_series(snapshots, resolve_series_out(args.out), series_id=Path(args.out).name, min_snapshots=args.min_snapshots)
            print(canonical_json_text(status))
        else:
            parser.error("expected --self-test, --manifest, or build")
    except BenchmarkSeriesError as exc:
        print(canonical_json_text(exc.to_record()), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
