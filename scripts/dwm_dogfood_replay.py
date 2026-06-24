#!/usr/bin/env python3
"""V20.6 deterministic dogfood replay gate."""

from __future__ import annotations

import argparse
import json
import shlex
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

from compile_workflow import canonical_hash, canonical_json_text, read_json, write_json_atomic, write_text_atomic  # noqa: E402
from dwm import DOGFOOD_COMMANDS  # noqa: E402


TOOL = "dwm_dogfood_replay.py"
SCHEMA_VERSION = "1.0"
DOGFOOD_REPLAY_VERSION = "20.6.0"
DOGFOOD_REPLAY_ROOT = ROOT / "out" / "dogfood-replay"
DEFAULT_RUN = "out/v9/v32-semantic-dogfood"
SENTINEL = ".dwm_dogfood_replay-owned.json"


class DogfoodReplayError(ValueError):
    """Structured V20.6 dogfood replay failure."""

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
        raise DogfoodReplayError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise DogfoodReplayError(code, "path contains a symlink", path=current)


def resolve_replay_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_DOGFOOD_PATH_UNSAFE", message="dogfood replay output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = DOGFOOD_REPLAY_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise DogfoodReplayError("ERR_DOGFOOD_PATH_UNSAFE", f"dogfood replay output must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise DogfoodReplayError("ERR_DOGFOOD_PATH_UNSAFE", "dogfood replay output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_DOGFOOD_PATH_SYMLINK")
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


def prepare_out_dir(path: Path, replay_id: str, *, source: Path | str) -> None:
    if path.exists():
        if path.is_symlink():
            raise DogfoodReplayError("ERR_DOGFOOD_PATH_SYMLINK", "dogfood replay output is a symlink", path=path)
        if not path.is_dir():
            raise DogfoodReplayError("ERR_DOGFOOD_PATH_UNSAFE", "dogfood replay output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("replay_id") != replay_id:
            raise DogfoodReplayError("ERR_DOGFOOD_PATH_UNSAFE", "existing dogfood replay output is not replay-owned", path=path)
        shutil.rmtree(path)
    DOGFOOD_REPLAY_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    source_path = rel(source) if isinstance(source, Path) else source
    write_json_atomic(
        path / SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "dogfood_replay_version": DOGFOOD_REPLAY_VERSION,
            "replay_id": replay_id,
            "source_path": source_path,
            "created_at": now_utc(),
        },
        root=path,
    )


def git_status_text() -> str:
    completed = subprocess.run(["git", "status", "--short"], cwd=ROOT, check=False, text=True, capture_output=True)
    if completed.returncode != 0:
        raise DogfoodReplayError("ERR_DOGFOOD_GIT_STATUS_FAILED", "git status failed")
    return completed.stdout


def run_shell_command(command: str) -> dict[str, Any]:
    completed = subprocess.run(shlex.split(command), cwd=ROOT, check=False, text=True, capture_output=True)
    return {
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def parse_json_stdout(result: dict[str, Any], *, code: str) -> dict[str, Any]:
    try:
        data = json.loads(str(result.get("stdout", "")))
    except json.JSONDecodeError as exc:
        raise DogfoodReplayError(code, f"command stdout is not JSON: {result.get('command')}") from exc
    if not isinstance(data, dict):
        raise DogfoodReplayError(code, f"command stdout root is not an object: {result.get('command')}")
    return data


def validate_replay(
    command_results: list[dict[str, Any]],
    final_status: dict[str, Any],
    final_next: dict[str, Any],
    repo_status_before: str,
    repo_status_after: str,
) -> None:
    failed = [item for item in command_results if item.get("returncode") != 0]
    if failed:
        raise DogfoodReplayError("ERR_DOGFOOD_COMMAND_FAILED", f"dogfood command failed: {failed[0].get('command')}")
    if repo_status_before != repo_status_after:
        raise DogfoodReplayError("ERR_DOGFOOD_REPO_DIFF_CHANGED", "repo status changed during dogfood replay")
    recommendation = final_next.get("recommendation")
    action = recommendation.get("action") if isinstance(recommendation, dict) else None
    if final_status.get("status") != "workflow-complete" or final_next.get("status") != "workflow-complete" or action != "complete":
        raise DogfoodReplayError("ERR_DOGFOOD_FINAL_STATUS", "dogfood replay did not end at trusted workflow-complete")
    if final_next.get("trusted") is not True:
        raise DogfoodReplayError("ERR_DOGFOOD_FINAL_STATUS", "dogfood replay next summary is not trusted")


def render_replay(replay: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# V20.6 Dogfood Replay",
            "",
            f"Decision: `{replay['decision']}`",
            f"Final status: `{replay['final_status']}`",
            f"Recommendation action: `{replay['recommendation_action']}`",
            f"Repo status unchanged: `{str(replay['repo_status_unchanged']).lower()}`",
            f"Command count: `{replay['command_count']}`",
            "",
            "The replay regenerates deterministic dogfood artifacts only. It does not execute live adapters or attach runtime sessions.",
            "",
        ]
    )


def replay_dogfood(out_dir: Path) -> dict[str, Any]:
    out_dir = resolve_replay_out(out_dir)
    replay_id = out_dir.name
    prepare_out_dir(out_dir, replay_id, source=DEFAULT_RUN)
    repo_status_before = git_status_text()
    command_results = [run_shell_command(command) for command in DOGFOOD_COMMANDS]
    status_result = run_shell_command(f"python scripts/dwm.py status --run {DEFAULT_RUN} --json")
    next_result = run_shell_command(f"python scripts/dwm.py next --run {DEFAULT_RUN} --json")
    command_results.extend([status_result, next_result])
    final_status = parse_json_stdout(status_result, code="ERR_DOGFOOD_FINAL_STATUS")
    final_next = parse_json_stdout(next_result, code="ERR_DOGFOOD_FINAL_STATUS")
    repo_status_after = git_status_text()
    validate_replay(command_results, final_status, final_next, repo_status_before, repo_status_after)
    recommendation = final_next["recommendation"]
    replay = {
        "tool": TOOL,
        "schema_version": SCHEMA_VERSION,
        "dogfood_replay_version": DOGFOOD_REPLAY_VERSION,
        "replay_id": replay_id,
        "created_at": now_utc(),
        "source_run": DEFAULT_RUN,
        "command_count": len(command_results),
        "commands_hash": canonical_hash(command_results),
        "status_hash": canonical_hash(final_status),
        "next_hash": canonical_hash(final_next),
        "repo_status_before": repo_status_before,
        "repo_status_after": repo_status_after,
        "repo_status_unchanged": repo_status_before == repo_status_after,
        "final_status": final_status["status"],
        "recommendation_action": recommendation["action"],
        "trusted": final_next["trusted"],
        "decision": "replayed",
    }
    replay_status = {
        "tool": TOOL,
        "schema_version": SCHEMA_VERSION,
        "replay_id": replay_id,
        "status": "accepted",
        "decision": "replayed",
        "source_run": DEFAULT_RUN,
        "repo_status_unchanged": True,
        "final_status": final_status["status"],
        "recommendation_action": recommendation["action"],
    }
    write_json_atomic(out_dir / "commands.json", command_results, root=out_dir)
    write_json_atomic(out_dir / "status.json", replay_status, root=out_dir)
    write_json_atomic(out_dir / "replay.json", replay, root=out_dir)
    write_text_atomic(out_dir / "replay.md", render_replay(replay), root=out_dir)
    return replay_status


def synthetic_fixture_status(kind: str) -> dict[str, Any]:
    good_command = {"command": "synthetic", "returncode": 0, "stdout": "", "stderr": ""}
    command_results = [good_command]
    final_status = {"status": "workflow-complete"}
    final_next = {"status": "workflow-complete", "trusted": True, "recommendation": {"action": "complete"}}
    before = ""
    after = ""
    if kind == "synthetic-command-failure":
        command_results = [{**good_command, "returncode": 1}]
    elif kind == "synthetic-repo-diff":
        after = " M README.md\n"
    elif kind == "synthetic-final-status":
        final_status = {"status": "blocked"}
    else:
        raise DogfoodReplayError("ERR_DOGFOOD_FIXTURE_FAILED", f"unknown synthetic fixture kind: {kind}")
    validate_replay(command_results, final_status, final_next, before, after)
    return {"status": "accepted", "decision": "replayed"}


def run_fixture(fixture: dict[str, Any], suite_dir: Path) -> dict[str, Any]:
    fixture_id = fixture["id"]
    try:
        kind = fixture["kind"]
        try:
            if kind == "real-replay":
                status = replay_dogfood(suite_dir / fixture_id)
            else:
                status = synthetic_fixture_status(kind)
        except DogfoodReplayError as exc:
            if fixture.get("expected_error") != exc.code:
                raise
            status = {"status": "blocked", "error": exc.to_record()}
        expected_status = fixture.get("expected_status")
        if expected_status is not None and status.get("status") != expected_status:
            raise DogfoodReplayError("ERR_DOGFOOD_FIXTURE_FAILED", f"expected status {expected_status}, got {status.get('status')}")
        expected_decision = fixture.get("expected_decision")
        if expected_decision is not None and status.get("decision") != expected_decision:
            raise DogfoodReplayError("ERR_DOGFOOD_FIXTURE_FAILED", f"expected decision {expected_decision}, got {status.get('decision')}")
        expected_error = fixture.get("expected_error")
        actual_error = status.get("error", {}).get("code") if isinstance(status.get("error"), dict) else None
        if expected_error is not None and actual_error != expected_error:
            raise DogfoodReplayError("ERR_DOGFOOD_FIXTURE_FAILED", f"expected error {expected_error}, got {actual_error}")
        return {"id": fixture_id, "status": "pass", "required": fixture.get("required", True)}
    except DogfoodReplayError as exc:
        record = exc.to_record()
        record["fixture_id"] = fixture_id
        return {"id": fixture_id, "status": "fail", "required": fixture.get("required", True), "error": record}


def evaluate_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    suite_id = Path(out_dir).name
    suite_dir = resolve_replay_out(out_dir)
    if suite_dir.exists():
        sentinel = read_sentinel(suite_dir)
        if sentinel is None or sentinel.get("replay_id") != suite_id:
            raise DogfoodReplayError("ERR_DOGFOOD_PATH_UNSAFE", "existing dogfood replay suite is not replay-owned", path=suite_dir)
        shutil.rmtree(suite_dir)
    suite_dir.mkdir(parents=True)
    write_json_atomic(
        suite_dir / SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "dogfood_replay_version": DOGFOOD_REPLAY_VERSION,
            "replay_id": suite_id,
            "source_path": rel(manifest_path),
            "created_at": now_utc(),
        },
        root=suite_dir,
    )
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
    }
    write_json_atomic(suite_dir / "summary.json", summary, root=suite_dir)
    if summary["decision"] != "keep":
        raise DogfoodReplayError("ERR_DOGFOOD_FIXTURE_FAILED", "manifest decision is kill", path=manifest_path)
    return summary


