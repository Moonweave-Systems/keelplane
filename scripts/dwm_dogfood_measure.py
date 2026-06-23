#!/usr/bin/env python3
"""V56 measured local dogfood sample runner."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from compile_workflow import canonical_hash, canonical_json_text, read_json, write_json_atomic, write_text_atomic  # noqa: E402
from dwm_dogfood_attempts import record_attempts  # noqa: E402
from dwm_dogfood_corpus import DOGFOOD_ROOT, REQUIRED_MODES, build_corpus, default_tasks  # noqa: E402


TOOL = "dwm_dogfood_measure.py"
SCHEMA_VERSION = "1.0"
MEASURE_VERSION = "56.0.0"
MEASURE_ROOT = ROOT / "out" / "dogfood-measurements"
ATTEMPT_ROOT = ROOT / "out" / "dogfood-attempts"
SENTINEL = ".dwm_dogfood_measure-owned.json"
DEFAULT_TASK_ID = "release-contract-count-sync"
DEFAULT_MODE = "dwm-controlled"


class DogfoodMeasureError(ValueError):
    """Structured V56 dogfood measurement failure."""

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
        raise DogfoodMeasureError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise DogfoodMeasureError(code, "path contains a symlink", path=current)


def resolve_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_DOGFOOD_MEASURE_PATH_UNSAFE", message="dogfood measurement output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = MEASURE_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise DogfoodMeasureError("ERR_DOGFOOD_MEASURE_PATH_UNSAFE", f"dogfood measurement output must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise DogfoodMeasureError("ERR_DOGFOOD_MEASURE_PATH_UNSAFE", "dogfood measurement output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_DOGFOOD_MEASURE_PATH_SYMLINK")
    return resolved


def read_sentinel(path: Path) -> dict[str, Any] | None:
    sentinel = path / SENTINEL
    if not sentinel.is_file() or sentinel.is_symlink():
        return None
    try:
        data = read_json(sentinel)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def prepare_out_dir(path: Path, measurement_id: str, *, source: Path) -> None:
    if path.exists():
        if path.is_symlink():
            raise DogfoodMeasureError("ERR_DOGFOOD_MEASURE_PATH_SYMLINK", "dogfood measurement output is a symlink", path=path)
        if not path.is_dir():
            raise DogfoodMeasureError("ERR_DOGFOOD_MEASURE_PATH_UNSAFE", "dogfood measurement output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("measurement_id") != measurement_id:
            raise DogfoodMeasureError("ERR_DOGFOOD_MEASURE_PATH_UNSAFE", "existing dogfood measurement output is not measurement-owned", path=path)
        shutil.rmtree(path)
    MEASURE_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(
        path / SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "measure_version": MEASURE_VERSION,
            "measurement_id": measurement_id,
            "source_path": rel(source),
            "created_at": now_utc(),
        },
        root=path,
    )


def task_by_id(task_id: str) -> dict[str, Any]:
    for task in default_tasks():
        if task["id"] == task_id:
            return task
    raise DogfoodMeasureError("ERR_DOGFOOD_MEASURE_UNKNOWN_TASK", "task id is not in the dogfood corpus", path=task_id)


def validate_mode(mode: str) -> str:
    if mode not in REQUIRED_MODES:
        raise DogfoodMeasureError("ERR_DOGFOOD_MEASURE_MODE_UNSAFE", "measurement mode is not supported", path=mode)
    if mode == "direct-codex":
        raise DogfoodMeasureError("ERR_DOGFOOD_MEASURE_DIRECT_REQUIRES_GATE", "direct-codex measurement requires a human-gated live attempt")
    return mode


def safe_command(command: str) -> list[str]:
    if any(token in command for token in [";", "&&", "||", "`", "$(", ">", "<", "|"]):
        raise DogfoodMeasureError("ERR_DOGFOOD_MEASURE_COMMAND_UNSAFE", "verification command contains shell control syntax", path=command)
    parts = command.split()
    if len(parts) < 2 or parts[0] != "python" or not parts[1].startswith("scripts/"):
        raise DogfoodMeasureError("ERR_DOGFOOD_MEASURE_COMMAND_UNSAFE", "verification command must be a repo-local python scripts command", path=command)
    return [sys.executable, *parts[1:]]


def render_evidence(task: dict[str, Any], mode: str, result: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# DWM Dogfood Measurement Evidence",
            "",
            f"task_id: {task['id']}",
            f"mode: {mode}",
            f"command: {' '.join(result['command'])}",
            f"returncode: {result['returncode']}",
            f"elapsed_seconds: {result['elapsed_seconds']}",
            f"recorded_at: {result['recorded_at']}",
            "",
            "## stdout",
            "",
            result["stdout"],
            "",
            "## stderr",
            "",
            result["stderr"],
            "",
        ]
    )


def run_verification(task: dict[str, Any], mode: str) -> dict[str, Any]:
    commands = task["verification_commands"]
    if len(commands) != 1:
        raise DogfoodMeasureError("ERR_DOGFOOD_MEASURE_COMMAND_UNSAFE", "V56 sample supports one verification command per task", path=task["id"])
    command = safe_command(commands[0])
    started = time.perf_counter()
    completed = subprocess.run(command, cwd=ROOT, check=False, capture_output=True, text=True, timeout=60)
    elapsed = round(time.perf_counter() - started, 6)
    return {
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
        "elapsed_seconds": elapsed,
        "recorded_at": now_utc(),
        "verification_passed": completed.returncode == 0,
    }


def render_summary(record: dict[str, Any]) -> str:
    lines = [
        "# DWM Dogfood Measurement",
        "",
        f"- measurement: `{record['measurement_id']}`",
        f"- task: `{record['task_id']}`",
        f"- mode: `{record['mode']}`",
        f"- verification passed: `{record['verification_passed']}`",
        f"- elapsed seconds: `{record['elapsed_seconds']}`",
        f"- ledger: `{record['ledger_path']}`",
        "- claim policy: local measurement only; not a benchmark superiority claim",
        "",
    ]
    return "\n".join(lines)


def measure(out_dir: Path, *, task_id: str = DEFAULT_TASK_ID, mode: str = DEFAULT_MODE) -> dict[str, Any]:
    out_dir = resolve_out(out_dir)
    measurement_id = out_dir.name
    mode = validate_mode(mode)
    task = task_by_id(task_id)
    prepare_out_dir(out_dir, measurement_id, source=Path("default-dogfood-tasks"))
    corpus_dir = DOGFOOD_ROOT / f"{measurement_id}-corpus"
    corpus = build_corpus(default_tasks(), corpus_dir, corpus_id=corpus_dir.name, source=Path("default-dogfood-tasks"))
    result = run_verification(task, mode)
    evidence_dir = out_dir / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    evidence_path = evidence_dir / f"{task_id}-{mode}.md"
    write_text_atomic(evidence_path, render_evidence(task, mode, result), root=out_dir)
    attempts = {
        "attempts": [
            {
                "task_id": task_id,
                "mode": mode,
                "evidence_path": rel(evidence_path),
                "metrics": {
                    "elapsed_seconds": result["elapsed_seconds"],
                    "interruptions": 0,
                    "verification_passed": result["verification_passed"],
                    "command_count": 1,
                },
                "summary": "measured local DWM-controlled verification sample",
                "recorded_at": result["recorded_at"],
            }
        ]
    }
    attempts_path = out_dir / "attempts.json"
    write_json_atomic(attempts_path, attempts, root=out_dir)
    ledger_dir = ATTEMPT_ROOT / f"{measurement_id}-ledger"
    ledger = record_attempts(corpus_dir, attempts_path, ledger_dir)
    record = {
        "tool": TOOL,
        "schema_version": SCHEMA_VERSION,
        "measure_version": MEASURE_VERSION,
        "status": "dogfood-measurement-recorded",
        "decision": "measured-local-sample",
        "measurement_id": measurement_id,
        "task_id": task_id,
        "mode": mode,
        "verification_passed": result["verification_passed"],
        "elapsed_seconds": result["elapsed_seconds"],
        "evidence_path": rel(evidence_path),
        "attempts_path": rel(attempts_path),
        "corpus_path": rel(corpus_dir),
        "ledger_path": rel(ledger_dir),
        "source_hashes": {
            "corpus": canonical_hash(corpus),
            "attempts": canonical_hash(attempts),
            "ledger": canonical_hash(ledger),
            "evidence": canonical_hash(evidence_path.read_text()),
        },
        "external_claim_policy": "local dogfood evidence only; not an external benchmark authority",
    }
    write_json_atomic(out_dir / "measurement.json", record, root=out_dir)
    write_json_atomic(out_dir / "status.json", record, root=out_dir)
    write_text_atomic(out_dir / "README.md", render_summary(record), root=out_dir)
    return record


def blocked_fixture_status(kind: str, fixture: dict[str, Any], suite_dir: Path) -> dict[str, Any]:
    try:
        if kind == "direct-requires-gate":
            measure(suite_dir / kind, mode="direct-codex")
        elif kind == "unknown-task":
            measure(suite_dir / kind, task_id="unknown-task")
        elif kind == "unsafe-command":
            tasks = default_tasks()
            tasks[-1]["verification_commands"] = ["python scripts/check_contract.py --self-test && echo unsafe"]
            corpus_dir = DOGFOOD_ROOT / f"{suite_dir.name}-unsafe-command-corpus"
            build_corpus(tasks, corpus_dir, corpus_id=corpus_dir.name, source=Path("fixture"))
            safe_command(tasks[-1]["verification_commands"][0])
        else:
            raise DogfoodMeasureError("ERR_DOGFOOD_MEASURE_FIXTURE_FAILED", f"unknown blocked fixture kind: {kind}")
    except DogfoodMeasureError as exc:
        if fixture.get("expected_error") != exc.code:
            raise
        return {"status": "blocked", "error": exc.to_record()}
    raise DogfoodMeasureError("ERR_DOGFOOD_MEASURE_FIXTURE_FAILED", f"{kind} unexpectedly passed")


def run_fixture(fixture: dict[str, Any], suite_dir: Path) -> dict[str, Any]:
    fixture_id = fixture["id"]
    try:
        kind = fixture["kind"]
        if kind == "measured-sample":
            status = measure(suite_dir / fixture_id)
        elif kind in {"direct-requires-gate", "unknown-task", "unsafe-command"}:
            status = blocked_fixture_status(kind, fixture, suite_dir)
        else:
            raise DogfoodMeasureError("ERR_DOGFOOD_MEASURE_FIXTURE_FAILED", f"unknown fixture kind: {kind}")
        expected_status = fixture.get("expected_status")
        if expected_status is not None and status.get("status") != expected_status:
            raise DogfoodMeasureError("ERR_DOGFOOD_MEASURE_FIXTURE_FAILED", f"expected status {expected_status}, got {status.get('status')}")
        expected_error = fixture.get("expected_error")
        actual_error = status.get("error", {}).get("code") if isinstance(status.get("error"), dict) else None
        if expected_error is not None and actual_error != expected_error:
            raise DogfoodMeasureError("ERR_DOGFOOD_MEASURE_FIXTURE_FAILED", f"expected error {expected_error}, got {actual_error}")
        return {"id": fixture_id, "status": "pass", "observed_status": status.get("status"), "required": fixture.get("required", True)}
    except DogfoodMeasureError as exc:
        record = exc.to_record()
        record["fixture_id"] = fixture_id
        return {"id": fixture_id, "status": "fail", "required": fixture.get("required", True), "error": record}


def evaluate_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    suite_id = Path(out_dir).name
    suite_dir = resolve_out(out_dir)
    if suite_dir.exists():
        sentinel = read_sentinel(suite_dir)
        if sentinel is None or sentinel.get("measurement_id") != suite_id:
            raise DogfoodMeasureError("ERR_DOGFOOD_MEASURE_PATH_UNSAFE", "existing dogfood measurement suite is not measurement-owned", path=suite_dir)
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
        raise DogfoodMeasureError("ERR_DOGFOOD_MEASURE_FIXTURE_FAILED", "manifest decision is kill", path=manifest_path)
    return summary


def self_test() -> None:
    MEASURE_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dwm-dogfood-measure-self-test-", dir=MEASURE_ROOT) as tmp:
        summary = evaluate_manifest(ROOT / "fixtures" / "v56" / "manifest.json", Path(tmp) / "dogfood-measure-self-test")
    if summary["decision"] != "keep":
        raise DogfoodMeasureError("ERR_DOGFOOD_MEASURE_FIXTURE_FAILED", "dogfood measure self-test manifest did not keep")
    print("dwm_dogfood_measure self-test: pass")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", choices=["sample"])
    parser.add_argument("--manifest")
    parser.add_argument("--mode", default=DEFAULT_MODE)
    parser.add_argument("--out")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--task-id", default=DEFAULT_TASK_ID)
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
        elif args.manifest:
            if not args.out:
                raise DogfoodMeasureError("ERR_DOGFOOD_MEASURE_PATH_UNSAFE", "--manifest requires --out")
            summary = evaluate_manifest(Path(args.manifest), Path(args.out))
            print(canonical_json_text({key: summary[key] for key in ["suite_id", "fixture_count", "required_fixture_count", "required_passed", "passed", "failed", "skipped", "decision"]}))
        elif args.command == "sample":
            if not args.out:
                raise DogfoodMeasureError("ERR_DOGFOOD_MEASURE_PATH_UNSAFE", "sample requires --out")
            print(canonical_json_text(measure(Path(args.out), task_id=args.task_id, mode=args.mode)))
        else:
            parser.error("expected --self-test, --manifest, or sample")
    except (DogfoodMeasureError, subprocess.TimeoutExpired) as exc:
        if isinstance(exc, subprocess.TimeoutExpired):
            error = DogfoodMeasureError("ERR_DOGFOOD_MEASURE_COMMAND_TIMEOUT", "verification command timed out")
            print(canonical_json_text(error.to_record()), file=sys.stderr)
        else:
            print(canonical_json_text(exc.to_record()), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
