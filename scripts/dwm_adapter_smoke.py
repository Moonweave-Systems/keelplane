#!/usr/bin/env python3
"""V27 adapter smoke evidence."""

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
from dwm_benchmark import REQUIRED_TASK_IDS  # noqa: E402
from dwm_benchmark_tasks import TEMPLATE_PATH, load_templates  # noqa: E402


TOOL = "dwm_adapter_smoke.py"
SCHEMA_VERSION = "1.0"
SMOKE_VERSION = "27.0.0"
SMOKE_ROOT = ROOT / "out" / "adapter-smoke"
SENTINEL = ".dwm_adapter_smoke-owned.json"


class AdapterSmokeError(ValueError):
    """Structured V27 adapter smoke failure."""

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
        raise AdapterSmokeError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise AdapterSmokeError(code, "path contains a symlink", path=current)


def resolve_smoke_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_ADAPTER_SMOKE_PATH_UNSAFE", message="adapter smoke output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = SMOKE_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise AdapterSmokeError("ERR_ADAPTER_SMOKE_PATH_UNSAFE", f"adapter smoke output must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise AdapterSmokeError("ERR_ADAPTER_SMOKE_PATH_UNSAFE", "adapter smoke output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_ADAPTER_SMOKE_PATH_SYMLINK")
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


def prepare_out_dir(path: Path, smoke_id: str, *, source: Path) -> None:
    if path.exists():
        if path.is_symlink():
            raise AdapterSmokeError("ERR_ADAPTER_SMOKE_PATH_SYMLINK", "adapter smoke output is a symlink", path=path)
        if not path.is_dir():
            raise AdapterSmokeError("ERR_ADAPTER_SMOKE_PATH_UNSAFE", "adapter smoke output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("smoke_id") != smoke_id:
            raise AdapterSmokeError("ERR_ADAPTER_SMOKE_PATH_UNSAFE", "existing adapter smoke output is not smoke-owned", path=path)
        shutil.rmtree(path)
    SMOKE_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(
        path / SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "smoke_version": SMOKE_VERSION,
            "smoke_id": smoke_id,
            "source_path": rel(source),
            "created_at": now_utc(),
        },
        root=path,
    )


def validate_adapter_command(command: str) -> str:
    if not command or any(char.isspace() for char in command) or "/" in command or "\\" in command:
        raise AdapterSmokeError("ERR_ADAPTER_SMOKE_UNSAFE_COMMAND", "adapter command must be a bare executable name")
    return command


def task_prompt(task_id: str) -> str:
    if task_id not in REQUIRED_TASK_IDS:
        raise AdapterSmokeError("ERR_ADAPTER_SMOKE_UNKNOWN_TASK", "task id is not in the benchmark corpus")
    templates = load_templates()
    for task in templates["tasks"]:
        if task["id"] == task_id:
            return str(task["prompt"])
    raise AdapterSmokeError("ERR_ADAPTER_SMOKE_UNKNOWN_TASK", "task template is missing", path=TEMPLATE_PATH)


def run_smoke(
    out_dir: Path,
    *,
    smoke_id: str,
    adapter_command: str,
    task_id: str,
    expected_template_hash: str | None = None,
) -> dict[str, Any]:
    command = validate_adapter_command(adapter_command)
    templates = load_templates()
    template_hash = canonical_hash(templates)
    if expected_template_hash is not None and expected_template_hash != template_hash:
        raise AdapterSmokeError("ERR_ADAPTER_SMOKE_STALE_TEMPLATE", "expected template hash does not match current templates")
    prompt = task_prompt(task_id)
    prepare_out_dir(out_dir, smoke_id, source=TEMPLATE_PATH)
    executable = shutil.which(command)
    planned_command = [command, "--version"]
    if executable is None:
        status = {
            "status": "skipped",
            "adapter": command,
            "task_id": task_id,
            "error": {
                "code": "ERR_ADAPTER_SMOKE_UNAVAILABLE",
                "message": f"adapter command not found: {command}",
            },
            "source_hashes": {"templates": template_hash},
        }
    else:
        completed = subprocess.run(planned_command, cwd=ROOT, check=False, capture_output=True, text=True, timeout=10)
        status = {
            "status": "captured" if completed.returncode == 0 else "skipped",
            "adapter": command,
            "task_id": task_id,
            "planned_command": planned_command,
            "returncode": completed.returncode,
            "version_output_hash": canonical_hash({"stdout": completed.stdout.strip(), "stderr": completed.stderr.strip()}),
            "source_hashes": {"templates": template_hash},
        }
        if completed.returncode != 0:
            status["error"] = {
                "code": "ERR_ADAPTER_SMOKE_UNAVAILABLE",
                "message": f"adapter version check failed: {command}",
            }
    write_json_atomic(
        out_dir / "adapter-smoke.json",
        {
            **status,
            "schema_version": SCHEMA_VERSION,
            "smoke_version": SMOKE_VERSION,
            "smoke_id": smoke_id,
            "task_prompt_hash": canonical_hash(prompt),
            "live_task_execution": False,
        },
        root=out_dir,
    )
    write_json_atomic(out_dir / "status.json", status, root=out_dir)
    return status


def blocked_fixture_status(kind: str, fixture: dict[str, Any]) -> dict[str, Any]:
    try:
        if kind == "unsafe-command":
            run_smoke(
                SMOKE_ROOT / "fixture-unsafe-command",
                smoke_id="fixture-unsafe-command",
                adapter_command=str(fixture["adapter_command"]),
                task_id=str(fixture["task_id"]),
            )
        elif kind == "unknown-task":
            run_smoke(
                SMOKE_ROOT / "fixture-unknown-task",
                smoke_id="fixture-unknown-task",
                adapter_command="python",
                task_id=str(fixture["task_id"]),
            )
        elif kind == "stale-template":
            run_smoke(
                SMOKE_ROOT / "fixture-stale-template",
                smoke_id="fixture-stale-template",
                adapter_command="python",
                task_id=str(fixture["task_id"]),
                expected_template_hash=str(fixture["expected_template_hash"]),
            )
        else:
            raise AdapterSmokeError("ERR_ADAPTER_SMOKE_FIXTURE_FAILED", f"unknown blocked fixture kind: {kind}")
    except AdapterSmokeError as exc:
        if fixture.get("expected_error") != exc.code:
            raise
        return {"status": "blocked", "error": exc.to_record()}
    raise AdapterSmokeError("ERR_ADAPTER_SMOKE_FIXTURE_FAILED", f"{kind} unexpectedly passed")


def run_fixture(fixture: dict[str, Any], suite_dir: Path) -> dict[str, Any]:
    fixture_id = fixture["id"]
    try:
        kind = fixture["kind"]
        if kind == "adapter-smoke":
            status = run_smoke(
                suite_dir / fixture_id,
                smoke_id=fixture_id,
                adapter_command=str(fixture["adapter_command"]),
                task_id=str(fixture["task_id"]),
            )
        elif kind in {"unsafe-command", "unknown-task", "stale-template"}:
            status = blocked_fixture_status(kind, fixture)
        else:
            raise AdapterSmokeError("ERR_ADAPTER_SMOKE_FIXTURE_FAILED", f"unknown fixture kind: {kind}")
        expected_status = fixture.get("expected_status")
        if expected_status is not None and status.get("status") != expected_status:
            raise AdapterSmokeError("ERR_ADAPTER_SMOKE_FIXTURE_FAILED", f"expected status {expected_status}, got {status.get('status')}")
        expected_error = fixture.get("expected_error")
        actual_error = status.get("error", {}).get("code") if isinstance(status.get("error"), dict) else None
        if expected_error is not None and actual_error != expected_error:
            raise AdapterSmokeError("ERR_ADAPTER_SMOKE_FIXTURE_FAILED", f"expected error {expected_error}, got {actual_error}")
        return {"id": fixture_id, "status": "pass", "observed_status": status.get("status"), "required": fixture.get("required", True)}
    except AdapterSmokeError as exc:
        record = exc.to_record()
        record["fixture_id"] = fixture_id
        return {"id": fixture_id, "status": "fail", "required": fixture.get("required", True), "error": record}


def evaluate_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    suite_id = Path(out_dir).name
    suite_dir = resolve_smoke_out(out_dir)
    if suite_dir.exists():
        sentinel = read_sentinel(suite_dir)
        if sentinel is None or sentinel.get("smoke_id") != suite_id:
            raise AdapterSmokeError("ERR_ADAPTER_SMOKE_PATH_UNSAFE", "existing adapter smoke suite is not smoke-owned", path=suite_dir)
        shutil.rmtree(suite_dir)
    prepare_out_dir(suite_dir, suite_id, source=manifest_path)
    fixtures = manifest["fixtures"]
    required_ids = set(manifest["required_fixture_ids"])
    results = [run_fixture(fixture, suite_dir) for fixture in fixtures]
    passed = sum(1 for item in results if item["status"] == "pass")
    failures = [item["error"] for item in results if item["status"] == "fail"]
    skipped = sum(1 for item in results if item.get("observed_status") == "skipped")
    required_passed = sum(1 for item in results if item["id"] in required_ids and item["status"] == "pass")
    required_failed = [item for item in results if item["id"] in required_ids and item["status"] == "fail"]
    summary = {
        "suite_id": suite_id,
        "fixture_count": len(fixtures),
        "required_fixture_count": len(required_ids),
        "required_passed": required_passed,
        "passed": passed,
        "failed": len(failures),
        "skipped": skipped,
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
        raise AdapterSmokeError("ERR_ADAPTER_SMOKE_FIXTURE_FAILED", "manifest decision is kill", path=manifest_path)
    return summary


def self_test() -> None:
    SMOKE_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dwm-adapter-smoke-self-test-", dir=SMOKE_ROOT) as tmp:
        summary = evaluate_manifest(ROOT / "fixtures" / "v27" / "manifest.json", Path(tmp) / "adapter-smoke-self-test")
    if summary["decision"] != "keep":
        raise AdapterSmokeError("ERR_ADAPTER_SMOKE_FIXTURE_FAILED", "adapter smoke self-test manifest did not keep")
    print("dwm_adapter_smoke self-test: pass")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", choices=["smoke"])
    parser.add_argument("--adapter-command", default="codex")
    parser.add_argument("--expected-template-hash")
    parser.add_argument("--manifest")
    parser.add_argument("--out")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--task-id", default="failing-test-fix")
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
        elif args.manifest:
            if not args.out:
                raise AdapterSmokeError("ERR_ADAPTER_SMOKE_PATH_UNSAFE", "--manifest requires --out")
            summary = evaluate_manifest(Path(args.manifest), Path(args.out))
            print(canonical_json_text({key: summary[key] for key in ["suite_id", "fixture_count", "required_fixture_count", "required_passed", "passed", "failed", "skipped", "decision"]}))
        elif args.command == "smoke":
            if not args.out:
                raise AdapterSmokeError("ERR_ADAPTER_SMOKE_PATH_UNSAFE", "smoke requires --out")
            status = run_smoke(
                resolve_smoke_out(args.out),
                smoke_id=Path(args.out).name,
                adapter_command=args.adapter_command,
                task_id=args.task_id,
                expected_template_hash=args.expected_template_hash,
            )
            print(canonical_json_text(status))
        else:
            parser.error("expected --self-test, --manifest, or smoke")
    except AdapterSmokeError as exc:
        print(canonical_json_text(exc.to_record()), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
