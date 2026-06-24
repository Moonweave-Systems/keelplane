#!/usr/bin/env python3
"""V34 adversarial live score review gate."""

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
from dwm_benchmark import REQUIRED_TASK_IDS  # noqa: E402
from dwm_live_score_aggregate import AGGREGATE_ROOT, aggregate_scores, make_score_dirs  # noqa: E402


TOOL = "dwm_live_score_review.py"
SCHEMA_VERSION = "1.0"
REVIEW_VERSION = "34.0.0"
REVIEW_ROOT = ROOT / "out" / "live-score-reviews"
SENTINEL = ".dwm_live_score_review-owned.json"


class LiveScoreReviewError(ValueError):
    """Structured V34 live score review failure."""

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
        raise LiveScoreReviewError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise LiveScoreReviewError(code, "path contains a symlink", path=current)


def resolve_review_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_LIVE_SCORE_REVIEW_PATH_UNSAFE", message="live score review output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = REVIEW_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise LiveScoreReviewError("ERR_LIVE_SCORE_REVIEW_PATH_UNSAFE", f"live score review output must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise LiveScoreReviewError("ERR_LIVE_SCORE_REVIEW_PATH_UNSAFE", "live score review output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_LIVE_SCORE_REVIEW_PATH_SYMLINK")
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


def prepare_out_dir(path: Path, review_id: str, *, source: Path) -> None:
    if path.exists():
        if path.is_symlink():
            raise LiveScoreReviewError("ERR_LIVE_SCORE_REVIEW_PATH_SYMLINK", "live score review output is a symlink", path=path)
        if not path.is_dir():
            raise LiveScoreReviewError("ERR_LIVE_SCORE_REVIEW_PATH_UNSAFE", "live score review output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("review_id") != review_id:
            raise LiveScoreReviewError("ERR_LIVE_SCORE_REVIEW_PATH_UNSAFE", "existing live score review output is not review-owned", path=path)
        shutil.rmtree(path)
    REVIEW_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(
        path / SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "review_version": REVIEW_VERSION,
            "review_id": review_id,
            "source_path": rel(source),
            "created_at": now_utc(),
        },
        root=path,
    )


def load_aggregate(aggregate_dir: Path) -> dict[str, Any]:
    aggregate_path = aggregate_dir / "aggregate-score.json"
    status_path = aggregate_dir / "status.json"
    if not aggregate_path.is_file() or aggregate_path.is_symlink() or not status_path.is_file() or status_path.is_symlink():
        raise LiveScoreReviewError("ERR_LIVE_SCORE_REVIEW_ARTIFACT_MISSING", "aggregate artifacts are missing", path=aggregate_dir)
    aggregate = read_json(aggregate_path)
    status = read_json(status_path)
    if aggregate != status:
        raise LiveScoreReviewError("ERR_LIVE_SCORE_REVIEW_STALE_AGGREGATE", "aggregate status and artifact do not match", path=aggregate_dir)
    if aggregate.get("status") != "aggregate-recorded":
        raise LiveScoreReviewError("ERR_LIVE_SCORE_REVIEW_STALE_AGGREGATE", "aggregate is not recorded", path=aggregate_dir)
    return aggregate


def validate_aggregate(aggregate: dict[str, Any], *, aggregate_dir: Path) -> None:
    if aggregate.get("task_count") != len(REQUIRED_TASK_IDS):
        raise LiveScoreReviewError("ERR_LIVE_SCORE_REVIEW_TASK_MISMATCH", "aggregate task count does not match required task set", path=aggregate_dir)
    tasks = aggregate.get("tasks")
    if not isinstance(tasks, list) or [task.get("task_id") for task in tasks if isinstance(task, dict)] != REQUIRED_TASK_IDS:
        raise LiveScoreReviewError("ERR_LIVE_SCORE_REVIEW_TASK_MISMATCH", "aggregate task order does not match required task set", path=aggregate_dir)
    source_hashes = aggregate.get("source_hashes")
    if not isinstance(source_hashes, dict) or source_hashes.get("required_task_ids") != canonical_hash(REQUIRED_TASK_IDS):
        raise LiveScoreReviewError("ERR_LIVE_SCORE_REVIEW_HASH_MISMATCH", "aggregate required task hash is stale", path=aggregate_dir)
    score_hashes = source_hashes.get("scores")
    if not isinstance(score_hashes, dict) or set(score_hashes) != set(REQUIRED_TASK_IDS):
        raise LiveScoreReviewError("ERR_LIVE_SCORE_REVIEW_HASH_MISMATCH", "aggregate score hashes are incomplete", path=aggregate_dir)


def review_aggregate(
    aggregate_dir: Path,
    out_dir: Path,
    *,
    review_id: str,
    expected_aggregate_hash: str | None = None,
) -> dict[str, Any]:
    aggregate = load_aggregate(aggregate_dir)
    validate_aggregate(aggregate, aggregate_dir=aggregate_dir)
    aggregate_hash = canonical_hash(aggregate)
    if expected_aggregate_hash is not None and expected_aggregate_hash != aggregate_hash:
        raise LiveScoreReviewError("ERR_LIVE_SCORE_REVIEW_STALE_AGGREGATE", "expected aggregate hash does not match current aggregate", path=aggregate_dir)
    prepare_out_dir(out_dir, review_id, source=aggregate_dir)
    failed_tasks = aggregate.get("failed_task_ids", [])
    if failed_tasks:
        review_status = "refuted"
        refuted = ["aggregate contains failed task scores"]
        confirmed: list[str] = []
        unverified = ["benchmark success claim"]
    elif aggregate.get("claim_status") == "candidate":
        review_status = "review-ready"
        refuted = []
        confirmed = ["all required task scores passed"]
        unverified = ["benchmark success claim requires V35 report gate"]
    else:
        review_status = "unverified"
        refuted = []
        confirmed = ["aggregate is structurally complete"]
        unverified = ["success claim was not requested"]
    reviewed = {
        "status": "review-recorded",
        "review_status": review_status,
        "confirmed": confirmed,
        "refuted": refuted,
        "unverified": unverified,
        "task_count": aggregate["task_count"],
        "pass_count": aggregate["pass_count"],
        "failed_task_ids": failed_tasks,
        "benchmark_success_claimed": False,
        "source_hashes": {
            "aggregate": aggregate_hash,
            **aggregate.get("source_hashes", {}),
        },
    }
    write_json_atomic(out_dir / "reviewed-score.json", reviewed, root=out_dir)
    write_json_atomic(out_dir / "status.json", reviewed, root=out_dir)
    return reviewed


def make_aggregate_dir(base_name: str, *, failed_task_id: str | None = None, claim_success: bool = True) -> Path:
    score_dirs = make_score_dirs(base_name, failed_task_id=failed_task_id)
    aggregate_dir = AGGREGATE_ROOT / f"{base_name}-aggregate"
    aggregate_scores(score_dirs, aggregate_dir, aggregate_id=aggregate_dir.name, claim_success=claim_success)
    return aggregate_dir


def blocked_fixture_status(kind: str, fixture: dict[str, Any], suite_id: str) -> dict[str, Any]:
    try:
        if kind == "stale-aggregate":
            aggregate_dir = make_aggregate_dir(f"{suite_id}-stale")
            review_aggregate(
                aggregate_dir,
                REVIEW_ROOT / f"{suite_id}-stale",
                review_id=f"{suite_id}-stale",
                expected_aggregate_hash=str(fixture["expected_aggregate_hash"]),
            )
        elif kind == "task-mismatch":
            aggregate_dir = make_aggregate_dir(f"{suite_id}-task-mismatch")
            aggregate_path = aggregate_dir / "aggregate-score.json"
            aggregate = read_json(aggregate_path)
            aggregate["tasks"] = aggregate["tasks"][:-1]
            aggregate["task_count"] = len(aggregate["tasks"])
            write_json_atomic(aggregate_path, aggregate, root=aggregate_dir)
            write_json_atomic(aggregate_dir / "status.json", aggregate, root=aggregate_dir)
            review_aggregate(aggregate_dir, REVIEW_ROOT / f"{suite_id}-task-mismatch", review_id=f"{suite_id}-task-mismatch")
        elif kind == "hash-mismatch":
            aggregate_dir = make_aggregate_dir(f"{suite_id}-hash-mismatch")
            aggregate_path = aggregate_dir / "aggregate-score.json"
            aggregate = read_json(aggregate_path)
            aggregate["source_hashes"]["required_task_ids"] = "stale-required-task-hash"
            write_json_atomic(aggregate_path, aggregate, root=aggregate_dir)
            write_json_atomic(aggregate_dir / "status.json", aggregate, root=aggregate_dir)
            review_aggregate(aggregate_dir, REVIEW_ROOT / f"{suite_id}-hash-mismatch", review_id=f"{suite_id}-hash-mismatch")
        elif kind == "missing-artifact":
            missing_dir = AGGREGATE_ROOT / f"{suite_id}-missing"
            if missing_dir.exists():
                shutil.rmtree(missing_dir)
            missing_dir.mkdir(parents=True)
            review_aggregate(missing_dir, REVIEW_ROOT / f"{suite_id}-missing", review_id=f"{suite_id}-missing")
        else:
            raise LiveScoreReviewError("ERR_LIVE_SCORE_REVIEW_FIXTURE_FAILED", f"unknown blocked fixture kind: {kind}")
    except LiveScoreReviewError as exc:
        if fixture.get("expected_error") != exc.code:
            raise
        return {"status": "blocked", "error": exc.to_record()}
    raise LiveScoreReviewError("ERR_LIVE_SCORE_REVIEW_FIXTURE_FAILED", f"{kind} unexpectedly passed")


def run_fixture(fixture: dict[str, Any], suite_dir: Path) -> dict[str, Any]:
    fixture_id = fixture["id"]
    try:
        kind = fixture["kind"]
        if kind == "review-all-passed":
            aggregate_dir = make_aggregate_dir(f"{suite_dir.name}-{fixture_id}", claim_success=True)
            status = review_aggregate(aggregate_dir, suite_dir / fixture_id, review_id=fixture_id)
        elif kind == "review-failed-refuted":
            aggregate_dir = make_aggregate_dir(f"{suite_dir.name}-{fixture_id}", failed_task_id=REQUIRED_TASK_IDS[0], claim_success=False)
            status = review_aggregate(aggregate_dir, suite_dir / fixture_id, review_id=fixture_id)
        elif kind == "review-not-claimed-unverified":
            aggregate_dir = make_aggregate_dir(f"{suite_dir.name}-{fixture_id}", claim_success=False)
            status = review_aggregate(aggregate_dir, suite_dir / fixture_id, review_id=fixture_id)
        elif kind in {"stale-aggregate", "task-mismatch", "hash-mismatch", "missing-artifact"}:
            status = blocked_fixture_status(kind, fixture, suite_dir.name)
        else:
            raise LiveScoreReviewError("ERR_LIVE_SCORE_REVIEW_FIXTURE_FAILED", f"unknown fixture kind: {kind}")
        expected_status = fixture.get("expected_status")
        if expected_status is not None and status.get("status") != expected_status:
            raise LiveScoreReviewError("ERR_LIVE_SCORE_REVIEW_FIXTURE_FAILED", f"expected status {expected_status}, got {status.get('status')}")
        expected_review_status = fixture.get("expected_review_status")
        if expected_review_status is not None and status.get("review_status") != expected_review_status:
            raise LiveScoreReviewError("ERR_LIVE_SCORE_REVIEW_FIXTURE_FAILED", f"expected review_status {expected_review_status}, got {status.get('review_status')}")
        expected_error = fixture.get("expected_error")
        actual_error = status.get("error", {}).get("code") if isinstance(status.get("error"), dict) else None
        if expected_error is not None and actual_error != expected_error:
            raise LiveScoreReviewError("ERR_LIVE_SCORE_REVIEW_FIXTURE_FAILED", f"expected error {expected_error}, got {actual_error}")
        return {"id": fixture_id, "status": "pass", "observed_status": status.get("status"), "required": fixture.get("required", True)}
    except LiveScoreReviewError as exc:
        record = exc.to_record()
        record["fixture_id"] = fixture_id
        return {"id": fixture_id, "status": "fail", "required": fixture.get("required", True), "error": record}


def evaluate_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    suite_id = Path(out_dir).name
    suite_dir = resolve_review_out(out_dir)
    if suite_dir.exists():
        sentinel = read_sentinel(suite_dir)
        if sentinel is None or sentinel.get("review_id") != suite_id:
            raise LiveScoreReviewError("ERR_LIVE_SCORE_REVIEW_PATH_UNSAFE", "existing live score review suite is not review-owned", path=suite_dir)
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
        raise LiveScoreReviewError("ERR_LIVE_SCORE_REVIEW_FIXTURE_FAILED", "manifest decision is kill", path=manifest_path)
    return summary


def self_test() -> None:
    REVIEW_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dwm-live-score-review-self-test-", dir=REVIEW_ROOT) as tmp:
        summary = evaluate_manifest(ROOT / "fixtures" / "v34" / "manifest.json", Path(tmp) / "live-score-review-self-test")
    if summary["decision"] != "keep":
        raise LiveScoreReviewError("ERR_LIVE_SCORE_REVIEW_FIXTURE_FAILED", "live score review self-test manifest did not keep")
    print("dwm_live_score_review self-test: pass")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", choices=["review"])
    parser.add_argument("--aggregate")
    parser.add_argument("--expected-aggregate-hash")
    parser.add_argument("--manifest")
    parser.add_argument("--out")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
        elif args.manifest:
            if not args.out:
                raise LiveScoreReviewError("ERR_LIVE_SCORE_REVIEW_PATH_UNSAFE", "--manifest requires --out")
            summary = evaluate_manifest(Path(args.manifest), Path(args.out))
            print(canonical_json_text({key: summary[key] for key in ["suite_id", "fixture_count", "required_fixture_count", "required_passed", "passed", "failed", "skipped", "decision"]}))
        elif args.command == "review":
            if not args.out or not args.aggregate:
                raise LiveScoreReviewError("ERR_LIVE_SCORE_REVIEW_PATH_UNSAFE", "review requires --aggregate and --out")
            status = review_aggregate(
                Path(args.aggregate),
                resolve_review_out(args.out),
                review_id=Path(args.out).name,
                expected_aggregate_hash=args.expected_aggregate_hash,
            )
            print(canonical_json_text(status))
        else:
            parser.error("expected --self-test, --manifest, or review")
    except LiveScoreReviewError as exc:
        print(canonical_json_text(exc.to_record()), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
