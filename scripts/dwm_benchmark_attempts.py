#!/usr/bin/env python3
"""V26 benchmark attempt harness."""

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
from dwm_benchmark_tasks import TEMPLATE_PATH, TASK_ROOT, load_templates, materialize_suite, require_safe_relative_path, verify_task  # noqa: E402


TOOL = "dwm_benchmark_attempts.py"
SCHEMA_VERSION = "1.0"
ATTEMPTS_VERSION = "26.0.0"
ATTEMPT_ROOT = ROOT / "out" / "benchmark-attempts"
PLAN_PATH = ROOT / "packaging" / "dwm-benchmark-attempts.json"
SENTINEL = ".dwm_benchmark_attempts-owned.json"
SUPPORTED_ADAPTER = "scripted-fixture"


class BenchmarkAttemptsError(ValueError):
    """Structured V26 benchmark attempt failure."""

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
        raise BenchmarkAttemptsError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise BenchmarkAttemptsError(code, "path contains a symlink", path=current)


def resolve_attempt_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_BENCHMARK_ATTEMPTS_PATH_UNSAFE", message="benchmark attempt output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = ATTEMPT_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise BenchmarkAttemptsError("ERR_BENCHMARK_ATTEMPTS_PATH_UNSAFE", f"benchmark attempt output must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise BenchmarkAttemptsError("ERR_BENCHMARK_ATTEMPTS_PATH_UNSAFE", "benchmark attempt output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_BENCHMARK_ATTEMPTS_PATH_SYMLINK")
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


def prepare_out_dir(path: Path, suite_id: str, *, source: Path) -> None:
    if path.exists():
        if path.is_symlink():
            raise BenchmarkAttemptsError("ERR_BENCHMARK_ATTEMPTS_PATH_SYMLINK", "benchmark attempt output is a symlink", path=path)
        if not path.is_dir():
            raise BenchmarkAttemptsError("ERR_BENCHMARK_ATTEMPTS_PATH_UNSAFE", "benchmark attempt output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("suite_id") != suite_id:
            raise BenchmarkAttemptsError("ERR_BENCHMARK_ATTEMPTS_PATH_UNSAFE", "existing benchmark attempt output is not attempt-owned", path=path)
        shutil.rmtree(path)
    ATTEMPT_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(
        path / SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "attempts_version": ATTEMPTS_VERSION,
            "suite_id": suite_id,
            "source_path": rel(source),
            "created_at": now_utc(),
        },
        root=path,
    )


def validate_plan(plan: dict[str, Any], *, path: Path | str = PLAN_PATH) -> dict[str, Any]:
    if plan.get("schema_version") != SCHEMA_VERSION:
        raise BenchmarkAttemptsError("ERR_BENCHMARK_ATTEMPTS_PLAN_INVALID", "unsupported attempt plan schema", path=path)
    if plan.get("adapter") != SUPPORTED_ADAPTER:
        raise BenchmarkAttemptsError("ERR_BENCHMARK_ATTEMPTS_PLAN_INVALID", "unsupported attempt adapter", path=path)
    tasks = plan.get("tasks")
    if not isinstance(tasks, list) or [task.get("id") for task in tasks if isinstance(task, dict)] != REQUIRED_TASK_IDS:
        raise BenchmarkAttemptsError("ERR_BENCHMARK_ATTEMPTS_STALE_PLAN", "attempt plan must match benchmark task order", path=path)
    for task in tasks:
        changes = task.get("changes")
        if not isinstance(changes, list) or not changes:
            raise BenchmarkAttemptsError("ERR_BENCHMARK_ATTEMPTS_PLAN_INVALID", f"{task.get('id')} must define changes", path=path)
        for change in changes:
            if (
                not isinstance(change, dict)
                or not isinstance(change.get("path"), str)
                or not isinstance(change.get("replace"), str)
                or not isinstance(change.get("with"), str)
            ):
                raise BenchmarkAttemptsError("ERR_BENCHMARK_ATTEMPTS_PLAN_INVALID", f"{task.get('id')} change is malformed", path=path)
            try:
                require_safe_relative_path(change["path"])
            except Exception as exc:
                raise BenchmarkAttemptsError("ERR_BENCHMARK_ATTEMPTS_UNSAFE_PATH", "attempt change path is unsafe", path=change["path"]) from exc
    return plan


def load_plan(path: Path = PLAN_PATH) -> dict[str, Any]:
    return validate_plan(read_json(path), path=path)


def ensure_materialized_tasks(path: Path) -> None:
    sentinel = path / ".dwm_benchmark_tasks-owned.json"
    if not sentinel.is_file() or sentinel.is_symlink():
        raise BenchmarkAttemptsError("ERR_BENCHMARK_ATTEMPTS_MISSING_TASKS", "materialized task suite is missing", path=path)
    status = read_json(path / "status.json")
    if status.get("task_count") != len(REQUIRED_TASK_IDS):
        raise BenchmarkAttemptsError("ERR_BENCHMARK_ATTEMPTS_MISSING_TASKS", "materialized task suite is incomplete", path=path)


def apply_change(task_dir: Path, change: dict[str, str]) -> dict[str, Any]:
    relative = require_safe_relative_path(change["path"])
    target = task_dir / "workspace" / relative
    if not target.is_file() or target.is_symlink():
        raise BenchmarkAttemptsError("ERR_BENCHMARK_ATTEMPTS_MISSING_TASKS", "attempt target file is missing", path=target)
    before = target.read_text()
    if change["replace"] not in before:
        raise BenchmarkAttemptsError("ERR_BENCHMARK_ATTEMPTS_STALE_PLAN", "attempt replacement text was not found", path=target)
    after = before.replace(change["replace"], change["with"])
    target.write_text(after)
    return {
        "path": change["path"],
        "before_hash": canonical_hash(before),
        "after_hash": canonical_hash(after),
    }


def run_attempt_suite(
    out_dir: Path,
    *,
    suite_id: str,
    plan: dict[str, Any] | None = None,
    expected_plan_hash: str | None = None,
) -> dict[str, Any]:
    plan = load_plan() if plan is None else validate_plan(plan, path="<synthetic>")
    plan_hash = canonical_hash(plan)
    if expected_plan_hash is not None and expected_plan_hash != plan_hash:
        raise BenchmarkAttemptsError("ERR_BENCHMARK_ATTEMPTS_STALE_PLAN", "expected attempt plan hash does not match current plan")
    prepare_out_dir(out_dir, suite_id, source=PLAN_PATH)
    tasks_dir = out_dir / "materialized"
    materialize_suite(tasks_dir, suite_id="materialized")
    ensure_materialized_tasks(tasks_dir)
    templates_by_id = {task["id"]: task for task in load_templates()["tasks"]}
    results: list[dict[str, Any]] = []
    for task_plan in plan["tasks"]:
        task_id = task_plan["id"]
        task_dir = tasks_dir / "tasks" / task_id
        attempt_dir = out_dir / "attempts" / task_id
        attempt_dir.mkdir(parents=True, exist_ok=True)
        changes = [apply_change(task_dir, change) for change in task_plan["changes"]]
        verification = verify_task(task_dir, templates_by_id[task_id])
        attempt = {
            "task_id": task_id,
            "adapter": SUPPORTED_ADAPTER,
            "status": "solved" if verification["status"] == "solved" else "attempted",
            "change_count": len(changes),
            "started_at": now_utc(),
            "completed_at": now_utc(),
        }
        write_json_atomic(attempt_dir / "attempt.json", attempt, root=out_dir)
        write_json_atomic(attempt_dir / "changes.json", {"changes": changes}, root=out_dir)
        write_json_atomic(attempt_dir / "verification.json", verification, root=out_dir)
        results.append({"task_id": task_id, "status": verification["status"], "change_count": len(changes)})
    solved_count = sum(1 for result in results if result["status"] == "solved")
    status = {
        "status": "attempted",
        "suite_id": suite_id,
        "adapter": SUPPORTED_ADAPTER,
        "task_count": len(results),
        "solved_count": solved_count,
        "source_hashes": {
            "plan": plan_hash,
            "templates": canonical_hash(load_templates()),
        },
    }
    write_json_atomic(out_dir / "status.json", status, root=out_dir)
    write_json_atomic(out_dir / "ledger.json", {"status": "verified", "task_count": len(results), "tasks": results}, root=out_dir)
    return status


def verify_attempt_ledger(out_dir: Path) -> dict[str, Any]:
    status_path = out_dir / "status.json"
    ledger_path = out_dir / "ledger.json"
    if not status_path.is_file() or not ledger_path.is_file():
        raise BenchmarkAttemptsError("ERR_BENCHMARK_ATTEMPTS_MISSING_TASKS", "attempt ledger artifacts are missing", path=out_dir)
    status = read_json(status_path)
    ledger = read_json(ledger_path)
    if status.get("source_hashes", {}).get("plan") != canonical_hash(load_plan()):
        raise BenchmarkAttemptsError("ERR_BENCHMARK_ATTEMPTS_STALE_PLAN", "attempt plan hash is stale", path=status_path)
    if ledger.get("task_count") != len(REQUIRED_TASK_IDS):
        raise BenchmarkAttemptsError("ERR_BENCHMARK_ATTEMPTS_MISSING_TASKS", "attempt ledger task count is incomplete", path=ledger_path)
    missing = []
    for task_id in REQUIRED_TASK_IDS:
        attempt_dir = out_dir / "attempts" / task_id
        for name in ["attempt.json", "changes.json", "verification.json"]:
            if not (attempt_dir / name).is_file():
                missing.append(f"{task_id}/{name}")
    if missing:
        raise BenchmarkAttemptsError("ERR_BENCHMARK_ATTEMPTS_MISSING_TASKS", f"attempt ledger is missing artifacts: {missing[:3]}", path=out_dir)
    return {
        "status": "verified",
        "task_count": ledger["task_count"],
        "solved_count": status["solved_count"],
    }


def blocked_fixture_status(kind: str, fixture: dict[str, Any]) -> dict[str, Any]:
    try:
        if kind == "missing-tasks":
            verify_attempt_ledger(ATTEMPT_ROOT / "fixture-missing-tasks")
        elif kind == "stale-plan":
            run_attempt_suite(
                ATTEMPT_ROOT / "fixture-stale-plan",
                suite_id="fixture-stale-plan",
                expected_plan_hash="stale-plan-hash",
            )
        elif kind == "unsafe-path":
            broken = json.loads(json.dumps(load_plan()))
            broken["tasks"][0]["changes"][0]["path"] = "../escape.py"
            run_attempt_suite(ATTEMPT_ROOT / "fixture-unsafe-path", suite_id="fixture-unsafe-path", plan=broken)
        else:
            raise BenchmarkAttemptsError("ERR_BENCHMARK_ATTEMPTS_FIXTURE_FAILED", f"unknown blocked fixture kind: {kind}")
    except BenchmarkAttemptsError as exc:
        if fixture.get("expected_error") != exc.code:
            raise
        return {"status": "blocked", "error": exc.to_record()}
    raise BenchmarkAttemptsError("ERR_BENCHMARK_ATTEMPTS_FIXTURE_FAILED", f"{kind} unexpectedly passed")


def run_fixture(fixture: dict[str, Any], suite_dir: Path) -> dict[str, Any]:
    fixture_id = fixture["id"]
    try:
        kind = fixture["kind"]
        if kind == "attempt-suite":
            status = run_attempt_suite(suite_dir / fixture_id, suite_id=fixture_id)
        elif kind == "verify-ledger":
            run_attempt_suite(suite_dir / fixture_id, suite_id=fixture_id)
            status = verify_attempt_ledger(suite_dir / fixture_id)
        elif kind in {"missing-tasks", "stale-plan", "unsafe-path"}:
            status = blocked_fixture_status(kind, fixture)
        else:
            raise BenchmarkAttemptsError("ERR_BENCHMARK_ATTEMPTS_FIXTURE_FAILED", f"unknown fixture kind: {kind}")
        expected_status = fixture.get("expected_status")
        if expected_status is not None and status.get("status") != expected_status:
            raise BenchmarkAttemptsError("ERR_BENCHMARK_ATTEMPTS_FIXTURE_FAILED", f"expected status {expected_status}, got {status.get('status')}")
        expected_task_count = fixture.get("expected_task_count")
        if expected_task_count is not None and status.get("task_count") != expected_task_count:
            raise BenchmarkAttemptsError("ERR_BENCHMARK_ATTEMPTS_FIXTURE_FAILED", f"expected task_count {expected_task_count}, got {status.get('task_count')}")
        expected_solved_count = fixture.get("expected_solved_count")
        if expected_solved_count is not None and status.get("solved_count") != expected_solved_count:
            raise BenchmarkAttemptsError("ERR_BENCHMARK_ATTEMPTS_FIXTURE_FAILED", f"expected solved_count {expected_solved_count}, got {status.get('solved_count')}")
        expected_error = fixture.get("expected_error")
        actual_error = status.get("error", {}).get("code") if isinstance(status.get("error"), dict) else None
        if expected_error is not None and actual_error != expected_error:
            raise BenchmarkAttemptsError("ERR_BENCHMARK_ATTEMPTS_FIXTURE_FAILED", f"expected error {expected_error}, got {actual_error}")
        return {"id": fixture_id, "status": "pass", "required": fixture.get("required", True)}
    except BenchmarkAttemptsError as exc:
        record = exc.to_record()
        record["fixture_id"] = fixture_id
        return {"id": fixture_id, "status": "fail", "required": fixture.get("required", True), "error": record}


def evaluate_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    suite_id = Path(out_dir).name
    suite_dir = resolve_attempt_out(out_dir)
    if suite_dir.exists():
        sentinel = read_sentinel(suite_dir)
        if sentinel is None or sentinel.get("suite_id") != suite_id:
            raise BenchmarkAttemptsError("ERR_BENCHMARK_ATTEMPTS_PATH_UNSAFE", "existing benchmark attempt suite is not attempt-owned", path=suite_dir)
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
        "source_hashes": {
            "manifest": canonical_hash(manifest),
            "plan": canonical_hash(load_plan()),
        },
    }
    write_json_atomic(suite_dir / "summary.json", summary, root=suite_dir)
    if summary["decision"] != "keep":
        raise BenchmarkAttemptsError("ERR_BENCHMARK_ATTEMPTS_FIXTURE_FAILED", "manifest decision is kill", path=manifest_path)
    return summary


