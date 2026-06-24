#!/usr/bin/env python3
"""V29 live runner preflight gate."""

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
from dwm_live_attempt_plan import PLAN_ROOT as ATTEMPT_PLAN_ROOT, plan_live_attempt, resolve_plan_out  # noqa: E402


TOOL = "dwm_live_runner_preflight.py"
SCHEMA_VERSION = "1.0"
PREFLIGHT_VERSION = "29.0.0"
PREFLIGHT_ROOT = ROOT / "out" / "live-runner-preflight"
SENTINEL = ".dwm_live_runner_preflight-owned.json"


class LiveRunnerPreflightError(ValueError):
    """Structured V29 preflight failure."""

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
        raise LiveRunnerPreflightError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise LiveRunnerPreflightError(code, "path contains a symlink", path=current)


def resolve_preflight_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_LIVE_RUNNER_PATH_UNSAFE", message="live runner preflight output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = PREFLIGHT_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise LiveRunnerPreflightError("ERR_LIVE_RUNNER_PATH_UNSAFE", f"live runner preflight output must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise LiveRunnerPreflightError("ERR_LIVE_RUNNER_PATH_UNSAFE", "live runner preflight output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_LIVE_RUNNER_PATH_SYMLINK")
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


def prepare_out_dir(path: Path, preflight_id: str, *, source: Path) -> None:
    if path.exists():
        if path.is_symlink():
            raise LiveRunnerPreflightError("ERR_LIVE_RUNNER_PATH_SYMLINK", "live runner preflight output is a symlink", path=path)
        if not path.is_dir():
            raise LiveRunnerPreflightError("ERR_LIVE_RUNNER_PATH_UNSAFE", "live runner preflight output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("preflight_id") != preflight_id:
            raise LiveRunnerPreflightError("ERR_LIVE_RUNNER_PATH_UNSAFE", "existing live runner preflight output is not preflight-owned", path=path)
        shutil.rmtree(path)
    PREFLIGHT_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(
        path / SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "preflight_version": PREFLIGHT_VERSION,
            "preflight_id": preflight_id,
            "source_path": rel(source),
            "created_at": now_utc(),
        },
        root=path,
    )


def load_command_plan(plan_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    command_plan_path = plan_dir / "command-plan.json"
    status_path = plan_dir / "status.json"
    if not command_plan_path.is_file() or command_plan_path.is_symlink() or not status_path.is_file() or status_path.is_symlink():
        raise LiveRunnerPreflightError("ERR_LIVE_RUNNER_ARTIFACT_MISSING", "live attempt plan artifacts are missing", path=plan_dir)
    return read_json(command_plan_path), read_json(status_path)


def preflight_plan(
    plan_dir: Path,
    out_dir: Path,
    *,
    preflight_id: str,
    expected_plan_hash: str | None = None,
) -> dict[str, Any]:
    command_plan, plan_status = load_command_plan(plan_dir)
    plan_hash = canonical_hash(command_plan)
    if expected_plan_hash is not None and expected_plan_hash != plan_hash:
        raise LiveRunnerPreflightError("ERR_LIVE_RUNNER_STALE_PLAN", "expected command plan hash does not match current plan", path=plan_dir)
    prepare_out_dir(out_dir, preflight_id, source=plan_dir)
    if plan_status.get("status") == "skipped":
        status = {
            "status": "skipped",
            "error": {
                "code": "ERR_LIVE_RUNNER_PLAN_SKIPPED",
                "message": "live attempt plan was skipped",
            },
            "source_hashes": {"command_plan": plan_hash},
        }
        write_json_atomic(out_dir / "status.json", status, root=out_dir)
        return status
    if command_plan.get("status") != "planned" or plan_status.get("status") != "planned":
        raise LiveRunnerPreflightError("ERR_LIVE_RUNNER_POLICY_BLOCKED", "command plan is not in planned state", path=plan_dir)
    if command_plan.get("execution_policy") != "planned-only; do not execute in V28":
        raise LiveRunnerPreflightError("ERR_LIVE_RUNNER_POLICY_BLOCKED", "unexpected execution policy", path=plan_dir)
    command = command_plan.get("command")
    if not isinstance(command, list) or not command or not all(isinstance(part, str) and part for part in command):
        raise LiveRunnerPreflightError("ERR_LIVE_RUNNER_POLICY_BLOCKED", "command plan command is malformed", path=plan_dir)
    status = {
        "status": "ready-for-human-run",
        "execution_mode": "manual-only",
        "command": command,
        "adapter": command_plan.get("adapter"),
        "task_id": command_plan.get("task_id"),
        "source_hashes": {
            "command_plan": plan_hash,
            **command_plan.get("source_hashes", {}),
        },
    }
    write_json_atomic(out_dir / "preflight.json", status, root=out_dir)
    write_json_atomic(out_dir / "status.json", status, root=out_dir)
    return status


def make_plan_dir(base_dir: Path, *, adapter_command: str = "python", task_id: str = "failing-test-fix") -> Path:
    plan_dir = resolve_plan_out(base_dir)
    plan_live_attempt(plan_dir, plan_id=plan_dir.name, adapter_command=adapter_command, task_id=task_id)
    return plan_dir


def blocked_fixture_status(kind: str, fixture: dict[str, Any], suite_id: str) -> dict[str, Any]:
    try:
        if kind == "stale-plan":
            plan_dir = make_plan_dir(ATTEMPT_PLAN_ROOT / f"{suite_id}-runner-stale-plan")
            preflight_plan(
                plan_dir,
                PREFLIGHT_ROOT / f"{suite_id}-fixture-stale-plan",
                preflight_id=f"{suite_id}-fixture-stale-plan",
                expected_plan_hash=str(fixture["expected_plan_hash"]),
            )
        elif kind == "policy-blocked":
            plan_dir = make_plan_dir(ATTEMPT_PLAN_ROOT / f"{suite_id}-runner-policy-blocked")
            command_plan_path = plan_dir / "command-plan.json"
            command_plan = read_json(command_plan_path)
            command_plan["execution_policy"] = "execute-now"
            write_json_atomic(command_plan_path, command_plan, root=plan_dir)
            preflight_plan(plan_dir, PREFLIGHT_ROOT / f"{suite_id}-fixture-policy-blocked", preflight_id=f"{suite_id}-fixture-policy-blocked")
        elif kind == "missing-artifact":
            missing_dir = ATTEMPT_PLAN_ROOT / f"{suite_id}-runner-missing-artifact"
            if missing_dir.exists():
                shutil.rmtree(missing_dir)
            missing_dir.mkdir(parents=True)
            preflight_plan(missing_dir, PREFLIGHT_ROOT / f"{suite_id}-fixture-missing-artifact", preflight_id=f"{suite_id}-fixture-missing-artifact")
        else:
            raise LiveRunnerPreflightError("ERR_LIVE_RUNNER_FIXTURE_FAILED", f"unknown blocked fixture kind: {kind}")
    except LiveRunnerPreflightError as exc:
        if fixture.get("expected_error") != exc.code:
            raise
        return {"status": "blocked", "error": exc.to_record()}
    raise LiveRunnerPreflightError("ERR_LIVE_RUNNER_FIXTURE_FAILED", f"{kind} unexpectedly passed")


def run_fixture(fixture: dict[str, Any], suite_dir: Path) -> dict[str, Any]:
    fixture_id = fixture["id"]
    try:
        kind = fixture["kind"]
        if kind in {"preflight-ready", "preflight-skipped"}:
            plan_dir = make_plan_dir(
                ATTEMPT_PLAN_ROOT / f"{suite_dir.name}-fixture-{fixture_id}",
                adapter_command=str(fixture.get("adapter_command", "python")),
                task_id=str(fixture.get("task_id", "failing-test-fix")),
            )
            status = preflight_plan(plan_dir, suite_dir / fixture_id, preflight_id=fixture_id)
        elif kind in {"stale-plan", "policy-blocked", "missing-artifact"}:
            status = blocked_fixture_status(kind, fixture, suite_dir.name)
        else:
            raise LiveRunnerPreflightError("ERR_LIVE_RUNNER_FIXTURE_FAILED", f"unknown fixture kind: {kind}")
        expected_status = fixture.get("expected_status")
        if expected_status is not None and status.get("status") != expected_status:
            raise LiveRunnerPreflightError("ERR_LIVE_RUNNER_FIXTURE_FAILED", f"expected status {expected_status}, got {status.get('status')}")
        expected_error = fixture.get("expected_error")
        actual_error = status.get("error", {}).get("code") if isinstance(status.get("error"), dict) else None
        if expected_error is not None and actual_error != expected_error:
            raise LiveRunnerPreflightError("ERR_LIVE_RUNNER_FIXTURE_FAILED", f"expected error {expected_error}, got {actual_error}")
        return {"id": fixture_id, "status": "pass", "observed_status": status.get("status"), "required": fixture.get("required", True)}
    except LiveRunnerPreflightError as exc:
        record = exc.to_record()
        record["fixture_id"] = fixture_id
        return {"id": fixture_id, "status": "fail", "required": fixture.get("required", True), "error": record}


def evaluate_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    suite_id = Path(out_dir).name
    suite_dir = resolve_preflight_out(out_dir)
    if suite_dir.exists():
        sentinel = read_sentinel(suite_dir)
        if sentinel is None or sentinel.get("preflight_id") != suite_id:
            raise LiveRunnerPreflightError("ERR_LIVE_RUNNER_PATH_UNSAFE", "existing live runner suite is not preflight-owned", path=suite_dir)
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
        "source_hashes": {"manifest": canonical_hash(manifest)},
    }
    write_json_atomic(suite_dir / "summary.json", summary, root=suite_dir)
    if summary["decision"] != "keep":
        raise LiveRunnerPreflightError("ERR_LIVE_RUNNER_FIXTURE_FAILED", "manifest decision is kill", path=manifest_path)
    return summary


def self_test() -> None:
    PREFLIGHT_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dwm-live-runner-preflight-self-test-", dir=PREFLIGHT_ROOT) as tmp:
        summary = evaluate_manifest(ROOT / "fixtures" / "v29" / "manifest.json", Path(tmp) / "live-runner-preflight-self-test")
    if summary["decision"] != "keep":
        raise LiveRunnerPreflightError("ERR_LIVE_RUNNER_FIXTURE_FAILED", "live runner preflight self-test manifest did not keep")
    print("dwm_live_runner_preflight self-test: pass")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", choices=["preflight"])
    parser.add_argument("--expected-plan-hash")
    parser.add_argument("--manifest")
    parser.add_argument("--out")
    parser.add_argument("--plan")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
        elif args.manifest:
            if not args.out:
                raise LiveRunnerPreflightError("ERR_LIVE_RUNNER_PATH_UNSAFE", "--manifest requires --out")
            summary = evaluate_manifest(Path(args.manifest), Path(args.out))
            print(canonical_json_text({key: summary[key] for key in ["suite_id", "fixture_count", "required_fixture_count", "required_passed", "passed", "failed", "skipped", "decision"]}))
        elif args.command == "preflight":
            if not args.out or not args.plan:
                raise LiveRunnerPreflightError("ERR_LIVE_RUNNER_PATH_UNSAFE", "preflight requires --plan and --out")
            status = preflight_plan(Path(args.plan), resolve_preflight_out(args.out), preflight_id=Path(args.out).name, expected_plan_hash=args.expected_plan_hash)
            print(canonical_json_text(status))
        else:
            parser.error("expected --self-test, --manifest, or preflight")
    except LiveRunnerPreflightError as exc:
        print(canonical_json_text(exc.to_record()), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
