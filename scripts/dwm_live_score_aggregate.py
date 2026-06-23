#!/usr/bin/env python3
"""V33 live score aggregate gate."""

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
from dwm_live_receipt import RECEIPT_ROOT, ingest_receipt, load_preflight, make_preflight_dir, synthetic_receipt_for  # noqa: E402
from dwm_live_receipt_judge import JUDGMENT_ROOT, judge_receipt  # noqa: E402
from dwm_live_score import SCORE_ROOT, score_live_judgment  # noqa: E402


TOOL = "dwm_live_score_aggregate.py"
SCHEMA_VERSION = "1.0"
AGGREGATE_VERSION = "33.0.0"
AGGREGATE_ROOT = ROOT / "out" / "live-score-aggregates"
SENTINEL = ".dwm_live_score_aggregate-owned.json"


class LiveScoreAggregateError(ValueError):
    """Structured V33 live score aggregate failure."""

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
        raise LiveScoreAggregateError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise LiveScoreAggregateError(code, "path contains a symlink", path=current)


def resolve_aggregate_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_LIVE_SCORE_AGGREGATE_PATH_UNSAFE", message="live score aggregate output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = AGGREGATE_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise LiveScoreAggregateError("ERR_LIVE_SCORE_AGGREGATE_PATH_UNSAFE", f"live score aggregate output must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise LiveScoreAggregateError("ERR_LIVE_SCORE_AGGREGATE_PATH_UNSAFE", "live score aggregate output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_LIVE_SCORE_AGGREGATE_PATH_SYMLINK")
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


def prepare_out_dir(path: Path, aggregate_id: str, *, source: Path) -> None:
    if path.exists():
        if path.is_symlink():
            raise LiveScoreAggregateError("ERR_LIVE_SCORE_AGGREGATE_PATH_SYMLINK", "live score aggregate output is a symlink", path=path)
        if not path.is_dir():
            raise LiveScoreAggregateError("ERR_LIVE_SCORE_AGGREGATE_PATH_UNSAFE", "live score aggregate output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("aggregate_id") != aggregate_id:
            raise LiveScoreAggregateError("ERR_LIVE_SCORE_AGGREGATE_PATH_UNSAFE", "existing live score aggregate output is not aggregate-owned", path=path)
        shutil.rmtree(path)
    AGGREGATE_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(
        path / SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "aggregate_version": AGGREGATE_VERSION,
            "aggregate_id": aggregate_id,
            "source_path": rel(source),
            "created_at": now_utc(),
        },
        root=path,
    )


def load_score(score_dir: Path) -> dict[str, Any]:
    score_path = score_dir / "score.json"
    status_path = score_dir / "status.json"
    if not score_path.is_file() or score_path.is_symlink() or not status_path.is_file() or status_path.is_symlink():
        raise LiveScoreAggregateError("ERR_LIVE_SCORE_AGGREGATE_ARTIFACT_MISSING", "score artifacts are missing", path=score_dir)
    score = read_json(score_path)
    status = read_json(status_path)
    if score != status:
        raise LiveScoreAggregateError("ERR_LIVE_SCORE_AGGREGATE_STALE_SCORE", "score status and artifact do not match", path=score_dir)
    if score.get("status") != "score-recorded":
        raise LiveScoreAggregateError("ERR_LIVE_SCORE_AGGREGATE_STALE_SCORE", "score is not recorded", path=score_dir)
    return score


def validate_score(score: dict[str, Any], *, score_dir: Path) -> None:
    source_hashes = score.get("source_hashes")
    if not isinstance(source_hashes, dict) or not source_hashes.get("judgment") or not source_hashes.get("receipt"):
        raise LiveScoreAggregateError("ERR_LIVE_SCORE_AGGREGATE_STALE_SCORE", "score source hashes are incomplete", path=score_dir)
    if score.get("verification_status") not in {"passed", "failed"}:
        raise LiveScoreAggregateError("ERR_LIVE_SCORE_AGGREGATE_STALE_SCORE", "score verification status is unsupported", path=score_dir)
    if score.get("score") not in {0, 1}:
        raise LiveScoreAggregateError("ERR_LIVE_SCORE_AGGREGATE_STALE_SCORE", "score value is unsupported", path=score_dir)
    if not isinstance(score.get("task_id"), str) or not score["task_id"]:
        raise LiveScoreAggregateError("ERR_LIVE_SCORE_AGGREGATE_STALE_SCORE", "score task id is missing", path=score_dir)


def aggregate_scores(
    score_dirs: list[Path],
    out_dir: Path,
    *,
    aggregate_id: str,
    expected_score_hashes: dict[str, str] | None = None,
    claim_success: bool = False,
) -> dict[str, Any]:
    if not score_dirs:
        raise LiveScoreAggregateError("ERR_LIVE_SCORE_AGGREGATE_ARTIFACT_MISSING", "at least one score directory is required")
    scores_by_task: dict[str, dict[str, Any]] = {}
    score_hashes: dict[str, str] = {}
    task_records: list[dict[str, Any]] = []
    for score_dir in score_dirs:
        score = load_score(score_dir)
        validate_score(score, score_dir=score_dir)
        task_id = score["task_id"]
        if task_id in scores_by_task:
            raise LiveScoreAggregateError("ERR_LIVE_SCORE_AGGREGATE_TASK_DUPLICATE", f"duplicate score for task {task_id}", path=score_dir)
        score_hash = canonical_hash(score)
        if expected_score_hashes is not None and expected_score_hashes.get(task_id) != score_hash:
            raise LiveScoreAggregateError("ERR_LIVE_SCORE_AGGREGATE_STALE_SCORE", f"expected score hash does not match task {task_id}", path=score_dir)
        scores_by_task[task_id] = score
        score_hashes[task_id] = score_hash
        task_records.append(
            {
                "task_id": task_id,
                "verification_status": score["verification_status"],
                "score": score["score"],
                "adapter": score.get("adapter"),
            }
        )
    missing = [task_id for task_id in REQUIRED_TASK_IDS if task_id not in scores_by_task]
    if missing:
        raise LiveScoreAggregateError("ERR_LIVE_SCORE_AGGREGATE_TASK_MISSING", f"required score tasks are missing: {missing}")
    failed_tasks = [task_id for task_id, score in scores_by_task.items() if score.get("verification_status") != "passed"]
    if claim_success and failed_tasks:
        raise LiveScoreAggregateError("ERR_LIVE_SCORE_AGGREGATE_UNSUPPORTED_CLAIM", f"cannot claim success with failed tasks: {failed_tasks}")
    prepare_out_dir(out_dir, aggregate_id, source=score_dirs[0])
    pass_count = len(REQUIRED_TASK_IDS) - len(failed_tasks)
    aggregate = {
        "status": "aggregate-recorded",
        "task_count": len(REQUIRED_TASK_IDS),
        "pass_count": pass_count,
        "failed_task_ids": failed_tasks,
        "claim_success_requested": claim_success,
        "claim_status": "candidate" if claim_success and not failed_tasks else "not-claimed",
        "benchmark_success_claimed": False,
        "tasks": sorted(task_records, key=lambda item: REQUIRED_TASK_IDS.index(item["task_id"])),
        "source_hashes": {
            "scores": score_hashes,
            "required_task_ids": canonical_hash(REQUIRED_TASK_IDS),
        },
    }
    write_json_atomic(out_dir / "aggregate-score.json", aggregate, root=out_dir)
    write_json_atomic(out_dir / "status.json", aggregate, root=out_dir)
    return aggregate


def make_score_dir(base_name: str, task_id: str, *, passed: bool = True) -> Path:
    preflight_dir = make_preflight_dir(f"{base_name}-{task_id}-preflight", task_id=task_id)
    preflight = load_preflight(preflight_dir)
    receipt = synthetic_receipt_for(preflight)
    receipt["returncode"] = 0 if passed else 1
    receipt_dir = RECEIPT_ROOT / f"{base_name}-{task_id}-receipt"
    ingest_receipt(preflight_dir, receipt, receipt_dir, receipt_id=receipt_dir.name)
    judgment_dir = JUDGMENT_ROOT / f"{base_name}-{task_id}-judgment"
    judge_receipt(receipt_dir, judgment_dir, judgment_id=judgment_dir.name)
    verification_spec = {
        "schema_version": SCHEMA_VERSION,
        "task_id": task_id,
        "adapter": preflight["adapter"],
        "expected_returncode": 0,
        "expected_stdout_hash": receipt["stdout_hash"],
        "expected_stderr_hash": receipt["stderr_hash"],
    }
    score_dir = SCORE_ROOT / f"{base_name}-{task_id}-score"
    score_live_judgment(judgment_dir, receipt_dir, verification_spec, score_dir, score_id=score_dir.name)
    return score_dir


def make_score_dirs(base_name: str, *, failed_task_id: str | None = None, omit_task_id: str | None = None) -> list[Path]:
    score_dirs = []
    for task_id in REQUIRED_TASK_IDS:
        if task_id == omit_task_id:
            continue
        score_dirs.append(make_score_dir(base_name, task_id, passed=task_id != failed_task_id))
    return score_dirs


def blocked_fixture_status(kind: str, fixture: dict[str, Any], suite_id: str) -> dict[str, Any]:
    try:
        if kind == "missing-task":
            score_dirs = make_score_dirs(f"{suite_id}-missing-task", omit_task_id=REQUIRED_TASK_IDS[-1])
            aggregate_scores(score_dirs, AGGREGATE_ROOT / f"{suite_id}-missing-task", aggregate_id=f"{suite_id}-missing-task")
        elif kind == "duplicate-task":
            score_dirs = make_score_dirs(f"{suite_id}-duplicate-task")
            score_dirs.append(score_dirs[0])
            aggregate_scores(score_dirs, AGGREGATE_ROOT / f"{suite_id}-duplicate-task", aggregate_id=f"{suite_id}-duplicate-task")
        elif kind == "stale-score":
            score_dirs = make_score_dirs(f"{suite_id}-stale-score")
            expected = {read_json(path / "score.json")["task_id"]: canonical_hash(read_json(path / "score.json")) for path in score_dirs}
            expected[REQUIRED_TASK_IDS[0]] = "stale-score-hash"
            aggregate_scores(score_dirs, AGGREGATE_ROOT / f"{suite_id}-stale-score", aggregate_id=f"{suite_id}-stale-score", expected_score_hashes=expected)
        elif kind == "unsupported-claim":
            score_dirs = make_score_dirs(f"{suite_id}-unsupported-claim", failed_task_id=REQUIRED_TASK_IDS[0])
            aggregate_scores(score_dirs, AGGREGATE_ROOT / f"{suite_id}-unsupported-claim", aggregate_id=f"{suite_id}-unsupported-claim", claim_success=True)
        elif kind == "missing-artifact":
            missing_dir = SCORE_ROOT / f"{suite_id}-missing-artifact"
            if missing_dir.exists():
                shutil.rmtree(missing_dir)
            missing_dir.mkdir(parents=True)
            aggregate_scores([missing_dir], AGGREGATE_ROOT / f"{suite_id}-missing-artifact", aggregate_id=f"{suite_id}-missing-artifact")
        else:
            raise LiveScoreAggregateError("ERR_LIVE_SCORE_AGGREGATE_FIXTURE_FAILED", f"unknown blocked fixture kind: {kind}")
    except LiveScoreAggregateError as exc:
        if fixture.get("expected_error") != exc.code:
            raise
        return {"status": "blocked", "error": exc.to_record()}
    raise LiveScoreAggregateError("ERR_LIVE_SCORE_AGGREGATE_FIXTURE_FAILED", f"{kind} unexpectedly passed")


def run_fixture(fixture: dict[str, Any], suite_dir: Path) -> dict[str, Any]:
    fixture_id = fixture["id"]
    try:
        kind = fixture["kind"]
        if kind == "aggregate-all-passed":
            score_dirs = make_score_dirs(f"{suite_dir.name}-{fixture_id}")
            status = aggregate_scores(score_dirs, suite_dir / fixture_id, aggregate_id=fixture_id, claim_success=bool(fixture.get("claim_success", False)))
        elif kind == "aggregate-failed-not-claimed":
            score_dirs = make_score_dirs(f"{suite_dir.name}-{fixture_id}", failed_task_id=REQUIRED_TASK_IDS[0])
            status = aggregate_scores(score_dirs, suite_dir / fixture_id, aggregate_id=fixture_id)
        elif kind in {"missing-task", "duplicate-task", "stale-score", "unsupported-claim", "missing-artifact"}:
            status = blocked_fixture_status(kind, fixture, suite_dir.name)
        else:
            raise LiveScoreAggregateError("ERR_LIVE_SCORE_AGGREGATE_FIXTURE_FAILED", f"unknown fixture kind: {kind}")
        expected_status = fixture.get("expected_status")
        if expected_status is not None and status.get("status") != expected_status:
            raise LiveScoreAggregateError("ERR_LIVE_SCORE_AGGREGATE_FIXTURE_FAILED", f"expected status {expected_status}, got {status.get('status')}")
        expected_pass_count = fixture.get("expected_pass_count")
        if expected_pass_count is not None and status.get("pass_count") != expected_pass_count:
            raise LiveScoreAggregateError("ERR_LIVE_SCORE_AGGREGATE_FIXTURE_FAILED", f"expected pass_count {expected_pass_count}, got {status.get('pass_count')}")
        expected_error = fixture.get("expected_error")
        actual_error = status.get("error", {}).get("code") if isinstance(status.get("error"), dict) else None
        if expected_error is not None and actual_error != expected_error:
            raise LiveScoreAggregateError("ERR_LIVE_SCORE_AGGREGATE_FIXTURE_FAILED", f"expected error {expected_error}, got {actual_error}")
        return {"id": fixture_id, "status": "pass", "observed_status": status.get("status"), "required": fixture.get("required", True)}
    except LiveScoreAggregateError as exc:
        record = exc.to_record()
        record["fixture_id"] = fixture_id
        return {"id": fixture_id, "status": "fail", "required": fixture.get("required", True), "error": record}


def evaluate_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    suite_id = Path(out_dir).name
    suite_dir = resolve_aggregate_out(out_dir)
    if suite_dir.exists():
        sentinel = read_sentinel(suite_dir)
        if sentinel is None or sentinel.get("aggregate_id") != suite_id:
            raise LiveScoreAggregateError("ERR_LIVE_SCORE_AGGREGATE_PATH_UNSAFE", "existing live score aggregate suite is not aggregate-owned", path=suite_dir)
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
        raise LiveScoreAggregateError("ERR_LIVE_SCORE_AGGREGATE_FIXTURE_FAILED", "manifest decision is kill", path=manifest_path)
    return summary


def self_test() -> None:
    AGGREGATE_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dwm-live-score-aggregate-self-test-", dir=AGGREGATE_ROOT) as tmp:
        summary = evaluate_manifest(ROOT / "fixtures" / "v33" / "manifest.json", Path(tmp) / "live-score-aggregate-self-test")
    if summary["decision"] != "keep":
        raise LiveScoreAggregateError("ERR_LIVE_SCORE_AGGREGATE_FIXTURE_FAILED", "live score aggregate self-test manifest did not keep")
    print("dwm_live_score_aggregate self-test: pass")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", choices=["aggregate"])
    parser.add_argument("--claim-success", action="store_true")
    parser.add_argument("--expected-score-hashes")
    parser.add_argument("--manifest")
    parser.add_argument("--out")
    parser.add_argument("--score-dir", action="append")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
        elif args.manifest:
            if not args.out:
                raise LiveScoreAggregateError("ERR_LIVE_SCORE_AGGREGATE_PATH_UNSAFE", "--manifest requires --out")
            summary = evaluate_manifest(Path(args.manifest), Path(args.out))
            print(canonical_json_text({key: summary[key] for key in ["suite_id", "fixture_count", "required_fixture_count", "required_passed", "passed", "failed", "skipped", "decision"]}))
        elif args.command == "aggregate":
            if not args.out or not args.score_dir:
                raise LiveScoreAggregateError("ERR_LIVE_SCORE_AGGREGATE_PATH_UNSAFE", "aggregate requires --score-dir and --out")
            expected_hashes = read_json(Path(args.expected_score_hashes)) if args.expected_score_hashes else None
            status = aggregate_scores(
                [Path(value) for value in args.score_dir],
                resolve_aggregate_out(args.out),
                aggregate_id=Path(args.out).name,
                expected_score_hashes=expected_hashes,
                claim_success=args.claim_success,
            )
            print(canonical_json_text(status))
        else:
            parser.error("expected --self-test, --manifest, or aggregate")
    except LiveScoreAggregateError as exc:
        print(canonical_json_text(exc.to_record()), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