def self_test() -> None:
    DOGFOOD_REPLAY_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dwm-dogfood-replay-self-test-", dir=DOGFOOD_REPLAY_ROOT) as tmp:
        summary = evaluate_manifest(ROOT / "fixtures" / "v20.6" / "manifest.json", Path(tmp) / "dogfood-replay-self-test")
    if summary["decision"] != "keep":
        raise DogfoodReplayError("ERR_DOGFOOD_FIXTURE_FAILED", "dogfood replay self-test manifest did not keep")
    print("dwm_dogfood_replay self-test: pass")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", choices=["replay"])
    parser.add_argument("--out")
    parser.add_argument("--manifest")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
        elif args.manifest:
            if not args.out:
                raise DogfoodReplayError("ERR_DOGFOOD_PATH_UNSAFE", "--manifest requires --out")
            summary = evaluate_manifest(Path(args.manifest), Path(args.out))
            print(canonical_json_text({key: summary[key] for key in ["suite_id", "fixture_count", "required_fixture_count", "required_passed", "passed", "failed", "skipped", "decision"]}))
        elif args.command == "replay":
            if not args.out:
                raise DogfoodReplayError("ERR_DOGFOOD_PATH_UNSAFE", "replay requires --out")
            print(canonical_json_text(replay_dogfood(Path(args.out))))
        else:
            parser.error("expected --self-test, --manifest, or replay")
    except DogfoodReplayError as exc:
        print(canonical_json_text(exc.to_record()), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