def self_test() -> None:
    ATTEMPT_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dwm-benchmark-attempts-self-test-", dir=ATTEMPT_ROOT) as tmp:
        summary = evaluate_manifest(ROOT / "fixtures" / "v26" / "manifest.json", Path(tmp) / "benchmark-attempts-self-test")
    if summary["decision"] != "keep":
        raise BenchmarkAttemptsError("ERR_BENCHMARK_ATTEMPTS_FIXTURE_FAILED", "benchmark attempts self-test manifest did not keep")
    print("dwm_benchmark_attempts self-test: pass")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", choices=["attempt", "verify"])
    parser.add_argument("--expected-plan-hash")
    parser.add_argument("--manifest")
    parser.add_argument("--out")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
        elif args.manifest:
            if not args.out:
                raise BenchmarkAttemptsError("ERR_BENCHMARK_ATTEMPTS_PATH_UNSAFE", "--manifest requires --out")
            summary = evaluate_manifest(Path(args.manifest), Path(args.out))
            print(canonical_json_text({key: summary[key] for key in ["suite_id", "fixture_count", "required_fixture_count", "required_passed", "passed", "failed", "skipped", "decision"]}))
        elif args.command == "attempt":
            if not args.out:
                raise BenchmarkAttemptsError("ERR_BENCHMARK_ATTEMPTS_PATH_UNSAFE", "attempt requires --out")
            print(canonical_json_text(run_attempt_suite(resolve_attempt_out(args.out), suite_id=Path(args.out).name, expected_plan_hash=args.expected_plan_hash)))
        elif args.command == "verify":
            if not args.out:
                raise BenchmarkAttemptsError("ERR_BENCHMARK_ATTEMPTS_PATH_UNSAFE", "verify requires --out")
            print(canonical_json_text(verify_attempt_ledger(resolve_attempt_out(args.out))))
        else:
            parser.error("expected --self-test, --manifest, attempt, or verify")
    except BenchmarkAttemptsError as exc:
        print(canonical_json_text(exc.to_record()), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
