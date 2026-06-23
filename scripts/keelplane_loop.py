#!/usr/bin/env python3
"""Keelplane Autonomous Loop v1 deterministic core."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from compile_workflow import (  # noqa: E402
    canonical_hash,
    read_json,
    sha256_text,
    write_json_atomic,
    write_text_atomic,
)
from dwm_live_proof import (  # noqa: E402
    check_components_not_symlink,
    reject_traversal,
    resolve_repo_input,
    run_process as trusted_run_process,
)
from execute_packet import (  # noqa: E402
    ensure_git_worktree,
    execute_codex_cli,
    git_text,
    repo_worktree_paths,
    worktree_path,
    write_text as safe_write_text,
)


TOOL = "keelplane_loop.py"
SCHEMA_VERSION = "keelplane-loop-v1"
OUT_ROOT = ROOT / "out" / "keelplane-loop"
WORKTREE_DIRNAME = "worktree"
JOURNAL = "journal.json"
JOURNAL_EVENTS = "journal.ndjson"
STATUS = "status.json"
SENTINEL = ".keelplane-loop-owned.json"
TERMINAL_EXPLANATIONS = {
    "verified-complete": "all declared checks passed; this does not mean the feature is correct in unchecked ways",
    "blocked": "risk gate, prerequisite, or budget cap stopped the loop",
    "failed": "a phase did not pass declared checks after the allowed repair",
}
SIDE_CHANNEL_NAMES = {
    "conftest.py",
    "pytest.ini",
    "setup.cfg",
    "sitecustomize.py",
}
SIDE_CHANNEL_SUFFIXES = (".pth",)
SIDE_CHANNEL_PARTS = {"pytest_plugins", "plugins"}


class LoopError(ValueError):
    """Structured Keelplane loop failure."""

    def __init__(self, code: str, message: str, *, path: Path | str | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.path = str(path) if path is not None else None

    def to_record(self) -> dict[str, Any]:
        record: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.path is not None:
            record["path"] = self.path
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


def safe_rel_path(value: str, *, label: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        raise LoopError("ERR_KEELPLANE_PATH_UNSAFE", f"{label} must be repo-relative", path=value)
    reject_traversal(path, code="ERR_KEELPLANE_PATH_UNSAFE")
    if path in {Path("."), Path("..")}:
        raise LoopError("ERR_KEELPLANE_PATH_UNSAFE", f"{label} must name a file", path=value)
    return path


def resolve_existing_repo_file(value: str, *, label: str) -> Path:
    path = resolve_repo_input(value, code="ERR_KEELPLANE_PATH_UNSAFE")
    if not path.is_file():
        raise LoopError("ERR_KEELPLANE_PATH_UNSAFE", f"{label} must be a file", path=value)
    return path


def resolve_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_KEELPLANE_OUT_UNSAFE")
    candidate = raw if raw.is_absolute() else ROOT / raw
    check_components_not_symlink(candidate, code="ERR_KEELPLANE_PATH_SYMLINK")
    resolved = candidate.resolve(strict=False)
    root = OUT_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise LoopError("ERR_KEELPLANE_OUT_UNSAFE", f"output must resolve under {root}", path=value) from exc
    if resolved == root:
        raise LoopError("ERR_KEELPLANE_OUT_UNSAFE", "output must name a run directory", path=value)
    return resolved


def read_manifest(path: Path) -> dict[str, Any]:
    data = read_json(path)
    if data.get("schema_version") != "keelplane-loop-fixture-v1":
        raise LoopError("ERR_KEELPLANE_MANIFEST_INVALID", "unsupported manifest schema_version", path=path)
    fixtures = data.get("fixtures")
    if not isinstance(fixtures, list) or not fixtures:
        raise LoopError("ERR_KEELPLANE_MANIFEST_INVALID", "manifest fixtures must be a non-empty list", path=path)
    return data


def phase_packet(fixture_id: str, phase: dict[str, Any], index: int) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "fixture_id": fixture_id,
        "phase_id": require_str(phase, "id"),
        "phase_index": index,
        "target_files": sorted(require_str_list(phase, "target_files")),
        "verification_files": sorted(require_str_list(phase, "verification_files")),
        "verification_command": require_str_list(phase, "verification_command"),
        "mode": "target-files-only",
    }


def require_str(item: dict[str, Any], key: str) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value:
        raise LoopError("ERR_KEELPLANE_MANIFEST_INVALID", f"{key} must be a non-empty string")
    return value


def require_str_list(item: dict[str, Any], key: str) -> list[str]:
    value = item.get(key)
    if not isinstance(value, list) or not value or not all(isinstance(part, str) and part for part in value):
        raise LoopError("ERR_KEELPLANE_MANIFEST_INVALID", f"{key} must be a non-empty string list")
    return list(value)


def prepare_out_dir(out_dir: Path, *, resume: bool) -> None:
    if resume:
        if not out_dir.is_dir():
            raise LoopError("ERR_KEELPLANE_RESUME_INVALID", "resume output is missing", path=out_dir)
        return
    if out_dir.exists():
        if out_dir.is_symlink() or not out_dir.is_dir():
            raise LoopError("ERR_KEELPLANE_OUT_UNSAFE", "output exists and is not a directory", path=out_dir)
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    write_json_atomic(out_dir / SENTINEL, {"tool": TOOL, "schema_version": SCHEMA_VERSION, "created_at": now_utc()}, root=out_dir)


def declared_target_files(phases: list[dict[str, Any]]) -> list[str]:
    targets: set[str] = set()
    for phase in phases:
        targets.update(safe_rel_path(path, label="target file").as_posix() for path in require_str_list(phase, "target_files"))
    return sorted(targets)


def pristine_verification_map(phases: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    pristine: dict[str, dict[str, str]] = {}
    for phase in phases:
        for value in require_str_list(phase, "verification_files"):
            rel_path = safe_rel_path(value, label="verification file")
            source = resolve_existing_repo_file(value, label="verification file")
            text = source.read_text(encoding="utf-8")
            pristine[rel_path.as_posix()] = {"text": text, "sha256": sha256_text(text)}
    return pristine


def init_worktree(worktree: Path, pristine: dict[str, dict[str, str]]) -> str:
    if worktree.exists():
        shutil.rmtree(worktree)
    worktree.mkdir(parents=True)
    for rel_path, record in pristine.items():
        target = worktree / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        write_text_atomic(target, record["text"], root=worktree)
    run_git(["init"], worktree)
    run_git(["config", "user.email", "keelplane@example.invalid"], worktree)
    run_git(["config", "user.name", "Keelplane Loop"], worktree)
    run_git(["add", "."], worktree)
    run_git(["commit", "-m", "keelplane seed"], worktree)
    return run_git(["rev-parse", "HEAD"], worktree).strip()


def live_worktree_name(out_dir: Path) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", out_dir.name).strip(".-_")
    if not slug:
        slug = "run"
    return f"keelplane-{slug}-{sha256_text(str(out_dir.resolve(strict=False)))[:12]}"


def init_live_worktree(name: str) -> tuple[Path, str]:
    path = worktree_path(name)
    if path.exists():
        registered = path.resolve(strict=False) in repo_worktree_paths()
        if registered:
            git_text(["worktree", "remove", "--force", str(path)], ROOT)
        else:
            shutil.rmtree(path)
    worktree = ensure_git_worktree(name)
    return worktree, run_git(["rev-parse", "HEAD"], worktree).strip()


def run_git(args: list[str], cwd: Path) -> str:
    return git_text(args, cwd).strip()


def load_journal(out_dir: Path) -> dict[str, Any]:
    path = out_dir / JOURNAL
    if not path.is_file() or path.is_symlink():
        raise LoopError("ERR_KEELPLANE_RESUME_INVALID", "journal is missing", path=path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise LoopError("ERR_KEELPLANE_RESUME_INVALID", "journal root must be an object", path=path)
    verify_journal_chain(data)
    return data


def verify_journal_chain(journal: dict[str, Any]) -> None:
    previous = "0" * 64
    for phase in journal.get("phases", []):
        if not isinstance(phase, dict):
            raise LoopError("ERR_KEELPLANE_RESUME_INVALID", "journal phase must be an object")
        expected_previous = phase.get("previous_evidence_hash")
        recorded_hash = phase.get("phase_evidence_hash")
        if expected_previous != previous:
            raise LoopError("ERR_KEELPLANE_RESUME_INVALID", "journal evidence chain is stale")
        body = {key: value for key, value in phase.items() if key != "phase_evidence_hash"}
        actual = canonical_hash(body)
        if actual != recorded_hash:
            raise LoopError("ERR_KEELPLANE_RESUME_INVALID", "journal evidence hash mismatch")
        previous = recorded_hash


def write_journal(out_dir: Path, journal: dict[str, Any]) -> None:
    write_json_atomic(out_dir / JOURNAL, journal, root=out_dir)


def append_journal_event(out_dir: Path, event: dict[str, Any]) -> None:
    path = out_dir / JOURNAL_EVENTS
    line = json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)


def write_status(out_dir: Path, status: dict[str, Any]) -> None:
    write_json_atomic(out_dir / STATUS, status, root=out_dir)


def restore_verification_files(worktree: Path, pristine: dict[str, dict[str, str]], scope: set[str]) -> dict[str, str]:
    restored: dict[str, str] = {}
    for rel_path in sorted(scope):
        record = pristine[rel_path]
        target = worktree / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        write_text_atomic(target, record["text"], root=worktree)
        restored[rel_path] = record["sha256"]
    return restored


def side_channel_paths(worktree: Path, baseline: set[str]) -> list[str]:
    found: list[str] = []
    for path in sorted(item for item in worktree.rglob("*") if item.is_file()):
        rel_path = path.relative_to(worktree).as_posix()
        if rel_path in baseline:
            continue
        name = path.name
        parts = set(path.parts)
        if (
            name in SIDE_CHANNEL_NAMES
            or name.endswith(SIDE_CHANNEL_SUFFIXES)
            or bool(parts & SIDE_CHANNEL_PARTS)
        ):
            found.append(rel_path)
    return found


def normalize_pytest_command(command: list[str]) -> list[str]:
    argv = list(command)
    if argv and argv[0] == "python":
        argv[0] = sys.executable
    if len(argv) >= 3 and argv[1:3] == ["-m", "pytest"] and "-p" not in argv:
        argv = [argv[0], "-m", "pytest", "-p", "no:cacheprovider", *argv[3:]]
    return argv


def run_verification_command(command: list[str], worktree: Path, timeout_seconds: int) -> dict[str, Any]:
    argv = normalize_pytest_command(command)
    old_disable = os.environ.get("PYTEST_DISABLE_PLUGIN_AUTOLOAD")
    os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    try:
        process = trusted_run_process(argv, worktree, timeout_seconds=timeout_seconds)
    finally:
        if old_disable is None:
            os.environ.pop("PYTEST_DISABLE_PLUGIN_AUTOLOAD", None)
        else:
            os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = old_disable
    return {
        "argv": argv,
        "returncode": process.returncode,
        "passed": process.returncode == 0,
        "stdout_hash": sha256_text(process.stdout),
        "stderr_hash": sha256_text(process.stderr),
        "stdout": process.stdout,
        "stderr": process.stderr,
    }


def verify_phase_scope(
    *,
    worktree: Path,
    phases: list[dict[str, Any]],
    current_index: int,
    pristine: dict[str, dict[str, str]],
    verified_phase_indexes: list[int],
    timeout_seconds: int,
) -> dict[str, Any]:
    indexes = [*verified_phase_indexes, current_index]
    scope: set[str] = set()
    for index in indexes:
        scope.update(safe_rel_path(path, label="verification file").as_posix() for path in require_str_list(phases[index], "verification_files"))
    restored = restore_verification_files(worktree, pristine, scope)
    baseline = set(pristine)
    side_channels = side_channel_paths(worktree, baseline)
    if side_channels:
        return {
            "verified": False,
            "restored_hashes": restored,
            "side_channels": side_channels,
            "commands": [],
            "invalidators": [
                {
                    "code": "ERR_KEELPLANE_VERIFY_SUBVERSION",
                    "message": "worker-created verification-affecting file",
                    "paths": side_channels,
                }
            ],
        }
    commands = [run_verification_command(require_str_list(phases[index], "verification_command"), worktree, timeout_seconds) for index in indexes]
    passed = all(command["passed"] for command in commands)
    return {
        "verified": passed,
        "restored_hashes": restored,
        "side_channels": [],
        "commands": commands,
        "invalidators": [] if passed else [{"code": "ERR_KEELPLANE_VERIFY_FAILED", "message": "declared checks did not pass"}],
    }


def target_artifacts(worktree: Path, phase: dict[str, Any]) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    for value in require_str_list(phase, "target_files"):
        rel_path = safe_rel_path(value, label="target file").as_posix()
        path = worktree / rel_path
        if not path.exists() or path.is_symlink() or not path.is_file():
            artifacts.append({"path": rel_path, "present": False})
            continue
        data = path.read_bytes()
        artifacts.append(
            {
                "path": rel_path,
                "present": True,
                "byte_count": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    return artifacts


def apply_recording(recording_path: Path, worktree: Path, allowed_targets: set[str], *, attempt: int) -> dict[str, Any]:
    recording = read_json(recording_path)
    if recording.get("fail"):
        return {
            "mode": "fixture",
            "status": "failed",
            "attempt": attempt,
            "recording": rel(recording_path),
            "message": str(recording.get("message", "recorded failure")),
        }
    writes = recording.get("writes")
    if not isinstance(writes, dict):
        raise LoopError("ERR_KEELPLANE_RECORDING_INVALID", "recording writes must be an object", path=recording_path)
    touched: list[str] = []
    unauthorized: list[str] = []
    for raw_path, content in writes.items():
        if not isinstance(raw_path, str) or not isinstance(content, str):
            raise LoopError("ERR_KEELPLANE_RECORDING_INVALID", "recording writes must map paths to strings", path=recording_path)
        rel_path = safe_rel_path(raw_path, label="recording path").as_posix()
        if rel_path not in allowed_targets:
            unauthorized.append(rel_path)
        target = worktree / rel_path
        safe_write_text(target, content, root=worktree)
        touched.append(rel_path)
    return {
        "mode": "fixture",
        "status": "executed",
        "attempt": attempt,
        "recording": rel(recording_path),
        "files_touched": sorted(touched),
        "unauthorized_writes": sorted(unauthorized),
    }


def execute_phase(
    *,
    mode: str,
    phase: dict[str, Any],
    worktree: Path,
    out_dir: Path,
    packet: dict[str, Any],
    attempt: int,
    approve_live_codex: bool,
    live_worktree: str | None,
    timeout_seconds: int,
) -> dict[str, Any]:
    target_files = {safe_rel_path(path, label="target file").as_posix() for path in require_str_list(phase, "target_files")}
    verification_files = {safe_rel_path(path, label="verification file").as_posix() for path in require_str_list(phase, "verification_files")}
    allowed_targets = target_files | verification_files
    if mode == "fixture":
        key = "recording" if attempt == 0 else "repair_recording"
        recording_value = phase.get(key) or phase.get("recording")
        if not isinstance(recording_value, str):
            raise LoopError("ERR_KEELPLANE_RECORDING_INVALID", f"{key} must be a string")
        recording = resolve_existing_repo_file(recording_value, label="recording")
        return apply_recording(recording, worktree, allowed_targets, attempt=attempt)
    if mode == "installed-codex":
        if not approve_live_codex:
            raise LoopError("ERR_KEELPLANE_APPROVAL_REQUIRED", "installed-codex requires --i-approve-live-codex")
        plan_value = phase.get("plan")
        if not isinstance(plan_value, str):
            raise LoopError("ERR_KEELPLANE_MANIFEST_INVALID", "installed-codex phases must declare plan")
        v1_run = ROOT / "out" / "v1" / f"keelplane-{out_dir.name}-{packet['phase_id']}"
        from compile_workflow import compile_plan  # imported lazily for the live-only path

        compile_plan(resolve_existing_repo_file(plan_value, label="phase plan"), v1_run, run_id=f"keelplane/{out_dir.name}/{packet['phase_id']}")
        result = execute_codex_cli(
            v1_run,
            out_dir=ROOT / "out" / "v2" / f"keelplane-{out_dir.name}-{packet['phase_id']}-{attempt}",
            worktree=live_worktree,
            codex_cli={"mode": "installed-codex", "timeout_seconds": timeout_seconds},
            verification_commands=None,
        )
        return {
            "mode": "installed-codex",
            "status": result["status"]["status"],
            "attempt": attempt,
            "v2_status_hash": canonical_hash(result["status"]),
        }
    raise LoopError("ERR_KEELPLANE_MODE_INVALID", f"unsupported executor mode: {mode}")


def checkpoint(worktree: Path, phase_id: str) -> str:
    run_git(["add", "."], worktree)
    if not run_git(["status", "--short"], worktree):
        return run_git(["rev-parse", "HEAD"], worktree)
    run_git(["commit", "-m", f"keelplane checkpoint: {phase_id}"], worktree)
    return run_git(["rev-parse", "HEAD"], worktree)


def verified_ref_name(out_dir: Path) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", out_dir.name).strip(".-_")
    if not slug:
        slug = "run"
    return f"refs/keelplane/{slug}"


def stamp_verified_ref(worktree: Path, out_dir: Path, checkpoint_commit: str) -> str:
    ref_name = verified_ref_name(out_dir)
    run_git(["update-ref", ref_name, checkpoint_commit], worktree)
    return ref_name


def phase_evidence(
    *,
    fixture_id: str,
    phase: dict[str, Any],
    packet: dict[str, Any],
    previous_hash: str,
    executor_evidence: list[dict[str, Any]],
    verification: dict[str, Any],
    artifacts: list[dict[str, Any]],
    checkpoint_commit: str,
) -> dict[str, Any]:
    body = {
        "fixture_id": fixture_id,
        "phase_id": require_str(phase, "id"),
        "previous_evidence_hash": previous_hash,
        "packet_hash": canonical_hash(packet),
        "executor_evidence_hash": canonical_hash(executor_evidence),
        "verification_hash": canonical_hash(
            {
                "verified": verification["verified"],
                "restored_hashes": verification["restored_hashes"],
                "commands": [
                    {
                        "argv": command["argv"],
                        "returncode": command["returncode"],
                        "passed": command["passed"],
                        "stdout_hash": command["stdout_hash"],
                        "stderr_hash": command["stderr_hash"],
                    }
                    for command in verification["commands"]
                ],
                "side_channels": verification["side_channels"],
                "invalidators": verification["invalidators"],
            }
        ),
        "target_artifacts": artifacts,
        "checkpoint_commit": checkpoint_commit,
        "recorded_at": now_utc(),
    }
    return {**body, "phase_evidence_hash": canonical_hash(body)}


def terminal_status(
    *,
    terminal: str,
    fixture_id: str,
    journal: dict[str, Any],
    invalidators: list[dict[str, Any]] | None = None,
    artifacts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    status = {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "fixture_id": fixture_id,
        "terminal_state": terminal,
        "terminal_explanation": TERMINAL_EXPLANATIONS[terminal],
        "verified_phase_count": len(journal.get("phases", [])),
        "evidence_chain_head": journal.get("chain_head", "0" * 64),
        "invalidators": invalidators or [],
        "checked_at": now_utc(),
    }
    if artifacts is not None:
        status["target_artifacts"] = artifacts
    return {**status, "status_hash": canonical_hash(status)}


def run_loop(
    fixture: dict[str, Any],
    out_dir: Path,
    *,
    mode: str = "fixture",
    resume: bool = False,
    approve_live_codex: bool = False,
    max_repairs_per_phase: int = 1,
    timeout_seconds: int = 30,
    max_calls: int = 12,
    max_wall_seconds: int = 300,
    stop_after_phases: int | None = None,
) -> dict[str, Any]:
    fixture_id = require_str(fixture, "id")
    phases = fixture.get("phases")
    if not isinstance(phases, list) or not phases:
        raise LoopError("ERR_KEELPLANE_MANIFEST_INVALID", "fixture phases must be a non-empty list")
    target_files = declared_target_files(phases)
    pristine = pristine_verification_map(phases)
    prepare_out_dir(out_dir, resume=resume)
    live_worktree = live_worktree_name(out_dir) if mode == "installed-codex" else None
    worktree = worktree_path(live_worktree) if live_worktree is not None else out_dir / WORKTREE_DIRNAME
    if resume:
        journal = load_journal(out_dir)
        journal.setdefault("run_base", journal.get("seed_commit"))
        journal.setdefault("target_files", target_files)
        if not worktree.is_dir():
            raise LoopError("ERR_KEELPLANE_RESUME_INVALID", "worktree is missing", path=worktree)
        last_commit = journal.get("last_checkpoint")
        if not isinstance(last_commit, str) or not last_commit:
            raise LoopError("ERR_KEELPLANE_RESUME_INVALID", "last checkpoint is missing")
        run_git(["reset", "--hard", last_commit], worktree)
    else:
        seed_commit = init_live_worktree(live_worktree)[1] if live_worktree is not None else init_worktree(worktree, pristine)
        journal = {
            "schema_version": SCHEMA_VERSION,
            "fixture_id": fixture_id,
            "mode": mode,
            "run_base": seed_commit,
            "seed_commit": seed_commit,
            "last_checkpoint": seed_commit,
            "target_files": target_files,
            "chain_head": "0" * 64,
            "phases": [],
        }
        write_journal(out_dir, journal)
        append_journal_event(
            out_dir,
            {
                "event": "seed",
                "fixture_id": fixture_id,
                "seed_commit": seed_commit,
                "chain_head": journal["chain_head"],
                "recorded_at": now_utc(),
            },
        )
    completed = len(journal["phases"])
    verified_phase_indexes = list(range(completed))
    call_count = 0
    started = time.monotonic()

    for index in range(completed, len(phases)):
        phase = phases[index]
        phase_id = require_str(phase, "id")
        if time.monotonic() - started > max_wall_seconds:
            status = terminal_status(
                terminal="blocked",
                fixture_id=fixture_id,
                journal=journal,
                invalidators=[{"code": "ERR_KEELPLANE_BUDGET_EXCEEDED", "message": "wall-time budget exceeded"}],
            )
            write_status(out_dir, status)
            return status
        restore_scope = set()
        for prior_index in [*verified_phase_indexes, index]:
            restore_scope.update(safe_rel_path(path, label="verification file").as_posix() for path in require_str_list(phases[prior_index], "verification_files"))
        restore_verification_files(worktree, pristine, restore_scope)
        packet = phase_packet(fixture_id, phase, index)
        executor_records: list[dict[str, Any]] = []
        verification: dict[str, Any] | None = None
        for attempt in range(max_repairs_per_phase + 1):
            if call_count >= max_calls:
                status = terminal_status(
                    terminal="blocked",
                    fixture_id=fixture_id,
                    journal=journal,
                    invalidators=[{"code": "ERR_KEELPLANE_BUDGET_EXCEEDED", "message": "executor call budget exceeded"}],
                )
                write_status(out_dir, status)
                return status
            call_count += 1
            executor_records.append(
                execute_phase(
                    mode=mode,
                    phase=phase,
                    worktree=worktree,
                    out_dir=out_dir,
                    packet=packet,
                    attempt=attempt,
                    approve_live_codex=approve_live_codex,
                    live_worktree=live_worktree,
                    timeout_seconds=timeout_seconds,
                )
            )
            verification = verify_phase_scope(
                worktree=worktree,
                phases=phases,
                current_index=index,
                pristine=pristine,
                verified_phase_indexes=verified_phase_indexes,
                timeout_seconds=timeout_seconds,
            )
            if verification["verified"]:
                commit = checkpoint(worktree, phase_id)
                artifacts = target_artifacts(worktree, phase)
                evidence = phase_evidence(
                    fixture_id=fixture_id,
                    phase=phase,
                    packet=packet,
                    previous_hash=journal["chain_head"],
                    executor_evidence=executor_records,
                    verification=verification,
                    artifacts=artifacts,
                    checkpoint_commit=commit,
                )
                journal["phases"].append(evidence)
                journal["chain_head"] = evidence["phase_evidence_hash"]
                journal["last_checkpoint"] = commit
                write_journal(out_dir, journal)
                append_journal_event(out_dir, {"event": "phase-verified", **evidence})
                verified_phase_indexes.append(index)
                break
            if attempt >= max_repairs_per_phase:
                status = terminal_status(
                    terminal="failed",
                    fixture_id=fixture_id,
                    journal=journal,
                    invalidators=verification["invalidators"],
                    artifacts=target_artifacts(worktree, phase),
                )
                write_status(out_dir, status)
                return status
        if stop_after_phases is not None and len(journal["phases"]) >= stop_after_phases:
            status = terminal_status(
                terminal="blocked",
                fixture_id=fixture_id,
                journal=journal,
                invalidators=[{"code": "ERR_KEELPLANE_STOP_AFTER_PHASES", "message": "deterministic resume fixture paused mid-run"}],
            )
            write_status(out_dir, status)
            return status

    status = terminal_status(terminal="verified-complete", fixture_id=fixture_id, journal=journal)
    ref_name = stamp_verified_ref(worktree, out_dir, str(journal["last_checkpoint"]))
    journal["terminal_state"] = status["terminal_state"]
    journal["evidence_chain_head"] = status["evidence_chain_head"]
    journal["status_hash"] = status["status_hash"]
    journal["verified_ref"] = ref_name
    write_journal(out_dir, journal)
    append_journal_event(
        out_dir,
        {
            "event": "verified-complete",
            "last_checkpoint": journal["last_checkpoint"],
            "verified_ref": ref_name,
            "chain_head": journal["chain_head"],
            "status_hash": status["status_hash"],
            "recorded_at": now_utc(),
        },
    )
    write_status(out_dir, status)
    return status


def run_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_manifest(resolve_existing_repo_file(str(manifest_path), label="manifest"))
    prepare_out_dir(out_dir, resume=False)
    records: list[dict[str, Any]] = []
    passed = 0
    for fixture in manifest["fixtures"]:
        fixture_id = require_str(fixture, "id")
        fixture_out = out_dir / fixture_id
        try:
            if isinstance(fixture.get("resume_after_phases"), int):
                run_loop(fixture, fixture_out, stop_after_phases=int(fixture["resume_after_phases"]))
                status = run_loop(fixture, fixture_out, resume=True)
            else:
                status = run_loop(fixture, fixture_out)
            expected = fixture.get("expected_terminal")
            chain = json.loads((fixture_out / JOURNAL).read_text(encoding="utf-8")) if (fixture_out / JOURNAL).is_file() else {}
            chain_ok = status.get("evidence_chain_head") == chain.get("chain_head")
            ok = status.get("terminal_state") == expected and chain_ok
            records.append(
                {
                    "id": fixture_id,
                    "status": "pass" if ok else "fail",
                    "expected_terminal": expected,
                    "actual_terminal": status.get("terminal_state"),
                    "evidence_chain_head": status.get("evidence_chain_head"),
                    "phase_count": status.get("verified_phase_count"),
                }
            )
            if ok:
                passed += 1
        except Exception as exc:  # noqa: BLE001 - manifest records fixture failures.
            records.append({"id": fixture_id, "status": "fail", "error": str(exc)})
    total = len(manifest["fixtures"])
    summary = {
        "suite_id": manifest.get("suite_id", out_dir.name),
        "passed": passed,
        "total": total,
        "failed": total - passed,
        "decision": "keep" if passed == total else "kill",
        "fixtures": records,
    }
    write_json_atomic(out_dir / "summary.json", summary, root=out_dir)
    return summary


def run_single_fixture(
    manifest_path: Path,
    out_dir: Path,
    *,
    mode: str,
    resume: bool,
    approve_live_codex: bool,
    timeout_seconds: int,
    max_calls: int,
    max_wall_seconds: int,
) -> dict[str, Any]:
    manifest = read_manifest(resolve_existing_repo_file(str(manifest_path), label="manifest"))
    fixtures = manifest["fixtures"]
    if len(fixtures) != 1:
        raise LoopError("ERR_KEELPLANE_MANIFEST_INVALID", "run requires a manifest with exactly one fixture", path=manifest_path)
    return run_loop(
        fixtures[0],
        out_dir,
        mode=mode,
        resume=resume,
        approve_live_codex=approve_live_codex,
        timeout_seconds=timeout_seconds,
        max_calls=max_calls,
        max_wall_seconds=max_wall_seconds,
    )


def self_test() -> dict[str, Any]:
    out_dir = OUT_ROOT / "self-test"
    summary = run_manifest(ROOT / "fixtures" / "keelplane-loop" / "manifest.json", out_dir)
    if summary["decision"] != "keep":
        raise LoopError("ERR_KEELPLANE_SELF_TEST_FAILED", "fixture suite did not keep", path=out_dir / "summary.json")
    by_id = {record["id"]: record for record in summary["fixtures"]}
    required = {
        "clean-multi-phase",
        "fault-injected",
        "regression-guard",
        "resume-mid-run",
        "immutable-restore",
        "side-channel",
    }
    missing = sorted(required - set(by_id))
    if missing:
        raise LoopError("ERR_KEELPLANE_SELF_TEST_FAILED", f"missing self-test records: {missing}")
    for fixture_id in required:
        if by_id[fixture_id]["status"] != "pass":
            raise LoopError("ERR_KEELPLANE_SELF_TEST_FAILED", f"{fixture_id} did not pass")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Keelplane Autonomous Loop v1 deterministic core")
    parser.add_argument("command", nargs="?", choices=["run"])
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--manifest")
    parser.add_argument("--out")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--mode", choices=["fixture", "installed-codex"], default="fixture")
    parser.add_argument("--timeout-seconds", type=int, default=30)
    parser.add_argument("--max-calls", type=int, default=12)
    parser.add_argument("--max-wall-seconds", type=int, default=300)
    parser.add_argument("--i-approve-live-codex", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            if not args.manifest or not args.out:
                raise LoopError("ERR_KEELPLANE_ARGS", "run requires --manifest and --out")
            status = run_single_fixture(
                Path(args.manifest),
                resolve_out(args.out),
                mode=args.mode,
                resume=args.resume,
                approve_live_codex=args.i_approve_live_codex,
                timeout_seconds=args.timeout_seconds,
                max_calls=args.max_calls,
                max_wall_seconds=args.max_wall_seconds,
            )
            print(json.dumps({key: status[key] for key in ["terminal_state", "verified_phase_count", "evidence_chain_head"]}, sort_keys=True))
            return 0 if status["terminal_state"] == "verified-complete" else 1
        if args.self_test:
            summary = self_test()
            print(f"keelplane_loop self-test: pass ({summary['passed']}/{summary['total']})")
            return 0
        if args.manifest:
            if not args.out:
                raise LoopError("ERR_KEELPLANE_ARGS", "--manifest requires --out")
            summary = run_manifest(Path(args.manifest), resolve_out(args.out))
            print(json.dumps({key: summary[key] for key in ["decision", "passed", "total", "failed"]}, sort_keys=True))
            return 0 if summary["decision"] == "keep" else 1
        raise LoopError("ERR_KEELPLANE_ARGS", "expected --self-test or --manifest")
    except LoopError as exc:
        print(json.dumps({"error": exc.to_record()}, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
