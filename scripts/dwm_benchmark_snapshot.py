#!/usr/bin/env python3
"""V40 release benchmark snapshot recorder."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from compile_workflow import canonical_hash, canonical_json_text, read_json, write_json_atomic  # noqa: E402
from dwm_live_report import REPORT_ROOT, make_review_dir, publish_report  # noqa: E402


TOOL = "dwm_benchmark_snapshot.py"
SCHEMA_VERSION = "1.0"
SNAPSHOT_VERSION = "40.0.0"
SNAPSHOT_ROOT = ROOT / "out" / "benchmark-snapshots"
SENTINEL = ".dwm_benchmark_snapshot-owned.json"


class BenchmarkSnapshotError(ValueError):
    """Structured V40 benchmark snapshot failure."""

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
        raise BenchmarkSnapshotError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise BenchmarkSnapshotError(code, "path contains a symlink", path=current)


def resolve_snapshot_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_BENCHMARK_SNAPSHOT_PATH_UNSAFE", message="benchmark snapshot output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = SNAPSHOT_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise BenchmarkSnapshotError("ERR_BENCHMARK_SNAPSHOT_PATH_UNSAFE", f"benchmark snapshot output must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise BenchmarkSnapshotError("ERR_BENCHMARK_SNAPSHOT_PATH_UNSAFE", "benchmark snapshot output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_BENCHMARK_SNAPSHOT_PATH_SYMLINK")
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


def prepare_out_dir(path: Path, snapshot_id: str, *, source: Path) -> None:
    if path.exists():
        if path.is_symlink():
            raise BenchmarkSnapshotError("ERR_BENCHMARK_SNAPSHOT_PATH_SYMLINK", "benchmark snapshot output is a symlink", path=path)
        if not path.is_dir():
            raise BenchmarkSnapshotError("ERR_BENCHMARK_SNAPSHOT_PATH_UNSAFE", "benchmark snapshot output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("snapshot_id") != snapshot_id:
            raise BenchmarkSnapshotError("ERR_BENCHMARK_SNAPSHOT_PATH_UNSAFE", "existing benchmark snapshot output is not snapshot-owned", path=path)
        shutil.rmtree(path)
    SNAPSHOT_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(
        path / SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "snapshot_version": SNAPSHOT_VERSION,
            "snapshot_id": snapshot_id,
            "source_path": rel(source),
            "created_at": now_utc(),
        },
        root=path,
    )


def git_commit() -> str:
    completed = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if completed.returncode != 0:
        raise BenchmarkSnapshotError("ERR_BENCHMARK_SNAPSHOT_GIT_UNAVAILABLE", "git commit is unavailable")
    return completed.stdout.strip()


def load_report(report_dir: Path) -> dict[str, Any]:
    report_path = report_dir / "report.json"
    status_path = report_dir / "status.json"
    if not report_path.is_file() or report_path.is_symlink() or not status_path.is_file() or status_path.is_symlink():
        raise BenchmarkSnapshotError("ERR_BENCHMARK_SNAPSHOT_ARTIFACT_MISSING", "report artifacts are missing", path=report_dir)
    report = read_json(report_path)
    status = read_json(status_path)
    if report != status:
        raise BenchmarkSnapshotError("ERR_BENCHMARK_SNAPSHOT_STALE_REPORT", "report status and artifact do not match", path=report_dir)
    if report.get("status") != "report-recorded":
        raise BenchmarkSnapshotError("ERR_BENCHMARK_SNAPSHOT_STALE_REPORT", "report is not recorded", path=report_dir)
    return report


def validate_metrics(report: dict[str, Any], *, report_dir: Path) -> dict[str, int]:
    metrics = report.get("graph_metrics")
    required = ["task_count", "pass_count", "failed_task_count", "refuted_count", "unverified_count", "claim_value"]
    if not isinstance(metrics, dict):
        raise BenchmarkSnapshotError("ERR_BENCHMARK_SNAPSHOT_METRICS_INVALID", "report graph_metrics are missing", path=report_dir)
    if any(key not in metrics for key in required):
        raise BenchmarkSnapshotError("ERR_BENCHMARK_SNAPSHOT_METRICS_INVALID", "report graph_metrics are incomplete", path=report_dir)
    normalized: dict[str, int] = {}
    for key in required:
        value = metrics[key]
        if not isinstance(value, int) or value < 0:
            raise BenchmarkSnapshotError("ERR_BENCHMARK_SNAPSHOT_METRICS_INVALID", f"{key} must be a non-negative integer", path=report_dir)
        normalized[key] = value
    if normalized["task_count"] <= 0 or normalized["pass_count"] > normalized["task_count"] or normalized["failed_task_count"] > normalized["task_count"]:
        raise BenchmarkSnapshotError("ERR_BENCHMARK_SNAPSHOT_METRICS_INVALID", "report graph_metrics are internally inconsistent", path=report_dir)
    return normalized


def record_snapshot(
    report_dir: Path,
    out_dir: Path,
    *,
    snapshot_id: str,
    release_id: str,
    expected_report_hash: str | None = None,
    git_commit_value: str | None = None,
) -> dict[str, Any]:
    if not release_id.strip():
        raise BenchmarkSnapshotError("ERR_BENCHMARK_SNAPSHOT_RELEASE_ID_MISSING", "release_id is required")
    report = load_report(report_dir)
    metrics = validate_metrics(report, report_dir=report_dir)
    report_hash = canonical_hash(report)
    if expected_report_hash is not None and expected_report_hash != report_hash:
        raise BenchmarkSnapshotError("ERR_BENCHMARK_SNAPSHOT_STALE_REPORT", "expected report hash does not match current report", path=report_dir)
    prepare_out_dir(out_dir, snapshot_id, source=report_dir)
    snapshot = {
        "status": "snapshot-recorded",
        "snapshot_id": snapshot_id,
        "release_id": release_id,
        "source_kind": "release",
        "report_path": rel(report_dir),
        "git_commit": git_commit_value or git_commit(),
        "benchmark_success_claimed": bool(report.get("benchmark_success_claimed")),
        "conclusion": report.get("conclusion"),
        "graph_metrics": metrics,
        "score_bps": round(10000 * metrics["pass_count"] / metrics["task_count"]),
        "source_hashes": {"report": report_hash},
    }
    write_json_atomic(out_dir / "snapshot.json", snapshot, root=out_dir)
    write_json_atomic(out_dir / "status.json", snapshot, root=out_dir)
    return snapshot


def make_report_dir(base_name: str, *, publish_claim: bool = True, failed: bool = False) -> Path:
    review_dir = make_review_dir(f"{base_name}-review-source", failed=failed, claim_success=publish_claim)
    report_dir = REPORT_ROOT / f"{base_name}-report"
    publish_report(review_dir, report_dir, report_id=report_dir.name, publish_claim=publish_claim and not failed)
    return report_dir


def blocked_fixture_status(kind: str, fixture: dict[str, Any], suite_id: str) -> dict[str, Any]:
    try:
        if kind == "missing-release-id":
            report_dir = make_report_dir(f"{suite_id}-missing-release")
            record_snapshot(report_dir, SNAPSHOT_ROOT / f"{suite_id}-missing-release", snapshot_id=f"{suite_id}-missing-release", release_id="")
        elif kind == "stale-report":
            report_dir = make_report_dir(f"{suite_id}-stale")
            record_snapshot(
                report_dir,
                SNAPSHOT_ROOT / f"{suite_id}-stale",
                snapshot_id=f"{suite_id}-stale",
                release_id="v40-stale",
                expected_report_hash=str(fixture["expected_report_hash"]),
            )
        elif kind == "metrics-invalid":
            report_dir = make_report_dir(f"{suite_id}-metrics-invalid")
            report_path = report_dir / "report.json"
            report = read_json(report_path)
            report["graph_metrics"]["pass_count"] = report["graph_metrics"]["task_count"] + 1
            write_json_atomic(report_path, report, root=report_dir)
            write_json_atomic(report_dir / "status.json", report, root=report_dir)
            record_snapshot(report_dir, SNAPSHOT_ROOT / f"{suite_id}-metrics-invalid", snapshot_id=f"{suite_id}-metrics-invalid", release_id="v40-invalid")
        elif kind == "missing-artifact":
            missing_dir = REPORT_ROOT / f"{suite_id}-missing"
            if missing_dir.exists():
                shutil.rmtree(missing_dir)
            missing_dir.mkdir(parents=True)
            record_snapshot(missing_dir, SNAPSHOT_ROOT / f"{suite_id}-missing", snapshot_id=f"{suite_id}-missing", release_id="v40-missing")
        else:
            raise BenchmarkSnapshotError("ERR_BENCHMARK_SNAPSHOT_FIXTURE_FAILED", f"unknown blocked fixture kind: {kind}")
    except BenchmarkSnapshotError as exc:
        if fixture.get("expected_error") != exc.code:
            raise
        return {"status": "blocked", "error": exc.to_record()}
    raise BenchmarkSnapshotError("ERR_BENCHMARK_SNAPSHOT_FIXTURE_FAILED", f"{kind} unexpectedly passed")


def run_fixture(fixture: dict[str, Any], suite_dir: Path) -> dict[str, Any]:
    fixture_id = fixture["id"]
    try:
        kind = fixture["kind"]
        if kind == "snapshot-recorded":
            report_dir = make_report_dir(f"{suite_dir.name}-{fixture_id}")
            status = record_snapshot(report_dir, suite_dir / fixture_id, snapshot_id=fixture_id, release_id="v40-fixture", git_commit_value="fixture-commit")
        elif kind in {"missing-release-id", "stale-report", "metrics-invalid", "missing-artifact"}:
            status = blocked_fixture_status(kind, fixture, suite_dir.name)
        else:
            raise BenchmarkSnapshotError("ERR_BENCHMARK_SNAPSHOT_FIXTURE_FAILED", f"unknown fixture kind: {kind}")
        expected_status = fixture.get("expected_status")
        if expected_status is not None and status.get("status") != expected_status:
            raise BenchmarkSnapshotError("ERR_BENCHMARK_SNAPSHOT_FIXTURE_FAILED", f"expected status {expected_status}, got {status.get('status')}")
        expected_error = fixture.get("expected_error")
        actual_error = status.get("error", {}).get("code") if isinstance(status.get("error"), dict) else None
        if expected_error is not None and actual_error != expected_error:
            raise BenchmarkSnapshotError("ERR_BENCHMARK_SNAPSHOT_FIXTURE_FAILED", f"expected error {expected_error}, got {actual_error}")
        return {"id": fixture_id, "status": "pass", "observed_status": status.get("status"), "required": fixture.get("required", True)}
    except BenchmarkSnapshotError as exc:
        record = exc.to_record()
        record["fixture_id"] = fixture_id
        return {"id": fixture_id, "status": "fail", "required": fixture.get("required", True), "error": record}


def evaluate_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    suite_id = Path(out_dir).name
    suite_dir = resolve_snapshot_out(out_dir)
    if suite_dir.exists():
        sentinel = read_sentinel(suite_dir)
        if sentinel is None or sentinel.get("snapshot_id") != suite_id:
            raise BenchmarkSnapshotError("ERR_BENCHMARK_SNAPSHOT_PATH_UNSAFE", "existing benchmark snapshot suite is not snapshot-owned", path=suite_dir)
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
        raise BenchmarkSnapshotError("ERR_BENCHMARK_SNAPSHOT_FIXTURE_FAILED", "manifest decision is kill", path=manifest_path)
    return summary


def self_test() -> None:
    SNAPSHOT_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dwm-benchmark-snapshot-self-test-", dir=SNAPSHOT_ROOT) as tmp:
        summary = evaluate_manifest(ROOT / "fixtures" / "v40" / "manifest.json", Path(tmp) / "benchmark-snapshot-self-test")
    if summary["decision"] != "keep":
        raise BenchmarkSnapshotError("ERR_BENCHMARK_SNAPSHOT_FIXTURE_FAILED", "benchmark snapshot self-test manifest did not keep")
    print("dwm_benchmark_snapshot self-test: pass")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", choices=["record"])
    parser.add_argument("--expected-report-hash")
    parser.add_argument("--git-commit")
    parser.add_argument("--manifest")
    parser.add_argument("--out")
    parser.add_argument("--release-id")
    parser.add_argument("--report")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
        elif args.manifest:
            if not args.out:
                raise BenchmarkSnapshotError("ERR_BENCHMARK_SNAPSHOT_PATH_UNSAFE", "--manifest requires --out")
            summary = evaluate_manifest(Path(args.manifest), Path(args.out))
            print(canonical_json_text({key: summary[key] for key in ["suite_id", "fixture_count", "required_fixture_count", "required_passed", "passed", "failed", "skipped", "decision"]}))
        elif args.command == "record":
            if not args.out or not args.report or args.release_id is None:
                raise BenchmarkSnapshotError("ERR_BENCHMARK_SNAPSHOT_PATH_UNSAFE", "record requires --report, --release-id, and --out")
            status = record_snapshot(
                Path(args.report),
                resolve_snapshot_out(args.out),
                snapshot_id=Path(args.out).name,
                release_id=args.release_id,
                expected_report_hash=args.expected_report_hash,
                git_commit_value=args.git_commit,
            )
            print(canonical_json_text(status))
        else:
            parser.error("expected --self-test, --manifest, or record")
    except BenchmarkSnapshotError as exc:
        print(canonical_json_text(exc.to_record()), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
