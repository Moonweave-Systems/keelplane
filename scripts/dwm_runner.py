#!/usr/bin/env python3
"""V13 DWM Runner MVP for one trusted V1 packet."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
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

from compile_workflow import (  # noqa: E402
    CompileError,
    canonical_hash,
    canonical_json_text,
    compile_plan,
    mutate_plan,
    plan_adapter_command,
    read_json,
    sha256_bytes,
    sha256_text,
    write_json_atomic,
    write_text_atomic,
)


TOOL = "dwm_runner.py"
SCHEMA_VERSION = "1.0"
RUNNER_VERSION = "13.0.0"
V13_OUT_ROOT = ROOT / "out" / "v13"
V1_OUT_ROOT = ROOT / "out" / "v1"
SESSIONS_ROOT = ROOT / "out" / "sessions"
WORKTREES_ROOT = ROOT / "out" / "worktrees"
SENTINEL = ".dwm_runner-owned.json"
PROMPT_REL = "packets/001-first-slice.prompt.md"
PACKET_REL = "packets/001-first-slice.packet.json"
ALLOWED_MODES = {"dry-run", "codex-fixture"}
ALLOWED_FIXTURE_COMMANDS = {
    (
        "python",
        "-c",
        "import sys; print('401 Invalid authentication credentials', file=sys.stderr); sys.exit(1)",
    ),
    (
        "python",
        "-c",
        "import sys; prompt=sys.stdin.read(); print('codex fixture ok'); print(len(prompt))",
    ),
}


class RunnerError(ValueError):
    """Structured V13 runner failure."""

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
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def rel(path: Path) -> str:
    resolved = path.resolve(strict=False)
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return str(resolved)


def reject_traversal(path: Path, *, code: str, message: str) -> None:
    if any(part == ".." for part in path.parts):
        raise RunnerError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise RunnerError(code, "path contains a symlink", path=current)


def resolve_under(value: str | Path, root: Path, *, label: str) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_RUNNER_PATH_UNSAFE", message=f"{label} path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = root.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise RunnerError("ERR_RUNNER_PATH_UNSAFE", f"{label} path must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise RunnerError("ERR_RUNNER_PATH_UNSAFE", f"{label} path must name a run directory", path=value)
    check_components_not_symlink(candidate, code="ERR_RUNNER_PATH_SYMLINK")
    return resolved


def resolve_v1_run(value: str | Path) -> Path:
    return resolve_under(value, V1_OUT_ROOT, label="V1 run")


def resolve_v13_out(value: str | Path) -> Path:
    return resolve_under(value, V13_OUT_ROOT, label="V13 output")


def resolve_session_out(value: str | Path) -> Path:
    try:
        return resolve_under(value, SESSIONS_ROOT, label="session")
    except RunnerError as exc:
        if exc.code == "ERR_RUNNER_PATH_SYMLINK":
            raise RunnerError("ERR_SESSION_PATH_SYMLINK", exc.message, path=exc.path) from exc
        if exc.code == "ERR_RUNNER_PATH_UNSAFE":
            raise RunnerError("ERR_SESSION_PATH_UNSAFE", exc.message, path=exc.path) from exc
        raise


def safe_segment(value: str, *, code: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value) or value in {".", ".."}:
        raise RunnerError(code, "value must be one safe path segment", path=value)
    return value


def ensure_contained(root: Path, path: Path) -> None:
    target = path if path.is_absolute() else root / path
    reject_traversal(path, code="ERR_RUNNER_PATH_UNSAFE", message="artifact path escapes run directory")
    try:
        target.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError as exc:
        raise RunnerError("ERR_RUNNER_PATH_UNSAFE", "artifact path escapes run directory", path=target) from exc


def write_text(path: Path, text: str, *, root: Path) -> None:
    ensure_contained(root, path)
    write_text_atomic(path, text, root=root)


def write_json(path: Path, data: Any, *, root: Path) -> None:
    write_text(path, canonical_json_text(data), root=root)


def read_json_obj(path: Path, *, root: Path, label: str) -> dict[str, Any]:
    ensure_contained(root, path)
    if not path.is_file() or path.is_symlink():
        raise RunnerError("ERR_RUNNER_STALE_RUN", f"{label} is missing or symlinked", path=path)
    try:
        data = json.loads(path.read_text())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RunnerError("ERR_RUNNER_STALE_RUN", f"{label} is malformed: {exc}", path=path) from exc
    if not isinstance(data, dict):
        raise RunnerError("ERR_RUNNER_STALE_RUN", f"{label} root must be an object", path=path)
    return data


def read_text_file(path: Path, *, root: Path, label: str) -> str:
    ensure_contained(root, path)
    if not path.is_file() or path.is_symlink():
        raise RunnerError("ERR_RUNNER_STALE_RUN", f"{label} is missing or symlinked", path=path)
    try:
        return path.read_text()
    except UnicodeDecodeError as exc:
        raise RunnerError("ERR_RUNNER_STALE_RUN", f"{label} is not UTF-8", path=path) from exc


def read_sentinel(path: Path) -> dict[str, Any] | None:
    sentinel = path / SENTINEL
    if not sentinel.is_file() or sentinel.is_symlink():
        return None
    try:
        data = json.loads(sentinel.read_text())
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def sentinel_payload(run_id: str, v1_run: Path, *, mode: str) -> dict[str, Any]:
    return {
        "tool": TOOL,
        "schema_version": SCHEMA_VERSION,
        "runner_version": RUNNER_VERSION,
        "run_id": run_id,
        "mode": mode,
        "v1_run_path": rel(v1_run),
        "created_at": now_utc(),
    }


def prepare_out_dir(path: Path, run_id: str, v1_run: Path, *, mode: str, clear: bool = False) -> None:
    path = resolve_v13_out(path)
    if path.exists():
        if path.is_symlink():
            raise RunnerError("ERR_RUNNER_PATH_SYMLINK", "V13 output directory is a symlink", path=path)
        if not path.is_dir():
            raise RunnerError("ERR_RUNNER_PATH_UNSAFE", "V13 output path is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None:
            raise RunnerError("ERR_RUNNER_PATH_UNSAFE", "existing V13 output is not runner-owned", path=path)
        if sentinel.get("tool") != TOOL or sentinel.get("run_id") != run_id or sentinel.get("mode") != mode:
            raise RunnerError("ERR_RUNNER_PATH_UNSAFE", "existing V13 output sentinel does not match this run", path=path)
        if clear:
            shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
    write_json(path / SENTINEL, sentinel_payload(run_id, v1_run, mode=mode), root=path)


def git_status_text(cwd: Path) -> str:
    result = subprocess.run(["git", "status", "--short"], cwd=cwd, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        return result.stderr or result.stdout
    return result.stdout


def git_output(args: list[str], cwd: Path = ROOT) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"git {' '.join(args)} failed"
        raise RunnerError("ERR_SESSION_GIT_FAILED", detail, path=cwd)
    return result.stdout


def current_head() -> str:
    return git_output(["rev-parse", "HEAD"]).strip()


def ensure_worktree(session_id: str, source_head: str) -> Path:
    safe_segment(session_id, code="ERR_SESSION_PATH_UNSAFE")
    path = (WORKTREES_ROOT / session_id).resolve(strict=False)
    try:
        path.relative_to(WORKTREES_ROOT.resolve(strict=False))
    except ValueError as exc:
        raise RunnerError("ERR_SESSION_PATH_UNSAFE", "worktree path escapes worktree root", path=path) from exc
    check_components_not_symlink(path, code="ERR_SESSION_PATH_SYMLINK")
    WORKTREES_ROOT.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.is_symlink():
            raise RunnerError("ERR_SESSION_PATH_SYMLINK", "worktree path is a symlink", path=path)
        if not path.is_dir():
            raise RunnerError("ERR_SESSION_PATH_UNSAFE", "worktree path is not a directory", path=path)
        probe = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=path, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if probe.returncode != 0:
            raise RunnerError("ERR_SESSION_WORKTREE_INVALID", "existing worktree path is not a git worktree", path=path)
        return path
    result = subprocess.run(
        ["git", "worktree", "add", "--detach", str(path), source_head],
        cwd=ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise RunnerError("ERR_SESSION_GIT_FAILED", result.stderr.strip() or result.stdout.strip(), path=path)
    return path


def append_event(session_dir: Path, event: dict[str, Any]) -> None:
    ensure_contained(session_dir, session_dir / "events.jsonl")
    with (session_dir / "events.jsonl").open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(canonical_json_text(event) + "\n")


def render_session_resume(session: dict[str, Any], status: dict[str, Any]) -> str:
    cleanup = session["cleanup_proposal"]["command"]
    return "\n".join(
        [
            "# V14 Session Resume",
            "",
            f"Session ID: `{session['session_id']}`",
            f"Status: `{status['status']}`",
            f"Resume state: `{status['resume_state']}`",
            "",
            "V14 records session and worktree state only. It does not delete worktrees automatically.",
            "",
            "## Cleanup Proposal",
            "",
            f"```bash\n{cleanup}\n```",
            "",
        ]
    )


def session_status(session_dir: Path) -> dict[str, Any]:
    session_dir = resolve_session_out(session_dir)
    session = read_json_obj(session_dir / "session.json", root=session_dir, label="session.json")
    worktree = read_json_obj(session_dir / "worktree.json", root=session_dir, label="worktree.json")
    errors = []
    if session.get("source_head") != current_head():
        errors.append({"code": "ERR_SESSION_STALE_SOURCE", "message": "source HEAD changed"})
    worktree_path = Path(str(worktree.get("path", "")))
    if not worktree_path.is_dir() or worktree_path.is_symlink():
        errors.append({"code": "ERR_SESSION_WORKTREE_INVALID", "message": "worktree path is missing or invalid"})
    status = {
        "tool": TOOL,
        "schema_version": SCHEMA_VERSION,
        "session_id": session.get("session_id"),
        "status": "blocked" if errors else "active",
        "resume_state": "blocked" if errors else "resumable",
        "errors": errors,
        "session_path": rel(session_dir),
        "worktree_path": worktree.get("path"),
    }
    write_json(session_dir / "status.json", status, root=session_dir)
    write_text(session_dir / "resume.md", render_session_resume(session, status), root=session_dir)
    return status


def session_start(v1_run: Path, session_dir: Path) -> dict[str, Any]:
    v1_run = resolve_v1_run(v1_run)
    session_dir = resolve_session_out(session_dir)
    session_id = safe_segment(session_dir.name, code="ERR_SESSION_PATH_UNSAFE")
    if session_dir.exists():
        if session_dir.is_symlink():
            raise RunnerError("ERR_SESSION_PATH_SYMLINK", "session path is a symlink", path=session_dir)
        if not session_dir.is_dir():
            raise RunnerError("ERR_SESSION_PATH_UNSAFE", "session path is not a directory", path=session_dir)
        if read_sentinel(session_dir) is None:
            raise RunnerError("ERR_SESSION_PATH_UNSAFE", "existing session is not runner-owned", path=session_dir)
        shutil.rmtree(session_dir)
    SESSIONS_ROOT.mkdir(parents=True, exist_ok=True)
    session_dir.mkdir(parents=True)
    write_json(session_dir / SENTINEL, sentinel_payload(session_id, v1_run, mode="session"), root=session_dir)
    try:
        context = load_trusted_context(v1_run)
    except RunnerError as exc:
        code = "ERR_SESSION_BLOCKED_RISK" if exc.code == "ERR_RUNNER_BLOCKED_RISK" else exc.code
        raise RunnerError(code, exc.message, path=exc.path) from exc
    source_head = current_head()
    worktree_path = ensure_worktree(session_id, source_head)
    session = {
        "tool": TOOL,
        "schema_version": SCHEMA_VERSION,
        "runtime_version": "14.0.0",
        "session_id": session_id,
        "created_at": now_utc(),
        "v1_run_path": rel(v1_run),
        "source_head": source_head,
        "packet_hash": context["packet_hash"],
        "prompt_hash": context["prompt_hash"],
        "cleanup_proposal": {
            "command": f"git worktree remove {rel(worktree_path)}",
            "auto_delete": False,
        },
    }
    worktree = {
        "session_id": session_id,
        "path": rel(worktree_path),
        "created": True,
        "source_head": source_head,
        "dirty_at_start": bool(git_status_text(worktree_path).strip()),
    }
    locks = {"session_id": session_id, "locked_paths": [], "exclusive": False}
    write_json(session_dir / "session.json", session, root=session_dir)
    write_json(session_dir / "worktree.json", worktree, root=session_dir)
    write_json(session_dir / "locks.json", locks, root=session_dir)
    append_event(session_dir, {"event": "session-started", "created_at": session["created_at"], "source_head": source_head})
    status = session_status(session_dir)
    return status


def session_resume(session_dir: Path) -> dict[str, Any]:
    session_dir = resolve_session_out(session_dir)
    status = session_status(session_dir)
    event = {
        "event": "session-resume-checked",
        "checked_at": now_utc(),
        "status": status["status"],
        "resume_state": status["resume_state"],
    }
    append_event(session_dir, event)
    if status["resume_state"] != "resumable":
        first = status["errors"][0] if status["errors"] else {"code": "ERR_SESSION_STALE_SOURCE", "message": "session is not resumable"}
        raise RunnerError(first["code"], first["message"], path=session_dir)
    return status


def status_from_plan_error(record: dict[str, Any]) -> RunnerError:
    blocked_by = record.get("blocked_by", [])
    if "risk-gate" in blocked_by:
        return RunnerError("ERR_RUNNER_BLOCKED_RISK", "V12 command planner blocked this run by risk gate")
    if "resume-invalidated" in blocked_by:
        return RunnerError("ERR_RUNNER_STALE_RUN", "V12 command planner found stale run artifacts")
    return RunnerError("ERR_RUNNER_STALE_RUN", f"V12 command planner blocked this run: {blocked_by}")


def load_trusted_context(v1_run: Path) -> dict[str, Any]:
    v1_run = resolve_v1_run(v1_run)
    try:
        plan = plan_adapter_command(v1_run)
    except CompileError as exc:
        raise RunnerError("ERR_RUNNER_STALE_RUN", exc.message, path=exc.path) from exc
    if plan.get("decision") != "command_ready":
        raise status_from_plan_error(plan)
    packet = read_json_obj(v1_run / PACKET_REL, root=v1_run, label=PACKET_REL)
    prompt = read_text_file(v1_run / PROMPT_REL, root=v1_run, label=PROMPT_REL)
    allowed_tools = packet.get("allowed_tools", {})
    if not isinstance(allowed_tools, dict):
        raise RunnerError("ERR_RUNNER_STALE_RUN", "packet allowed_tools is malformed", path=v1_run / PACKET_REL)
    if allowed_tools.get("write") or allowed_tools.get("network"):
        raise RunnerError("ERR_RUNNER_WORKTREE_REQUIRED", "V13 requires read-only packets unless caller supplies an isolated worktree")
    return {
        "v1_run": v1_run,
        "packet": packet,
        "prompt": prompt,
        "plan_command": plan,
        "packet_hash": canonical_hash(packet),
        "prompt_hash": sha256_text(prompt),
    }


def run_fixture_command(argv: list[str], prompt: str) -> subprocess.CompletedProcess[str]:
    if tuple(argv) not in ALLOWED_FIXTURE_COMMANDS:
        raise RunnerError("ERR_RUNNER_BACKEND_UNAVAILABLE", "fixture command is not allowlisted")
    try:
        return subprocess.run(argv, cwd=ROOT, input=prompt, text=True, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        return subprocess.CompletedProcess(argv, 124, stdout, stderr + "\nfixture command timed out\n")


def render_transcript(mode: str, attempt: dict[str, Any], stdout: str, stderr: str) -> str:
    return "\n".join(
        [
            "# V13 Runner Transcript",
            "",
            f"Mode: `{mode}`",
            f"Attempt: `{attempt['attempt_id']}`",
            f"Exit code: `{attempt['exit_code']}`",
            "",
            "## Stdout",
            "```text",
            stdout,
            "```",
            "",
            "## Stderr",
            "```text",
            stderr,
            "```",
            "",
        ]
    )


def write_runner_artifacts(out_dir: Path, runner: dict[str, Any], attempt: dict[str, Any], status: dict[str, Any], stdout: str, stderr: str) -> None:
    write_json(out_dir / "runner.json", runner, root=out_dir)
    write_json(out_dir / "attempt.json", attempt, root=out_dir)
    write_text(out_dir / "stdout.txt", stdout, root=out_dir)
    write_text(out_dir / "stderr.txt", stderr, root=out_dir)
    write_text(out_dir / "transcript.md", render_transcript(runner["mode"], attempt, stdout, stderr), root=out_dir)
    write_text(out_dir / "git-status-before.txt", runner["git_status_before"], root=out_dir)
    write_text(out_dir / "git-status-after.txt", runner["git_status_after"], root=out_dir)
    hashes = {
        "runner.json": canonical_hash(runner),
        "attempt.json": canonical_hash(attempt),
        "stdout.txt": sha256_text(stdout),
        "stderr.txt": sha256_text(stderr),
        "transcript.md": sha256_text((out_dir / "transcript.md").read_text()),
        "git-status-before.txt": sha256_text(runner["git_status_before"]),
        "git-status-after.txt": sha256_text(runner["git_status_after"]),
    }
    write_json(out_dir / "hashes.json", hashes, root=out_dir)
    write_json(out_dir / "status.json", status, root=out_dir)


def run(v1_run: Path, out_dir: Path, *, mode: str = "dry-run", fixture_command: list[str] | None = None) -> dict[str, Any]:
    if mode not in ALLOWED_MODES:
        raise RunnerError("ERR_RUNNER_BACKEND_UNAVAILABLE", f"unsupported runner mode: {mode}")
    v1_run = resolve_v1_run(v1_run)
    out_dir = resolve_v13_out(out_dir)
    run_id = out_dir.name
    prepare_out_dir(out_dir, run_id, v1_run, mode="run")
    status_value = "prepared"
    error: dict[str, Any] | None = None
    stdout = ""
    stderr = ""
    exit_code: int | None = None
    started_at = now_utc()
    git_before = git_status_text(ROOT)
    try:
        context = load_trusted_context(v1_run)
        if mode == "codex-fixture":
            if fixture_command is None:
                raise RunnerError("ERR_RUNNER_BACKEND_UNAVAILABLE", "codex-fixture requires a fixture command")
            completed = run_fixture_command(fixture_command, context["prompt"])
            stdout = completed.stdout
            stderr = completed.stderr
            exit_code = completed.returncode
            if completed.returncode != 0:
                if "401" in stderr or "Invalid authentication credentials" in stderr:
                    raise RunnerError("ERR_RUNNER_BACKEND_AUTH", "Codex fixture reported authentication failure")
                raise RunnerError("ERR_RUNNER_BACKEND_FAILED", f"fixture command exited {completed.returncode}")
            status_value = "executed"
    except RunnerError as exc:
        status_value = "blocked" if exc.code in {"ERR_RUNNER_BACKEND_AUTH", "ERR_RUNNER_BLOCKED_RISK", "ERR_RUNNER_STALE_RUN", "ERR_RUNNER_WORKTREE_REQUIRED"} else "failed"
        error = exc.to_record()
        context = {
            "packet_hash": None,
            "prompt_hash": None,
            "plan_command": None,
        }
    git_after = git_status_text(ROOT)
    finished_at = now_utc()
    runner = {
        "tool": TOOL,
        "schema_version": SCHEMA_VERSION,
        "runner_version": RUNNER_VERSION,
        "run_id": run_id,
        "mode": mode,
        "v1_run_path": rel(v1_run),
        "created_at": started_at,
        "git_status_before": git_before,
        "git_status_after": git_after,
        "worktree_created": False,
        "session_attached": False,
    }
    attempt = {
        "attempt_id": "0000",
        "mode": mode,
        "adapter": "codex",
        "command": context.get("plan_command", {}).get("command") if isinstance(context.get("plan_command"), dict) else None,
        "fixture_command": fixture_command,
        "started_at": started_at,
        "finished_at": finished_at,
        "exit_code": exit_code,
        "stdout_path": "stdout.txt",
        "stderr_path": "stderr.txt",
        "transcript_path": "transcript.md",
        "packet_hash": context.get("packet_hash"),
        "prompt_hash": context.get("prompt_hash"),
        "error": error,
    }
    status = {
        "tool": TOOL,
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "status": status_value,
        "error": error,
        "attempt_count": 1 if mode == "codex-fixture" else 0,
        "artifact_paths": {
            "runner": "runner.json",
            "attempt": "attempt.json",
            "stdout": "stdout.txt",
            "stderr": "stderr.txt",
            "transcript": "transcript.md",
            "hashes": "hashes.json",
        },
    }
    write_runner_artifacts(out_dir, runner, attempt, status, stdout, stderr)
    if error is not None:
        raise RunnerError(error["code"], error["message"], path=error.get("path"))
    return status


def mutate_fixture_v1_run(run_dir: Path, fixture: dict[str, Any], plan_path: Path) -> None:
    if fixture.get("stale_prompt"):
        prompt_path = run_dir / PROMPT_REL
        write_text_atomic(prompt_path, prompt_path.read_text() + "\nstale\n", root=run_dir)
    if fixture.get("stale_source_plan"):
        plan = read_json(plan_path)
        plan["objective"] += " changed"
        write_json_atomic(plan_path, plan)


def write_fixture_plan(temp_root: Path, fixture: dict[str, Any]) -> Path:
    plan = read_json(ROOT / fixture["plan"])
    if fixture.get("mutation"):
        plan = mutate_plan(plan, fixture["mutation"])
    path = temp_root / f"{fixture['id']}.workflow.plan.json"
    write_json_atomic(path, plan, root=temp_root)
    return path


def run_fixture(fixture: dict[str, Any], suite_dir: Path, temp_root: Path) -> dict[str, Any]:
    fixture_id = fixture["id"]
    try:
        plan_path = write_fixture_plan(temp_root, fixture)
        v1_run_dir = V1_OUT_ROOT / f"v13-{suite_dir.name}" / fixture_id
        compile_plan(plan_path, v1_run_dir, run_id=f"v13/{fixture_id}", mode="fixture")
        mutate_fixture_v1_run(v1_run_dir, fixture, plan_path)
        out_dir = suite_dir / fixture_id
        try:
            status = run(v1_run_dir, out_dir, mode=fixture["mode"], fixture_command=fixture.get("fixture_command"))
        except RunnerError as exc:
            status_path = out_dir / "status.json"
            status = json.loads(status_path.read_text()) if status_path.is_file() else {"status": "blocked", "error": exc.to_record()}
            if fixture.get("expected_error") != exc.code:
                raise
        expected_status = fixture.get("expected_status")
        if expected_status is not None and status.get("status") != expected_status:
            raise RunnerError("ERR_RUNNER_FIXTURE_FAILED", f"expected status {expected_status}, got {status.get('status')}")
        expected_attempt_count = fixture.get("expected_attempt_count")
        if expected_attempt_count is not None and status.get("attempt_count") != expected_attempt_count:
            raise RunnerError("ERR_RUNNER_FIXTURE_FAILED", f"expected attempt_count {expected_attempt_count}, got {status.get('attempt_count')}")
        expected_error = fixture.get("expected_error")
        actual_error = status.get("error", {}).get("code") if isinstance(status.get("error"), dict) else None
        if expected_error is not None and actual_error != expected_error:
            raise RunnerError("ERR_RUNNER_FIXTURE_FAILED", f"expected error {expected_error}, got {actual_error}")
        return {"id": fixture_id, "status": "pass", "required": fixture.get("required", True)}
    except (RunnerError, CompileError) as exc:
        record = exc.to_record() if isinstance(exc, RunnerError) else {"code": exc.code, "message": exc.message, "path": exc.path}
        record["fixture_id"] = fixture_id
        return {"id": fixture_id, "status": "fail", "required": fixture.get("required", True), "error": record}


def mutate_session_fixture(session_dir: Path, fixture: dict[str, Any]) -> None:
    if fixture.get("stale_source_head"):
        session = read_json_obj(session_dir / "session.json", root=session_dir, label="session.json")
        session["source_head"] = "0" * 40
        write_json(session_dir / "session.json", session, root=session_dir)


def run_session_fixture(fixture: dict[str, Any], suite_dir: Path, temp_root: Path) -> dict[str, Any]:
    fixture_id = fixture["id"]
    try:
        plan_path = write_fixture_plan(temp_root, fixture)
        v1_run_dir = V1_OUT_ROOT / f"v14-{suite_dir.name}" / fixture_id
        compile_plan(plan_path, v1_run_dir, run_id=f"v14/{fixture_id}", mode="fixture")
        session_dir = SESSIONS_ROOT / f"{suite_dir.name}-{fixture_id}"
        if fixture.get("make_session_symlink"):
            SESSIONS_ROOT.mkdir(parents=True, exist_ok=True)
            target = SESSIONS_ROOT / f"{suite_dir.name}-{fixture_id}-target"
            target.mkdir(parents=True, exist_ok=True)
            if session_dir.exists() or session_dir.is_symlink():
                if session_dir.is_dir() and not session_dir.is_symlink():
                    shutil.rmtree(session_dir)
                else:
                    session_dir.unlink()
            session_dir.symlink_to(target, target_is_directory=True)
        try:
            status = session_start(v1_run_dir, session_dir)
            mutate_session_fixture(session_dir, fixture)
            if fixture["type"] == "session-resume":
                status = session_resume(session_dir)
        except RunnerError as exc:
            status_path = session_dir / "status.json"
            status = json.loads(status_path.read_text()) if status_path.is_file() else {"status": "blocked", "errors": [exc.to_record()]}
            if fixture.get("expected_error") != exc.code:
                raise
        expected_status = fixture.get("expected_status")
        if expected_status is not None and status.get("status") != expected_status:
            raise RunnerError("ERR_SESSION_FIXTURE_FAILED", f"expected status {expected_status}, got {status.get('status')}")
        expected_resume_state = fixture.get("expected_resume_state")
        if expected_resume_state is not None and status.get("resume_state") != expected_resume_state:
            raise RunnerError("ERR_SESSION_FIXTURE_FAILED", f"expected resume_state {expected_resume_state}, got {status.get('resume_state')}")
        expected_error = fixture.get("expected_error")
        errors = status.get("errors", [])
        actual_error = errors[0].get("code") if isinstance(errors, list) and errors and isinstance(errors[0], dict) else None
        if expected_error is not None and actual_error != expected_error:
            raise RunnerError("ERR_SESSION_FIXTURE_FAILED", f"expected error {expected_error}, got {actual_error}")
        return {"id": fixture_id, "status": "pass", "required": fixture.get("required", True)}
    except (RunnerError, CompileError) as exc:
        record = exc.to_record() if isinstance(exc, RunnerError) else {"code": exc.code, "message": exc.message, "path": exc.path}
        record["fixture_id"] = fixture_id
        return {"id": fixture_id, "status": "fail", "required": fixture.get("required", True), "error": record}


def evaluate_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    suite_id = Path(out_dir).name
    suite_dir = resolve_v13_out(out_dir)
    if suite_dir.exists():
        sentinel = read_sentinel(suite_dir)
        if sentinel is None or sentinel.get("run_id") != suite_id or sentinel.get("mode") != "manifest":
            raise RunnerError("ERR_RUNNER_PATH_UNSAFE", "existing suite is not runner-owned", path=suite_dir)
        shutil.rmtree(suite_dir)
    suite_dir.mkdir(parents=True)
    write_json(suite_dir / SENTINEL, sentinel_payload(suite_id, suite_dir, mode="manifest"), root=suite_dir)
    temp_root = suite_dir / "_fixture-plans"
    temp_root.mkdir()
    fixtures = manifest["fixtures"]
    required_ids = set(manifest["required_fixture_ids"])
    results = [
        run_session_fixture(fixture, suite_dir, temp_root)
        if str(fixture.get("type", "")).startswith("session-")
        else run_fixture(fixture, suite_dir, temp_root)
        for fixture in fixtures
    ]
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
    write_json(suite_dir / "summary.json", summary, root=suite_dir)
    if summary["decision"] != "keep":
        raise RunnerError("ERR_RUNNER_FIXTURE_FAILED", "manifest decision is kill", path=manifest_path)
    return summary


def self_test() -> None:
    V13_OUT_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dwm-runner-self-test-", dir=V13_OUT_ROOT) as tmp:
        summary = evaluate_manifest(ROOT / "fixtures" / "v13" / "manifest.json", Path(tmp) / "self-test")
    if summary["decision"] != "keep":
        raise RunnerError("ERR_RUNNER_FIXTURE_FAILED", "self-test manifest did not keep")
    print("dwm_runner self-test: pass")


def session_self_test() -> None:
    SESSIONS_ROOT.mkdir(parents=True, exist_ok=True)
    V13_OUT_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dwm-session-self-test-", dir=V13_OUT_ROOT) as tmp:
        summary = evaluate_manifest(ROOT / "fixtures" / "v14" / "manifest.json", Path(tmp) / "session-self-test")
    if summary["decision"] != "keep":
        raise RunnerError("ERR_SESSION_FIXTURE_FAILED", "session self-test manifest did not keep")
    print("dwm_runner session self-test: pass")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", choices=["run", "session"])
    parser.add_argument("session_command", nargs="?", choices=["start", "status", "resume"])
    parser.add_argument("--run")
    parser.add_argument("--out")
    parser.add_argument("--session")
    parser.add_argument("--mode", default="dry-run", choices=sorted(ALLOWED_MODES))
    parser.add_argument("--fixture-command-json")
    parser.add_argument("--manifest")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        if args.self_test:
            if args.command == "session":
                session_self_test()
            else:
                self_test()
        elif args.manifest:
            if not args.out:
                raise RunnerError("ERR_RUNNER_PATH_UNSAFE", "--manifest requires --out")
            summary = evaluate_manifest(Path(args.manifest), Path(args.out))
            print(canonical_json_text({key: summary[key] for key in ["suite_id", "fixture_count", "required_fixture_count", "required_passed", "passed", "failed", "skipped", "decision"]}))
        elif args.command == "run":
            if not args.run or not args.out:
                raise RunnerError("ERR_RUNNER_PATH_UNSAFE", "run requires --run and --out")
            fixture_command = json.loads(args.fixture_command_json) if args.fixture_command_json else None
            if fixture_command is not None and (not isinstance(fixture_command, list) or not all(isinstance(item, str) for item in fixture_command)):
                raise RunnerError("ERR_RUNNER_BACKEND_UNAVAILABLE", "--fixture-command-json must be a string list")
            status = run(Path(args.run), Path(args.out), mode=args.mode, fixture_command=fixture_command)
            print(canonical_json_text(status))
        elif args.command == "session":
            if args.session_command == "start":
                if not args.run or not args.out:
                    raise RunnerError("ERR_SESSION_PATH_UNSAFE", "session start requires --run and --out")
                status = session_start(Path(args.run), Path(args.out))
                print(canonical_json_text(status))
            elif args.session_command == "status":
                if not args.session:
                    raise RunnerError("ERR_SESSION_PATH_UNSAFE", "session status requires --session")
                status = session_status(Path(args.session))
                print(canonical_json_text(status))
            elif args.session_command == "resume":
                if not args.session:
                    raise RunnerError("ERR_SESSION_PATH_UNSAFE", "session resume requires --session")
                status = session_resume(Path(args.session))
                print(canonical_json_text(status))
            else:
                raise RunnerError("ERR_SESSION_PATH_UNSAFE", "expected session start, status, or resume")
        else:
            parser.error("expected --self-test, --manifest, run --run --out, or session subcommand")
    except (RunnerError, CompileError) as exc:
        record = exc.to_record() if isinstance(exc, RunnerError) else {"code": exc.code, "message": exc.message, "path": exc.path}
        print(canonical_json_text(record), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
