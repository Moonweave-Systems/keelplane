#!/usr/bin/env python3
"""V25 benchmark task materializer."""

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

from compile_workflow import canonical_hash, canonical_json_text, read_json, write_json_atomic, write_text_atomic  # noqa: E402
from dwm_benchmark import REGISTRY_PATH, REQUIRED_TASK_IDS, validate_corpus  # noqa: E402


TOOL = "dwm_benchmark_tasks.py"
SCHEMA_VERSION = "1.0"
TASKS_VERSION = "25.0.0"
TASK_ROOT = ROOT / "out" / "benchmark-tasks"
TEMPLATE_PATH = ROOT / "packaging" / "dwm-benchmark-tasks.json"
SENTINEL = ".dwm_benchmark_tasks-owned.json"


class BenchmarkTasksError(ValueError):
    """Structured V25 benchmark task failure."""

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
        raise BenchmarkTasksError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise BenchmarkTasksError(code, "path contains a symlink", path=current)


def resolve_task_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_BENCHMARK_TASKS_PATH_UNSAFE", message="benchmark task output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = TASK_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise BenchmarkTasksError("ERR_BENCHMARK_TASKS_PATH_UNSAFE", f"benchmark task output must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise BenchmarkTasksError("ERR_BENCHMARK_TASKS_PATH_UNSAFE", "benchmark task output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_BENCHMARK_TASKS_PATH_SYMLINK")
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
            raise BenchmarkTasksError("ERR_BENCHMARK_TASKS_PATH_SYMLINK", "benchmark task output is a symlink", path=path)
        if not path.is_dir():
            raise BenchmarkTasksError("ERR_BENCHMARK_TASKS_PATH_UNSAFE", "benchmark task output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("suite_id") != suite_id:
            raise BenchmarkTasksError("ERR_BENCHMARK_TASKS_PATH_UNSAFE", "existing benchmark task output is not task-owned", path=path)
        shutil.rmtree(path)
    TASK_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(
        path / SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "tasks_version": TASKS_VERSION,
            "suite_id": suite_id,
            "source_path": rel(source),
            "created_at": now_utc(),
        },
        root=path,
    )


def require_safe_relative_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise BenchmarkTasksError("ERR_BENCHMARK_TASKS_UNSAFE_PATH", "task file path must be a safe relative path", path=value)
    return path


def validate_templates(templates: dict[str, Any], *, path: Path | str = TEMPLATE_PATH) -> dict[str, Any]:
    if templates.get("schema_version") != SCHEMA_VERSION:
        raise BenchmarkTasksError("ERR_BENCHMARK_TASKS_TEMPLATE_INVALID", "unsupported benchmark task template schema", path=path)
    tasks = templates.get("tasks")
    if not isinstance(tasks, list) or [task.get("id") for task in tasks if isinstance(task, dict)] != REQUIRED_TASK_IDS:
        raise BenchmarkTasksError("ERR_BENCHMARK_TASKS_CORPUS_MISMATCH", "benchmark task templates must match V23 corpus task order", path=path)
    corpus = validate_corpus(read_json(REGISTRY_PATH), path=REGISTRY_PATH)
    corpus_ids = [task["id"] for task in corpus["tasks"]]
    if [task["id"] for task in tasks] != corpus_ids:
        raise BenchmarkTasksError("ERR_BENCHMARK_TASKS_CORPUS_MISMATCH", "benchmark task templates do not match benchmark corpus", path=path)
    for task in tasks:
        if not isinstance(task, dict):
            raise BenchmarkTasksError("ERR_BENCHMARK_TASKS_TEMPLATE_INVALID", "task template must be an object", path=path)
        if not isinstance(task.get("prompt"), str) or not task["prompt"].strip():
            raise BenchmarkTasksError("ERR_BENCHMARK_TASKS_TEMPLATE_INVALID", "task prompt must be non-empty", path=path)
        files = task.get("files")
        checks = task.get("verifier_checks")
        if not isinstance(files, list) or not files:
            raise BenchmarkTasksError("ERR_BENCHMARK_TASKS_TEMPLATE_INVALID", f"{task['id']} must define files", path=path)
        if not isinstance(checks, list) or not checks:
            raise BenchmarkTasksError("ERR_BENCHMARK_TASKS_TEMPLATE_INVALID", f"{task['id']} must define verifier checks", path=path)
        for file_record in files:
            if not isinstance(file_record, dict) or not isinstance(file_record.get("path"), str) or not isinstance(file_record.get("content"), str):
                raise BenchmarkTasksError("ERR_BENCHMARK_TASKS_TEMPLATE_INVALID", f"{task['id']} file record is malformed", path=path)
            require_safe_relative_path(file_record["path"])
        for check in checks:
            if (
                not isinstance(check, dict)
                or check.get("type") != "file_contains"
                or not isinstance(check.get("id"), str)
                or not isinstance(check.get("path"), str)
                or not isinstance(check.get("text"), str)
            ):
                raise BenchmarkTasksError("ERR_BENCHMARK_TASKS_TEMPLATE_INVALID", f"{task['id']} verifier check is malformed", path=path)
            require_safe_relative_path(check["path"])
    return templates


def load_templates(path: Path = TEMPLATE_PATH) -> dict[str, Any]:
    return validate_templates(read_json(path), path=path)


def verify_task(task_dir: Path, task: dict[str, Any]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    for check in task["verifier_checks"]:
        target = task_dir / "workspace" / check["path"]
        if not target.is_file() or target.is_symlink():
            passed = False
        else:
            passed = check["text"] in target.read_text()
        checks.append(
            {
                "id": check["id"],
                "type": check["type"],
                "path": check["path"],
                "passed": passed,
            }
        )
    passed_count = sum(1 for check in checks if check["passed"])
    status = "solved" if passed_count == len(checks) else "needs-solution"
    return {
        "task_id": task["id"],
        "status": status,
        "passed": passed_count,
        "failed": len(checks) - passed_count,
        "checks": checks,
    }


def materialize_task(task: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    task_dir = out_dir / "tasks" / task["id"]
    workspace_dir = task_dir / "workspace"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    for file_record in task["files"]:
        relative = require_safe_relative_path(file_record["path"])
        target = workspace_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        write_text_atomic(target, file_record["content"], root=task_dir)
    write_text_atomic(task_dir / "prompt.md", task["prompt"] + "\n", root=task_dir)
    write_json_atomic(task_dir / "task.json", {"id": task["id"], "prompt": task["prompt"]}, root=task_dir)
    write_json_atomic(task_dir / "verifier.json", {"checks": task["verifier_checks"]}, root=task_dir)
    initial = verify_task(task_dir, task)
    write_json_atomic(task_dir / "initial-verification.json", initial, root=task_dir)
    return initial


def materialize_suite(
    out_dir: Path,
    *,
    suite_id: str,
    templates: dict[str, Any] | None = None,
    expected_template_hash: str | None = None,
) -> dict[str, Any]:
    templates = load_templates() if templates is None else validate_templates(templates, path="<synthetic>")
    template_hash = canonical_hash(templates)
    if expected_template_hash is not None and expected_template_hash != template_hash:
        raise BenchmarkTasksError("ERR_BENCHMARK_TASKS_STALE_TEMPLATE", "expected template hash does not match current templates")
    prepare_out_dir(out_dir, suite_id, source=TEMPLATE_PATH)
    task_results = [materialize_task(task, out_dir) for task in templates["tasks"]]
    needs_solution = sum(1 for result in task_results if result["status"] == "needs-solution")
    status = {
        "status": "materialized",
        "suite_id": suite_id,
        "task_count": len(task_results),
        "initial_needs_solution": needs_solution,
        "source_hashes": {
            "templates": template_hash,
            "corpus": canonical_hash(read_json(REGISTRY_PATH)),
        },
    }
    write_json_atomic(out_dir / "status.json", status, root=out_dir)
    write_json_atomic(out_dir / "verification.json", {"status": "verified", "task_count": len(task_results), "tasks": task_results}, root=out_dir)
    return status


def verify_materialized_suite(out_dir: Path) -> dict[str, Any]:
    status_path = out_dir / "status.json"
    verification_path = out_dir / "verification.json"
    if not status_path.is_file() or not verification_path.is_file():
        raise BenchmarkTasksError("ERR_BENCHMARK_TASKS_ARTIFACT_MISSING", "materialized suite artifacts are missing", path=out_dir)
    status = read_json(status_path)
    verification = read_json(verification_path)
    if status.get("source_hashes", {}).get("templates") != canonical_hash(load_templates()):
        raise BenchmarkTasksError("ERR_BENCHMARK_TASKS_STALE_TEMPLATE", "materialized template hash is stale", path=status_path)
    if verification.get("task_count") != len(REQUIRED_TASK_IDS):
        raise BenchmarkTasksError("ERR_BENCHMARK_TASKS_CORPUS_MISMATCH", "verification task count does not match corpus", path=verification_path)
    return {
        "status": "verified",
        "task_count": verification["task_count"],
        "initial_needs_solution": status["initial_needs_solution"],
    }


def blocked_fixture_status(kind: str, fixture: dict[str, Any]) -> dict[str, Any]:
    try:
        if kind == "corpus-mismatch":
            broken = {"schema_version": SCHEMA_VERSION, "tasks": load_templates()["tasks"][:-1]}
            materialize_suite(TASK_ROOT / "fixture-corpus-mismatch", suite_id="fixture-corpus-mismatch", templates=broken)
        elif kind == "unsafe-path":
            broken = json.loads(json.dumps(load_templates()))
            broken["tasks"][0]["files"][0]["path"] = "../escape.py"
            materialize_suite(TASK_ROOT / "fixture-unsafe-path", suite_id="fixture-unsafe-path", templates=broken)
        elif kind == "stale-template":
            materialize_suite(
                TASK_ROOT / "fixture-stale-template",
                suite_id="fixture-stale-template",
                expected_template_hash="stale-template-hash",
            )
        else:
            raise BenchmarkTasksError("ERR_BENCHMARK_TASKS_FIXTURE_FAILED", f"unknown blocked fixture kind: {kind}")
    except BenchmarkTasksError as exc:
        if fixture.get("expected_error") != exc.code:
            raise
        return {"status": "blocked", "error": exc.to_record()}
    raise BenchmarkTasksError("ERR_BENCHMARK_TASKS_FIXTURE_FAILED", f"{kind} unexpectedly passed")


def run_fixture(fixture: dict[str, Any], suite_dir: Path) -> dict[str, Any]:
    fixture_id = fixture["id"]
    try:
        kind = fixture["kind"]
        if kind == "materialize-suite":
            status = materialize_suite(suite_dir / fixture_id, suite_id=fixture_id)
        elif kind == "verify-initial":
            status = materialize_suite(suite_dir / fixture_id, suite_id=fixture_id)
            status = verify_materialized_suite(suite_dir / fixture_id)
        elif kind in {"corpus-mismatch", "unsafe-path", "stale-template"}:
            status = blocked_fixture_status(kind, fixture)
        else:
            raise BenchmarkTasksError("ERR_BENCHMARK_TASKS_FIXTURE_FAILED", f"unknown fixture kind: {kind}")
        expected_status = fixture.get("expected_status")
        if expected_status is not None and status.get("status") != expected_status:
            raise BenchmarkTasksError("ERR_BENCHMARK_TASKS_FIXTURE_FAILED", f"expected status {expected_status}, got {status.get('status')}")
        expected_task_count = fixture.get("expected_task_count")
        if expected_task_count is not None and status.get("task_count") != expected_task_count:
            raise BenchmarkTasksError("ERR_BENCHMARK_TASKS_FIXTURE_FAILED", f"expected task_count {expected_task_count}, got {status.get('task_count')}")
        expected_error = fixture.get("expected_error")
        actual_error = status.get("error", {}).get("code") if isinstance(status.get("error"), dict) else None
        if expected_error is not None and actual_error != expected_error:
            raise BenchmarkTasksError("ERR_BENCHMARK_TASKS_FIXTURE_FAILED", f"expected error {expected_error}, got {actual_error}")
        return {"id": fixture_id, "status": "pass", "required": fixture.get("required", True)}
    except BenchmarkTasksError as exc:
        record = exc.to_record()
        record["fixture_id"] = fixture_id
        return {"id": fixture_id, "status": "fail", "required": fixture.get("required", True), "error": record}


def evaluate_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    suite_id = Path(out_dir).name
    suite_dir = resolve_task_out(out_dir)
    if suite_dir.exists():
        sentinel = read_sentinel(suite_dir)
        if sentinel is None or sentinel.get("suite_id") != suite_id:
            raise BenchmarkTasksError("ERR_BENCHMARK_TASKS_PATH_UNSAFE", "existing benchmark task suite is not task-owned", path=suite_dir)
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
            "templates": canonical_hash(load_templates()),
        },
    }
    write_json_atomic(suite_dir / "summary.json", summary, root=suite_dir)
    if summary["decision"] != "keep":
        raise BenchmarkTasksError("ERR_BENCHMARK_TASKS_FIXTURE_FAILED", "manifest decision is kill", path=manifest_path)
    return summary


def self_test() -> None:
    TASK_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dwm-benchmark-tasks-self-test-", dir=TASK_ROOT) as tmp:
        summary = evaluate_manifest(ROOT / "fixtures" / "v25" / "manifest.json", Path(tmp) / "benchmark-tasks-self-test")
    if summary["decision"] != "keep":
        raise BenchmarkTasksError("ERR_BENCHMARK_TASKS_FIXTURE_FAILED", "benchmark tasks self-test manifest did not keep")
    print("dwm_benchmark_tasks self-test: pass")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", choices=["materialize", "verify"])
    parser.add_argument("--expected-template-hash")
    parser.add_argument("--manifest")
    parser.add_argument("--out")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
        elif args.manifest:
            if not args.out:
                raise BenchmarkTasksError("ERR_BENCHMARK_TASKS_PATH_UNSAFE", "--manifest requires --out")
            summary = evaluate_manifest(Path(args.manifest), Path(args.out))
            print(canonical_json_text({key: summary[key] for key in ["suite_id", "fixture_count", "required_fixture_count", "required_passed", "passed", "failed", "skipped", "decision"]}))
        elif args.command == "materialize":
            if not args.out:
                raise BenchmarkTasksError("ERR_BENCHMARK_TASKS_PATH_UNSAFE", "materialize requires --out")
            status = materialize_suite(
                resolve_task_out(args.out),
                suite_id=Path(args.out).name,
                expected_template_hash=args.expected_template_hash,
            )
            print(canonical_json_text(status))
        elif args.command == "verify":
            if not args.out:
                raise BenchmarkTasksError("ERR_BENCHMARK_TASKS_PATH_UNSAFE", "verify requires --out")
            print(canonical_json_text(verify_materialized_suite(resolve_task_out(args.out))))
        else:
            parser.error("expected --self-test, --manifest, materialize, or verify")
    except BenchmarkTasksError as exc:
        print(canonical_json_text(exc.to_record()), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
