#!/usr/bin/env python3
"""V39 benchmark trend promotion gate."""

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
from dwm_benchmark_history import HISTORY_ROOT, build_history, make_report_dir  # noqa: E402


TOOL = "dwm_benchmark_promotion.py"
SCHEMA_VERSION = "1.0"
PROMOTION_VERSION = "39.0.0"
PROMOTION_ROOT = ROOT / "out" / "benchmark-promotions"
SENTINEL = ".dwm_benchmark_promotion-owned.json"
DEFAULT_MIN_ENTRIES = 3
DEFAULT_MIN_DELTA_BPS = 100


class BenchmarkPromotionError(ValueError):
    """Structured V39 benchmark promotion failure."""

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
        raise BenchmarkPromotionError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise BenchmarkPromotionError(code, "path contains a symlink", path=current)


def resolve_promotion_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_BENCHMARK_PROMOTION_PATH_UNSAFE", message="benchmark promotion output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = PROMOTION_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise BenchmarkPromotionError("ERR_BENCHMARK_PROMOTION_PATH_UNSAFE", f"benchmark promotion output must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise BenchmarkPromotionError("ERR_BENCHMARK_PROMOTION_PATH_UNSAFE", "benchmark promotion output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_BENCHMARK_PROMOTION_PATH_SYMLINK")
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


def prepare_out_dir(path: Path, promotion_id: str, *, source: Path) -> None:
    if path.exists():
        if path.is_symlink():
            raise BenchmarkPromotionError("ERR_BENCHMARK_PROMOTION_PATH_SYMLINK", "benchmark promotion output is a symlink", path=path)
        if not path.is_dir():
            raise BenchmarkPromotionError("ERR_BENCHMARK_PROMOTION_PATH_UNSAFE", "benchmark promotion output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("promotion_id") != promotion_id:
            raise BenchmarkPromotionError("ERR_BENCHMARK_PROMOTION_PATH_UNSAFE", "existing benchmark promotion output is not promotion-owned", path=path)
        shutil.rmtree(path)
    PROMOTION_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(
        path / SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "promotion_version": PROMOTION_VERSION,
            "promotion_id": promotion_id,
            "source_path": rel(source),
            "created_at": now_utc(),
        },
        root=path,
    )


def load_history(history_dir: Path) -> dict[str, Any]:
    history_path = history_dir / "history.json"
    status_path = history_dir / "status.json"
    if not history_path.is_file() or history_path.is_symlink() or not status_path.is_file() or status_path.is_symlink():
        raise BenchmarkPromotionError("ERR_BENCHMARK_PROMOTION_ARTIFACT_MISSING", "history artifacts are missing", path=history_dir)
    history = read_json(history_path)
    status = read_json(status_path)
    if history != status:
        raise BenchmarkPromotionError("ERR_BENCHMARK_PROMOTION_STALE_HISTORY", "history status and artifact do not match", path=history_dir)
    if history.get("status") != "history-recorded":
        raise BenchmarkPromotionError("ERR_BENCHMARK_PROMOTION_STALE_HISTORY", "history is not recorded", path=history_dir)
    return history


def validate_promotion(history: dict[str, Any], *, history_dir: Path, min_entries: int, min_delta_bps: int, allow_fixture: bool) -> None:
    entries = history.get("entries")
    trend = history.get("trend_metrics")
    if not isinstance(entries, list) or not isinstance(trend, dict):
        raise BenchmarkPromotionError("ERR_BENCHMARK_PROMOTION_HISTORY_INVALID", "history entries or trend metrics are missing", path=history_dir)
    if len(entries) < min_entries:
        raise BenchmarkPromotionError("ERR_BENCHMARK_PROMOTION_INSUFFICIENT_HISTORY", "not enough history entries for promotion", path=history_dir)
    report_hashes = [entry.get("report_hash") for entry in entries if isinstance(entry, dict)]
    if len(report_hashes) != len(entries) or len(set(report_hashes)) != len(report_hashes):
        raise BenchmarkPromotionError("ERR_BENCHMARK_PROMOTION_HISTORY_INVALID", "history report hashes must be present and unique", path=history_dir)
    source_kinds = [entry.get("source_kind") for entry in entries if isinstance(entry, dict)]
    if len(source_kinds) != len(entries):
        raise BenchmarkPromotionError("ERR_BENCHMARK_PROMOTION_SOURCE_NOT_RELEASE", "history entries must record source_kind", path=history_dir)
    if not allow_fixture and any(kind != "release" for kind in source_kinds):
        raise BenchmarkPromotionError("ERR_BENCHMARK_PROMOTION_SOURCE_NOT_RELEASE", "promotion requires release source_kind entries", path=history_dir)
    scores = [entry.get("score_bps") for entry in entries if isinstance(entry, dict)]
    if len(scores) != len(entries) or any(not isinstance(score, int) for score in scores):
        raise BenchmarkPromotionError("ERR_BENCHMARK_PROMOTION_HISTORY_INVALID", "history score_bps values are invalid", path=history_dir)
    if any(next_score < score for score, next_score in zip(scores, scores[1:], strict=False)):
        raise BenchmarkPromotionError("ERR_BENCHMARK_PROMOTION_NOT_UPWARD", "promotion requires a non-decreasing trend", path=history_dir)
    delta = trend.get("delta_score_bps")
    if not isinstance(delta, int) or delta < min_delta_bps:
        raise BenchmarkPromotionError("ERR_BENCHMARK_PROMOTION_DELTA_TOO_SMALL", "promotion delta is below the minimum threshold", path=history_dir)


def promote_history(
    history_dir: Path,
    out_dir: Path,
    *,
    promotion_id: str,
    min_entries: int = DEFAULT_MIN_ENTRIES,
    min_delta_bps: int = DEFAULT_MIN_DELTA_BPS,
    allow_fixture: bool = False,
) -> dict[str, Any]:
    history = load_history(history_dir)
    validate_promotion(history, history_dir=history_dir, min_entries=min_entries, min_delta_bps=min_delta_bps, allow_fixture=allow_fixture)
    history_hash = canonical_hash(history)
    prepare_out_dir(out_dir, promotion_id, source=history_dir)
    trend_source = history_dir / "trend.svg"
    if not trend_source.is_file() or trend_source.is_symlink():
        raise BenchmarkPromotionError("ERR_BENCHMARK_PROMOTION_ARTIFACT_MISSING", "trend.svg is missing", path=history_dir)
    shutil.copyfile(trend_source, out_dir / "promoted-trend.svg")
    promotion = {
        "status": "promotion-ready",
        "promotion_id": promotion_id,
        "source": "benchmark-history",
        "history_path": rel(history_dir),
        "trend_metrics": history["trend_metrics"],
        "entry_count": len(history["entries"]),
        "min_entries": min_entries,
        "min_delta_bps": min_delta_bps,
        "readme_embed": f"![DWM benchmark history]({rel(out_dir / 'promoted-trend.svg')})",
        "source_hashes": {"history": history_hash, **history.get("source_hashes", {})},
    }
    write_json_atomic(out_dir / "promotion.json", promotion, root=out_dir)
    write_json_atomic(out_dir / "status.json", promotion, root=out_dir)
    (out_dir / "README-snippet.md").write_text(promotion["readme_embed"] + "\n")
    return promotion


def make_history_dir(base_name: str, *, scores: list[bool], source_kind: str = "release") -> Path:
    reports = [
        make_report_dir(f"{base_name}-{index}", publish_claim=passed, failed=not passed)
        for index, passed in enumerate(scores)
    ]
    history_dir = HISTORY_ROOT / f"{base_name}-history"
    build_history(
        reports,
        history_dir,
        history_id=history_dir.name,
        labels=[f"r{index}" for index, _ in enumerate(reports)],
        source_kinds=[source_kind for _ in reports],
    )
    return history_dir


def blocked_fixture_status(kind: str, fixture: dict[str, Any], suite_id: str) -> dict[str, Any]:
    try:
        if kind == "insufficient-history":
            history_dir = make_history_dir(f"{suite_id}-insufficient", scores=[False, True])
            promote_history(history_dir, PROMOTION_ROOT / f"{suite_id}-insufficient", promotion_id=f"{suite_id}-insufficient")
        elif kind == "fixture-source":
            history_dir = make_history_dir(f"{suite_id}-fixture-source", scores=[False, False, True], source_kind="fixture")
            promote_history(history_dir, PROMOTION_ROOT / f"{suite_id}-fixture-source", promotion_id=f"{suite_id}-fixture-source")
        elif kind == "not-upward":
            history_dir = make_history_dir(f"{suite_id}-not-upward", scores=[False, True, False])
            promote_history(history_dir, PROMOTION_ROOT / f"{suite_id}-not-upward", promotion_id=f"{suite_id}-not-upward")
        elif kind == "delta-too-small":
            history_dir = make_history_dir(f"{suite_id}-delta-small", scores=[True, True, True])
            promote_history(history_dir, PROMOTION_ROOT / f"{suite_id}-delta-small", promotion_id=f"{suite_id}-delta-small")
        elif kind == "stale-history":
            history_dir = make_history_dir(f"{suite_id}-stale", scores=[False, False, True])
            status_path = history_dir / "status.json"
            status = read_json(status_path)
            status["trend_metrics"]["delta_score_bps"] = 0
            write_json_atomic(status_path, status, root=history_dir)
            promote_history(history_dir, PROMOTION_ROOT / f"{suite_id}-stale", promotion_id=f"{suite_id}-stale")
        else:
            raise BenchmarkPromotionError("ERR_BENCHMARK_PROMOTION_FIXTURE_FAILED", f"unknown blocked fixture kind: {kind}")
    except BenchmarkPromotionError as exc:
        if fixture.get("expected_error") != exc.code:
            raise
        return {"status": "blocked", "error": exc.to_record()}
    raise BenchmarkPromotionError("ERR_BENCHMARK_PROMOTION_FIXTURE_FAILED", f"{kind} unexpectedly passed")


def run_fixture(fixture: dict[str, Any], suite_dir: Path) -> dict[str, Any]:
    fixture_id = fixture["id"]
    try:
        kind = fixture["kind"]
        if kind == "promotion-ready":
            history_dir = make_history_dir(f"{suite_dir.name}-{fixture_id}", scores=[False, False, True])
            status = promote_history(history_dir, suite_dir / fixture_id, promotion_id=fixture_id)
        elif kind in {"insufficient-history", "fixture-source", "not-upward", "delta-too-small", "stale-history"}:
            status = blocked_fixture_status(kind, fixture, suite_dir.name)
        else:
            raise BenchmarkPromotionError("ERR_BENCHMARK_PROMOTION_FIXTURE_FAILED", f"unknown fixture kind: {kind}")
        expected_status = fixture.get("expected_status")
        if expected_status is not None and status.get("status") != expected_status:
            raise BenchmarkPromotionError("ERR_BENCHMARK_PROMOTION_FIXTURE_FAILED", f"expected status {expected_status}, got {status.get('status')}")
        expected_error = fixture.get("expected_error")
        actual_error = status.get("error", {}).get("code") if isinstance(status.get("error"), dict) else None
        if expected_error is not None and actual_error != expected_error:
            raise BenchmarkPromotionError("ERR_BENCHMARK_PROMOTION_FIXTURE_FAILED", f"expected error {expected_error}, got {actual_error}")
        return {"id": fixture_id, "status": "pass", "observed_status": status.get("status"), "required": fixture.get("required", True)}
    except BenchmarkPromotionError as exc:
        record = exc.to_record()
        record["fixture_id"] = fixture_id
        return {"id": fixture_id, "status": "fail", "required": fixture.get("required", True), "error": record}


def evaluate_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    suite_id = Path(out_dir).name
    suite_dir = resolve_promotion_out(out_dir)
    if suite_dir.exists():
        sentinel = read_sentinel(suite_dir)
        if sentinel is None or sentinel.get("promotion_id") != suite_id:
            raise BenchmarkPromotionError("ERR_BENCHMARK_PROMOTION_PATH_UNSAFE", "existing benchmark promotion suite is not promotion-owned", path=suite_dir)
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
        raise BenchmarkPromotionError("ERR_BENCHMARK_PROMOTION_FIXTURE_FAILED", "manifest decision is kill", path=manifest_path)
    return summary


def self_test() -> None:
    PROMOTION_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dwm-benchmark-promotion-self-test-", dir=PROMOTION_ROOT) as tmp:
        summary = evaluate_manifest(ROOT / "fixtures" / "v39" / "manifest.json", Path(tmp) / "benchmark-promotion-self-test")
    if summary["decision"] != "keep":
        raise BenchmarkPromotionError("ERR_BENCHMARK_PROMOTION_FIXTURE_FAILED", "benchmark promotion self-test manifest did not keep")
    print("dwm_benchmark_promotion self-test: pass")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", choices=["promote"])
    parser.add_argument("--allow-fixture", action="store_true")
    parser.add_argument("--history")
    parser.add_argument("--manifest")
    parser.add_argument("--min-delta-bps", type=int, default=DEFAULT_MIN_DELTA_BPS)
    parser.add_argument("--min-entries", type=int, default=DEFAULT_MIN_ENTRIES)
    parser.add_argument("--out")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
        elif args.manifest:
            if not args.out:
                raise BenchmarkPromotionError("ERR_BENCHMARK_PROMOTION_PATH_UNSAFE", "--manifest requires --out")
            summary = evaluate_manifest(Path(args.manifest), Path(args.out))
            print(canonical_json_text({key: summary[key] for key in ["suite_id", "fixture_count", "required_fixture_count", "required_passed", "passed", "failed", "skipped", "decision"]}))
        elif args.command == "promote":
            if not args.out or not args.history:
                raise BenchmarkPromotionError("ERR_BENCHMARK_PROMOTION_PATH_UNSAFE", "promote requires --history and --out")
            status = promote_history(
                Path(args.history),
                resolve_promotion_out(args.out),
                promotion_id=Path(args.out).name,
                min_entries=args.min_entries,
                min_delta_bps=args.min_delta_bps,
                allow_fixture=args.allow_fixture,
            )
            print(canonical_json_text(status))
        else:
            parser.error("expected --self-test, --manifest, or promote")
    except BenchmarkPromotionError as exc:
        print(canonical_json_text(exc.to_record()), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
