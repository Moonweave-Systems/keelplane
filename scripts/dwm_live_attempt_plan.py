#!/usr/bin/env python3
"""V28 live attempt command planner."""

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
from dwm_adapter_smoke import AdapterSmokeError, run_smoke, task_prompt, validate_adapter_command  # noqa: E402
from dwm_benchmark_tasks import TEMPLATE_PATH, load_templates  # noqa: E402


TOOL = "dwm_live_attempt_plan.py"
SCHEMA_VERSION = "1.0"
PLAN_VERSION = "28.0.0"
PLAN_ROOT = ROOT / "out" / "live-attempt-plans"
SENTINEL = ".dwm_live_attempt_plan-owned.json"


class LiveAttemptPlanError(ValueError):
    """Structured V28 live attempt planning failure."""

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
        raise LiveAttemptPlanError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise LiveAttemptPlanError(code, "path contains a symlink", path=current)


def resolve_plan_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_LIVE_ATTEMPT_PATH_UNSAFE", message="live attempt plan output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = PLAN_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise LiveAttemptPlanError("ERR_LIVE_ATTEMPT_PATH_UNSAFE", f"live attempt plan output must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise LiveAttemptPlanError("ERR_LIVE_ATTEMPT_PATH_UNSAFE", "live attempt plan output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_LIVE_ATTEMPT_PATH_SYMLINK")
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


def prepare_out_dir(path: Path, plan_id: str, *, source: Path) -> None:
    if path.exists():
        if path.is_symlink():
            raise LiveAttemptPlanError("ERR_LIVE_ATTEMPT_PATH_SYMLINK", "live attempt plan output is a symlink", path=path)
        if not path.is_dir():
            raise LiveAttemptPlanError("ERR_LIVE_ATTEMPT_PATH_UNSAFE", "live attempt plan output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("plan_id") != plan_id:
            raise LiveAttemptPlanError("ERR_LIVE_ATTEMPT_PATH_UNSAFE", "existing live attempt plan output is not plan-owned", path=path)
        shutil.rmtree(path)
    PLAN_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(
        path / SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "plan_version": PLAN_VERSION,
            "plan_id": plan_id,
            "source_path": rel(source),
            "created_at": now_utc(),
        },
        root=path,
    )


def map_smoke_error(exc: AdapterSmokeError) -> LiveAttemptPlanError:
    mapping = {
        "ERR_ADAPTER_SMOKE_UNSAFE_COMMAND": "ERR_LIVE_ATTEMPT_UNSAFE_COMMAND",
        "ERR_ADAPTER_SMOKE_UNKNOWN_TASK": "ERR_LIVE_ATTEMPT_UNKNOWN_TASK",
        "ERR_ADAPTER_SMOKE_STALE_TEMPLATE": "ERR_LIVE_ATTEMPT_STALE_SMOKE",
        "ERR_ADAPTER_SMOKE_UNAVAILABLE": "ERR_LIVE_ATTEMPT_ADAPTER_UNAVAILABLE",
    }
    return LiveAttemptPlanError(mapping.get(exc.code, "ERR_LIVE_ATTEMPT_SMOKE_FAILED"), exc.message, path=exc.path)


def command_for_adapter(adapter_command: str, prompt_path: Path) -> list[str]:
    if adapter_command == "codex":
        return ["codex", "exec", "--ask-for-approval", "never", "--sandbox", "workspace-write", "--", f"$(cat {rel(prompt_path)})"]
    return [adapter_command, rel(prompt_path)]


def plan_live_attempt(
    out_dir: Path,
    *,
    plan_id: str,
    adapter_command: str,
    task_id: str,
    expected_template_hash: str | None = None,
) -> dict[str, Any]:
    try:
        command = validate_adapter_command(adapter_command)
        prompt = task_prompt(task_id)
        templates = load_templates()
        template_hash = canonical_hash(templates)
        if expected_template_hash is not None and expected_template_hash != template_hash:
            raise LiveAttemptPlanError("ERR_LIVE_ATTEMPT_STALE_SMOKE", "expected template hash does not match current templates")
        prepare_out_dir(out_dir, plan_id, source=TEMPLATE_PATH)
        smoke_status = run_smoke(
            out_dir / "smoke",
            smoke_id="smoke",
            adapter_command=command,
            task_id=task_id,
            expected_template_hash=expected_template_hash,
        )
    except AdapterSmokeError as exc:
        raise map_smoke_error(exc) from exc
    prompt_path = out_dir / "prompt.md"
    write_text_atomic(prompt_path, prompt + "\n", root=out_dir)
    if smoke_status.get("status") == "skipped":
        error = smoke_status.get("error", {})
        status = {
            "status": "skipped",
            "adapter": command,
            "task_id": task_id,
            "error": {
                "code": "ERR_LIVE_ATTEMPT_ADAPTER_UNAVAILABLE",
                "message": str(error.get("message", "adapter unavailable")),
            },
            "source_hashes": {
                "templates": template_hash,
                "prompt": canonical_hash(prompt),
                "smoke": canonical_hash(smoke_status),
            },
        }
        write_json_atomic(out_dir / "status.json", status, root=out_dir)
        write_json_atomic(out_dir / "command-plan.json", {**status, "command": []}, root=out_dir)
        return status
    if smoke_status.get("status") != "captured":
        raise LiveAttemptPlanError("ERR_LIVE_ATTEMPT_SMOKE_FAILED", "adapter smoke did not produce captured or skipped status")
    command_plan = {
        "schema_version": SCHEMA_VERSION,
        "plan_version": PLAN_VERSION,
        "plan_id": plan_id,
        "status": "planned",
        "adapter": command,
        "task_id": task_id,
        "command": command_for_adapter(command, prompt_path),
        "execution_policy": "planned-only; do not execute in V28",
        "source_hashes": {
            "templates": template_hash,
            "prompt": canonical_hash(prompt),
            "smoke": canonical_hash(smoke_status),
        },
    }
    status = {
        "status": "planned",
        "adapter": command,
        "task_id": task_id,
        "command_ready": True,
        "source_hashes": command_plan["source_hashes"],
    }
    write_json_atomic(out_dir / "command-plan.json", command_plan, root=out_dir)
    write_json_atomic(out_dir / "status.json", status, root=out_dir)
    return status


def blocked_fixture_status(kind: str, fixture: dict[str, Any]) -> dict[str, Any]:
    try:
        if kind == "stale-smoke":
            plan_live_attempt(
                PLAN_ROOT / "fixture-stale-smoke",
                plan_id="fixture-stale-smoke",
                adapter_command="python",
                task_id=str(fixture["task_id"]),
                expected_template_hash=str(fixture["expected_template_hash"]),
            )
        elif kind == "unknown-task":
            plan_live_attempt(
                PLAN_ROOT / "fixture-unknown-task",
                plan_id="fixture-unknown-task",
                adapter_command="python",
                task_id=str(fixture["task_id"]),
            )
        elif kind == "unsafe-command":
            plan_live_attempt(
                PLAN_ROOT / "fixture-unsafe-command",
                plan_id="fixture-unsafe-command",
                adapter_command=str(fixture["adapter_command"]),
                task_id=str(fixture["task_id"]),
            )
        else:
            raise LiveAttemptPlanError("ERR_LIVE_ATTEMPT_FIXTURE_FAILED", f"unknown blocked fixture kind: {kind}")
    except LiveAttemptPlanError as exc:
        if fixture.get("expected_error") != exc.code:
            raise
        return {"status": "blocked", "error": exc.to_record()}
    raise LiveAttemptPlanError("ERR_LIVE_ATTEMPT_FIXTURE_FAILED", f"{kind} unexpectedly passed")


def run_fixture(fixture: dict[str, Any], suite_dir: Path) -> dict[str, Any]:
    fixture_id = fixture["id"]
    try:
        kind = fixture["kind"]
        if kind == "plan":
            status = plan_live_attempt(
                suite_dir / fixture_id,
                plan_id=fixture_id,
                adapter_command=str(fixture["adapter_command"]),
                task_id=str(fixture["task_id"]),
            )
        elif kind in {"stale-smoke", "unknown-task", "unsafe-command"}:
            status = blocked_fixture_status(kind, fixture)
        else:
            raise LiveAttemptPlanError("ERR_LIVE_ATTEMPT_FIXTURE_FAILED", f"unknown fixture kind: {kind}")
        expected_status = fixture.get("expected_status")
        if expected_status is not None and status.get("status") != expected_status:
            raise LiveAttemptPlanError("ERR_LIVE_ATTEMPT_FIXTURE_FAILED", f"expected status {expected_status}, got {status.get('status')}")
        expected_error = fixture.get("expected_error")
        actual_error = status.get("error", {}).get("code") if isinstance(status.get("error"), dict) else None
        if expected_error is not None and actual_error != expected_error:
            raise LiveAttemptPlanError("ERR_LIVE_ATTEMPT_FIXTURE_FAILED", f"expected error {expected_error}, got {actual_error}")
        return {"id": fixture_id, "status": "pass", "observed_status": status.get("status"), "required": fixture.get("required", True)}
    except LiveAttemptPlanError as exc:
        record = exc.to_record()
        record["fixture_id"] = fixture_id
        return {"id": fixture_id, "status": "fail", "required": fixture.get("required", True), "error": record}


def evaluate_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    suite_id = Path(out_dir).name
    suite_dir = resolve_plan_out(out_dir)
    if suite_dir.exists():
        sentinel = read_sentinel(suite_dir)
        if sentinel is None or sentinel.get("plan_id") != suite_id:
            raise LiveAttemptPlanError("ERR_LIVE_ATTEMPT_PATH_UNSAFE", "existing live attempt suite is not plan-owned", path=suite_dir)
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
        raise LiveAttemptPlanError("ERR_LIVE_ATTEMPT_FIXTURE_FAILED", "manifest decision is kill", path=manifest_path)
    return summary


def self_test() -> None:
    PLAN_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dwm-live-attempt-plan-self-test-", dir=PLAN_ROOT) as tmp:
        summary = evaluate_manifest(ROOT / "fixtures" / "v28" / "manifest.json", Path(tmp) / "live-attempt-plan-self-test")
    if summary["decision"] != "keep":
        raise LiveAttemptPlanError("ERR_LIVE_ATTEMPT_FIXTURE_FAILED", "live attempt plan self-test manifest did not keep")
    print("dwm_live_attempt_plan self-test: pass")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", choices=["plan"])
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
                raise LiveAttemptPlanError("ERR_LIVE_ATTEMPT_PATH_UNSAFE", "--manifest requires --out")
            summary = evaluate_manifest(Path(args.manifest), Path(args.out))
            print(canonical_json_text({key: summary[key] for key in ["suite_id", "fixture_count", "required_fixture_count", "required_passed", "passed", "failed", "skipped", "decision"]}))
        elif args.command == "plan":
            if not args.out:
                raise LiveAttemptPlanError("ERR_LIVE_ATTEMPT_PATH_UNSAFE", "plan requires --out")
            status = plan_live_attempt(
                resolve_plan_out(args.out),
                plan_id=Path(args.out).name,
                adapter_command=args.adapter_command,
                task_id=args.task_id,
                expected_template_hash=args.expected_template_hash,
            )
            print(canonical_json_text(status))
        else:
            parser.error("expected --self-test, --manifest, or plan")
    except LiveAttemptPlanError as exc:
        print(canonical_json_text(exc.to_record()), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
