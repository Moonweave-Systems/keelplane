#!/usr/bin/env python3
"""V42 benchmark publish candidate workflow."""

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
from dwm_benchmark_promotion import PROMOTION_ROOT, BenchmarkPromotionError, promote_history  # noqa: E402
from dwm_benchmark_series import SERIES_ROOT, build_series, make_snapshot_dir  # noqa: E402


TOOL = "dwm_benchmark_candidate.py"
SCHEMA_VERSION = "1.0"
CANDIDATE_VERSION = "42.0.0"
CANDIDATE_ROOT = ROOT / "out" / "benchmark-candidates"
SENTINEL = ".dwm_benchmark_candidate-owned.json"


class BenchmarkCandidateError(ValueError):
    """Structured V42 benchmark candidate failure."""

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
        raise BenchmarkCandidateError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise BenchmarkCandidateError(code, "path contains a symlink", path=current)


def resolve_candidate_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_BENCHMARK_CANDIDATE_PATH_UNSAFE", message="benchmark candidate output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = CANDIDATE_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise BenchmarkCandidateError("ERR_BENCHMARK_CANDIDATE_PATH_UNSAFE", f"benchmark candidate output must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise BenchmarkCandidateError("ERR_BENCHMARK_CANDIDATE_PATH_UNSAFE", "benchmark candidate output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_BENCHMARK_CANDIDATE_PATH_SYMLINK")
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


def prepare_out_dir(path: Path, candidate_id: str, *, source: Path) -> None:
    if path.exists():
        if path.is_symlink():
            raise BenchmarkCandidateError("ERR_BENCHMARK_CANDIDATE_PATH_SYMLINK", "benchmark candidate output is a symlink", path=path)
        if not path.is_dir():
            raise BenchmarkCandidateError("ERR_BENCHMARK_CANDIDATE_PATH_UNSAFE", "benchmark candidate output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("candidate_id") != candidate_id:
            raise BenchmarkCandidateError("ERR_BENCHMARK_CANDIDATE_PATH_UNSAFE", "existing benchmark candidate output is not candidate-owned", path=path)
        shutil.rmtree(path)
    CANDIDATE_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(
        path / SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "candidate_version": CANDIDATE_VERSION,
            "candidate_id": candidate_id,
            "source_path": rel(source),
            "created_at": now_utc(),
        },
        root=path,
    )


def load_series(series_dir: Path) -> dict[str, Any]:
    series_path = series_dir / "series.json"
    status_path = series_dir / "status.json"
    if not series_path.is_file() or series_path.is_symlink() or not status_path.is_file() or status_path.is_symlink():
        raise BenchmarkCandidateError("ERR_BENCHMARK_CANDIDATE_ARTIFACT_MISSING", "series artifacts are missing", path=series_dir)
    series = read_json(series_path)
    status = read_json(status_path)
    if series != status:
        raise BenchmarkCandidateError("ERR_BENCHMARK_CANDIDATE_STALE_SERIES", "series status and artifact do not match", path=series_dir)
    if series.get("status") != "series-recorded":
        raise BenchmarkCandidateError("ERR_BENCHMARK_CANDIDATE_STALE_SERIES", "series is not recorded", path=series_dir)
    history_path = series.get("history_path")
    if not isinstance(history_path, str) or not history_path:
        raise BenchmarkCandidateError("ERR_BENCHMARK_CANDIDATE_SERIES_INVALID", "series history_path is missing", path=series_dir)
    return series


def make_candidate(series_dir: Path, out_dir: Path, *, candidate_id: str, min_entries: int = 3, min_delta_bps: int = 100) -> dict[str, Any]:
    series = load_series(series_dir)
    history_dir = ROOT / str(series["history_path"])
    promotion_dir = PROMOTION_ROOT / f"{out_dir.parent.name}-{candidate_id}-promotion"
    try:
        promotion = promote_history(
            history_dir,
            promotion_dir,
            promotion_id=promotion_dir.name,
            min_entries=min_entries,
            min_delta_bps=min_delta_bps,
        )
    except BenchmarkPromotionError as exc:
        raise BenchmarkCandidateError(f"ERR_BENCHMARK_CANDIDATE_PROMOTION_{exc.code.removeprefix('ERR_BENCHMARK_PROMOTION_')}", exc.message, path=series_dir) from exc
    prepare_out_dir(out_dir, candidate_id, source=series_dir)
    candidate = {
        "status": "candidate-ready",
        "candidate_id": candidate_id,
        "series_path": rel(series_dir),
        "history_path": series["history_path"],
        "promotion_path": rel(promotion_dir),
        "release_ids": series.get("release_ids", []),
        "trend_metrics": promotion["trend_metrics"],
        "readme_embed": promotion["readme_embed"],
        "source_hashes": {
            "series": canonical_hash(series),
            "promotion": canonical_hash(promotion),
            **promotion.get("source_hashes", {}),
        },
    }
    write_json_atomic(out_dir / "candidate.json", candidate, root=out_dir)
    write_json_atomic(out_dir / "status.json", candidate, root=out_dir)
    (out_dir / "README-snippet.md").write_text(candidate["readme_embed"] + "\n")
    return candidate


def make_series_dir(base_name: str, *, scores: list[bool], stale: bool = False) -> Path:
    snapshots = [
        make_snapshot_dir(f"{base_name}-{index}", f"r{index}", failed=not passed)
        for index, passed in enumerate(scores)
    ]
    series_dir = SERIES_ROOT / f"{base_name}-series"
    build_series(snapshots, series_dir, series_id=series_dir.name)
    if stale:
        status = read_json(series_dir / "status.json")
        status["release_ids"] = list(reversed(status["release_ids"]))
        write_json_atomic(series_dir / "status.json", status, root=series_dir)
    return series_dir


def blocked_fixture_status(kind: str, fixture: dict[str, Any], suite_id: str) -> dict[str, Any]:
    try:
        if kind == "not-upward":
            series_dir = make_series_dir(f"{suite_id}-not-upward", scores=[False, True, False])
            make_candidate(series_dir, CANDIDATE_ROOT / f"{suite_id}-not-upward", candidate_id=f"{suite_id}-not-upward")
        elif kind == "delta-too-small":
            series_dir = make_series_dir(f"{suite_id}-delta-small", scores=[True, True, True])
            make_candidate(series_dir, CANDIDATE_ROOT / f"{suite_id}-delta-small", candidate_id=f"{suite_id}-delta-small")
        elif kind == "stale-series":
            series_dir = make_series_dir(f"{suite_id}-stale", scores=[False, False, True], stale=True)
            make_candidate(series_dir, CANDIDATE_ROOT / f"{suite_id}-stale", candidate_id=f"{suite_id}-stale")
        elif kind == "missing-series":
            missing_dir = SERIES_ROOT / f"{suite_id}-missing"
            if missing_dir.exists():
                shutil.rmtree(missing_dir)
            missing_dir.mkdir(parents=True)
            make_candidate(missing_dir, CANDIDATE_ROOT / f"{suite_id}-missing", candidate_id=f"{suite_id}-missing")
        else:
            raise BenchmarkCandidateError("ERR_BENCHMARK_CANDIDATE_FIXTURE_FAILED", f"unknown blocked fixture kind: {kind}")
    except BenchmarkCandidateError as exc:
        if fixture.get("expected_error") != exc.code:
            raise
        return {"status": "blocked", "error": exc.to_record()}
    raise BenchmarkCandidateError("ERR_BENCHMARK_CANDIDATE_FIXTURE_FAILED", f"{kind} unexpectedly passed")


def run_fixture(fixture: dict[str, Any], suite_dir: Path) -> dict[str, Any]:
    fixture_id = fixture["id"]
    try:
        kind = fixture["kind"]
        if kind == "candidate-ready":
            series_dir = make_series_dir(f"{suite_dir.name}-{fixture_id}", scores=[False, False, True])
            status = make_candidate(series_dir, suite_dir / fixture_id, candidate_id=fixture_id)
        elif kind in {"not-upward", "delta-too-small", "stale-series", "missing-series"}:
            status = blocked_fixture_status(kind, fixture, suite_dir.name)
        else:
            raise BenchmarkCandidateError("ERR_BENCHMARK_CANDIDATE_FIXTURE_FAILED", f"unknown fixture kind: {kind}")
        expected_status = fixture.get("expected_status")
        if expected_status is not None and status.get("status") != expected_status:
            raise BenchmarkCandidateError("ERR_BENCHMARK_CANDIDATE_FIXTURE_FAILED", f"expected status {expected_status}, got {status.get('status')}")
        expected_error = fixture.get("expected_error")
        actual_error = status.get("error", {}).get("code") if isinstance(status.get("error"), dict) else None
        if expected_error is not None and actual_error != expected_error:
            raise BenchmarkCandidateError("ERR_BENCHMARK_CANDIDATE_FIXTURE_FAILED", f"expected error {expected_error}, got {actual_error}")
        return {"id": fixture_id, "status": "pass", "observed_status": status.get("status"), "required": fixture.get("required", True)}
    except BenchmarkCandidateError as exc:
        record = exc.to_record()
        record["fixture_id"] = fixture_id
        return {"id": fixture_id, "status": "fail", "required": fixture.get("required", True), "error": record}


def evaluate_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    suite_id = Path(out_dir).name
    suite_dir = resolve_candidate_out(out_dir)
    if suite_dir.exists():
        sentinel = read_sentinel(suite_dir)
        if sentinel is None or sentinel.get("candidate_id") != suite_id:
            raise BenchmarkCandidateError("ERR_BENCHMARK_CANDIDATE_PATH_UNSAFE", "existing benchmark candidate suite is not candidate-owned", path=suite_dir)
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
        raise BenchmarkCandidateError("ERR_BENCHMARK_CANDIDATE_FIXTURE_FAILED", "manifest decision is kill", path=manifest_path)
    return summary


def self_test() -> None:
    CANDIDATE_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dwm-benchmark-candidate-self-test-", dir=CANDIDATE_ROOT) as tmp:
        summary = evaluate_manifest(ROOT / "fixtures" / "v42" / "manifest.json", Path(tmp) / "benchmark-candidate-self-test")
    if summary["decision"] != "keep":
        raise BenchmarkCandidateError("ERR_BENCHMARK_CANDIDATE_FIXTURE_FAILED", "benchmark candidate self-test manifest did not keep")
    print("dwm_benchmark_candidate self-test: pass")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", choices=["make"])
    parser.add_argument("--manifest")
    parser.add_argument("--min-delta-bps", type=int, default=100)
    parser.add_argument("--min-entries", type=int, default=3)
    parser.add_argument("--out")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--series")
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
        elif args.manifest:
            if not args.out:
                raise BenchmarkCandidateError("ERR_BENCHMARK_CANDIDATE_PATH_UNSAFE", "--manifest requires --out")
            summary = evaluate_manifest(Path(args.manifest), Path(args.out))
            print(canonical_json_text({key: summary[key] for key in ["suite_id", "fixture_count", "required_fixture_count", "required_passed", "passed", "failed", "skipped", "decision"]}))
        elif args.command == "make":
            if not args.out or not args.series:
                raise BenchmarkCandidateError("ERR_BENCHMARK_CANDIDATE_PATH_UNSAFE", "make requires --series and --out")
            status = make_candidate(
                Path(args.series),
                resolve_candidate_out(args.out),
                candidate_id=Path(args.out).name,
                min_entries=args.min_entries,
                min_delta_bps=args.min_delta_bps,
            )
            print(canonical_json_text(status))
        else:
            parser.error("expected --self-test, --manifest, or make")
    except BenchmarkCandidateError as exc:
        print(canonical_json_text(exc.to_record()), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
