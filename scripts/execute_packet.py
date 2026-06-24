#!/usr/bin/env python3
"""Execute or prepare one trusted V1 first-slice packet."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
import subprocess
import sys
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
    read_json,
    resume_run,
    sha256_text,
    write_text_atomic,
)


TOOL = "execute_packet.py"
SCHEMA_VERSION = "1.0"
ADAPTER_VERSION = "0.1.0"
V1_OUT_ROOT = ROOT / "out" / "v1"
V2_OUT_ROOT = ROOT / "out" / "v2"
V25_OUT_ROOT = ROOT / "out" / "v2.5"
WORKTREE_ROOT = ROOT.parent / f"{ROOT.name}.dwf-worktrees"
SENTINEL = ".execute_packet-owned.json"
ATTEMPT_CONTRACTS = "attempt-contracts.json"
REVIEW_CONTRACTS = "review-contracts.json"
REPAIR_CONTRACTS = "repair-contracts.json"
PACKET_ID = "001-first-slice"
PROMPT_REL = "packets/001-first-slice.prompt.md"
PACKET_REL = "packets/001-first-slice.packet.json"
APPROVAL_REL = "gates/approval-state.json"
TRUSTED_V2_MANIFEST = ROOT / "fixtures" / "v2" / "manifest.json"
TRUSTED_V25_MANIFEST = ROOT / "fixtures" / "v2.5" / "manifest.json"
ALLOWED_FIXTURE_TYPES = {
    "dry-run",
    "local-shell",
    "codex-cli",
    "manifest-required-failure",
}
ALLOWED_V25_FIXTURE_TYPES = {
    "review-approved",
    "review-request-changes",
    "review-resume",
    "review-tamper-invalid",
    "review-stale-after-new-attempt",
    "review-replacement-after-new-attempt",
    "repair-prepared",
    "repair-no-actionable",
    "repair-stale-after-new-review",
}
ALLOWED_PYTHON_FIXTURE_SNIPPETS = {
    "from pathlib import Path; print(Path.cwd().name)",
    "import sys; print('before failure'); print('boom', file=sys.stderr); sys.exit(3)",
    "print('should not run')",
    "print('backend should not run')",
    "print('backend ready')",
    "print('wrong repo')",
    "print('local shell ok')",
    "print('inventory.json')",
    "from pathlib import Path; Path('inventory.json').write_text('{}')",
    "from pathlib import Path; raise SystemExit(0 if Path('inventory.json').is_file() else 1)",
    "import json, subprocess; from pathlib import Path; status=subprocess.run(['git','status','--short'],check=True,text=True,stdout=subprocess.PIPE).stdout.splitlines(); inventory={'release_surfaces':['scripts/compile_workflow.py','scripts/execute_packet.py','scripts/run_workflow.py','fixtures/v2/manifest.json','fixtures/v3/manifest.json'],'evidence_commands':['python scripts/check_contract.py','python scripts/execute_packet.py --manifest fixtures/v2/manifest.json --out out/v2/final','python scripts/run_workflow.py --self-test'],'dirty_files':{'classes':['modified','added','untracked'],'git_status_short':status},'open_risks':['V2 fixture execution proves checked artifacts, not full semantic agent execution']}; Path('inventory.json').write_text(json.dumps(inventory,sort_keys=True))",
    "import json; from pathlib import Path; data=json.loads(Path('inventory.json').read_text()); required={'release_surfaces','evidence_commands','dirty_files','open_risks'}; ok=required <= set(data) and data['release_surfaces'] and data['evidence_commands'] and isinstance(data['dirty_files'], dict) and data['open_risks']; print(json.dumps(data,sort_keys=True)); raise SystemExit(0 if ok else 1)",
    "print('verify ok')",
    "print('verification pass')",
    "import sys; print('verification failed', file=sys.stderr); sys.exit(4)",
    "import sys; sys.exit(2)",
    "import sys; sys.exit(7)",
    "import sys; prompt=sys.stdin.read(); print('codex fixture ok'); print(len(prompt))",
    "import sys; print('codex ok'); print(len(sys.stdin.read()))",
    "import sys; print('Invalid authentication credentials', file=sys.stderr); sys.exit(1)",
    "import sys; print('401 Invalid authentication credentials', file=sys.stderr); sys.exit(1)",
    "print('first attempt')",
}


class ExecError(ValueError):
    """Structured V2 adapter failure."""

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
    return (
        dt.datetime.now(dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def reject_traversal(path: Path, code: str, message: str) -> None:
    if any(part == ".." for part in path.parts):
        raise ExecError(code, message, path=path)


def check_components_not_symlink(path: Path, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        try:
            if current.is_symlink():
                raise ExecError(code, "path contains a symlink", path=current)
        except OSError as exc:
            raise ExecError(
                "ERR_EXEC_OUTSIDE_REPO", f"cannot inspect path: {exc}", path=current
            ) from exc


def resolve_under_out(
    value: str | Path, root: Path, *, unsafe_code: str, symlink_code: str, label: str
) -> Path:
    raw = Path(value)
    reject_traversal(
        raw, unsafe_code, f"{label} path must not contain parent traversal"
    )
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    out_root = root.resolve(strict=False)
    forbidden = {ROOT.resolve(), (ROOT / "out").resolve(strict=False), out_root}
    if resolved in forbidden:
        raise ExecError(
            unsafe_code, f"{label} path must name a run directory", path=value
        )
    try:
        resolved.relative_to(out_root)
    except ValueError as exc:
        raise ExecError(
            unsafe_code, f"{label} path must resolve under {out_root}", path=value
        ) from exc
    check_components_not_symlink(candidate, symlink_code)
    return resolved


def resolve_v1_run(value: str | Path) -> Path:
    return resolve_under_out(
        value,
        V1_OUT_ROOT,
        unsafe_code="ERR_EXEC_OUTSIDE_REPO",
        symlink_code="ERR_EXEC_DIR_SYMLINK",
        label="V1 run",
    )


def resolve_v2_out(value: str | Path) -> Path:
    return resolve_under_out(
        value,
        V2_OUT_ROOT,
        unsafe_code="ERR_EXEC_OUTSIDE_REPO",
        symlink_code="ERR_EXEC_DIR_SYMLINK",
        label="V2 output",
    )


def resolve_v25_out(value: str | Path) -> Path:
    return resolve_under_out(
        value,
        V25_OUT_ROOT,
        unsafe_code="ERR_EXEC_OUTSIDE_REPO",
        symlink_code="ERR_EXEC_DIR_SYMLINK",
        label="V2.5 output",
    )


def ensure_contained(root: Path, path: Path) -> None:
    resolved_root = root.resolve(strict=False)
    target = path if path.is_absolute() else root / path
    reject_traversal(
        path, "ERR_EXEC_OUTSIDE_REPO", "artifact path escapes owned directory"
    )
    try:
        target.resolve(strict=False).relative_to(resolved_root)
    except ValueError as exc:
        raise ExecError(
            "ERR_EXEC_OUTSIDE_REPO",
            "artifact path escapes owned directory",
            path=target,
        ) from exc


def ensure_artifact_parent(root: Path, path: Path) -> None:
    ensure_contained(root, path)
    current = root.resolve(strict=False)
    for part in path.resolve(strict=False).relative_to(current).parent.parts:
        current = current / part
        if current.exists():
            if current.is_symlink():
                raise ExecError(
                    "ERR_EXEC_DIR_SYMLINK", "artifact parent is symlinked", path=current
                )
            if not current.is_dir():
                raise ExecError(
                    "ERR_EXEC_OUTSIDE_REPO",
                    "artifact parent is not a directory",
                    path=current,
                )
        else:
            current.mkdir()


def ensure_leaf_not_symlink(path: Path) -> None:
    if path.exists():
        if path.is_symlink():
            raise ExecError(
                "ERR_EXEC_LEAF_SYMLINK",
                "refusing to overwrite symlinked file",
                path=path,
            )
        if not path.is_file():
            raise ExecError(
                "ERR_EXEC_OUTSIDE_REPO",
                "refusing to overwrite non-file leaf",
                path=path,
            )


def write_text(path: Path, text: str, *, root: Path) -> None:
    ensure_artifact_parent(root, path)
    ensure_leaf_not_symlink(path)
    write_text_atomic(path, text, root=root)


def write_json(path: Path, data: Any, *, root: Path) -> None:
    write_text(path, canonical_json_text(data), root=root)


def read_json_file(path: Path, *, root: Path, label: str) -> dict[str, Any]:
    ensure_contained(root, path)
    if not path.is_file() or path.is_symlink():
        raise ExecError(
            "ERR_EXEC_UNTRUSTED_V1_RUN", f"{label} is missing or symlinked", path=path
        )
    try:
        data = json.loads(path.read_text())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExecError(
            "ERR_EXEC_UNTRUSTED_V1_RUN", f"{label} is malformed: {exc}", path=path
        ) from exc
    if not isinstance(data, dict):
        raise ExecError(
            "ERR_EXEC_UNTRUSTED_V1_RUN", f"{label} root must be an object", path=path
        )
    return data


def read_text_file(path: Path, *, root: Path, label: str) -> str:
    ensure_contained(root, path)
    if not path.is_file() or path.is_symlink():
        raise ExecError(
            "ERR_EXEC_UNTRUSTED_V1_RUN", f"{label} is missing or symlinked", path=path
        )
    try:
        return path.read_text()
    except UnicodeDecodeError as exc:
        raise ExecError(
            "ERR_EXEC_UNTRUSTED_V1_RUN", f"{label} is not UTF-8", path=path
        ) from exc


def sentinel_payload(run_id: str, v1_run_dir: Path) -> dict[str, Any]:
    return {
        "tool": TOOL,
        "schema_version": SCHEMA_VERSION,
        "adapter_version": ADAPTER_VERSION,
        "run_id": run_id,
        "v1_run_path": rel(v1_run_dir),
        "created_at": now_utc(),
    }


def rel(path: Path) -> str:
    resolved = path.resolve(strict=False)
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return str(resolved)


def read_sentinel(path: Path) -> dict[str, Any] | None:
    sentinel = path / SENTINEL
    if not sentinel.is_file() or sentinel.is_symlink():
        return None
    try:
        data = json.loads(sentinel.read_text())
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def ensure_v2_dir(path: Path, run_id: str, v1_run_dir: Path) -> None:
    path = resolve_v2_out(path)
    if path.exists():
        if path.is_symlink():
            raise ExecError(
                "ERR_EXEC_DIR_SYMLINK", "V2 output directory is a symlink", path=path
            )
        if not path.is_dir():
            raise ExecError(
                "ERR_EXEC_OUTSIDE_REPO",
                "V2 output exists and is not a directory",
                path=path,
            )
        sentinel = read_sentinel(path)
        if sentinel is None:
            raise ExecError(
                "ERR_EXEC_UNTRUSTED_V1_RUN",
                "existing V2 output is not adapter-owned",
                path=path,
            )
        if (
            sentinel.get("tool") != TOOL
            or sentinel.get("schema_version") != SCHEMA_VERSION
            or sentinel.get("run_id") != run_id
            or sentinel.get("v1_run_path") != rel(v1_run_dir)
        ):
            raise ExecError(
                "ERR_EXEC_UNTRUSTED_V1_RUN",
                "existing V2 output sentinel does not match this run",
                path=path,
            )
    path.mkdir(parents=True, exist_ok=True)
    if read_sentinel(path) is None:
        write_json(path / SENTINEL, sentinel_payload(run_id, v1_run_dir), root=path)


def prepare_manifest_suite(path: Path, suite_id: str) -> None:
    path = resolve_v2_out(path)
    if path.exists():
        if path.is_symlink():
            raise ExecError(
                "ERR_EXEC_DIR_SYMLINK",
                "manifest suite directory is a symlink",
                path=path,
            )
        if not path.is_dir():
            raise ExecError(
                "ERR_EXEC_OUTSIDE_REPO",
                "manifest suite path is not a directory",
                path=path,
            )
        sentinel = read_sentinel(path)
        if (
            sentinel is None
            or sentinel.get("run_id") != suite_id
            or sentinel.get("mode") != "manifest"
        ):
            raise ExecError(
                "ERR_EXEC_UNTRUSTED_V1_RUN",
                "existing manifest suite is not adapter-owned",
                path=path,
            )
        shutil.rmtree(path)
    path.mkdir(parents=True)
    payload = {
        "tool": TOOL,
        "schema_version": SCHEMA_VERSION,
        "adapter_version": ADAPTER_VERSION,
        "run_id": suite_id,
        "mode": "manifest",
        "created_at": now_utc(),
    }
    write_json(path / SENTINEL, payload, root=path)


def prepare_v25_manifest_suite(path: Path, suite_id: str) -> None:
    path = resolve_v25_out(path)
    if path.exists():
        if path.is_symlink():
            raise ExecError(
                "ERR_EXEC_DIR_SYMLINK",
                "V2.5 manifest suite directory is a symlink",
                path=path,
            )
        if not path.is_dir():
            raise ExecError(
                "ERR_EXEC_OUTSIDE_REPO",
                "V2.5 manifest suite path is not a directory",
                path=path,
            )
        sentinel = read_sentinel(path)
        if (
            sentinel is None
            or sentinel.get("run_id") != suite_id
            or sentinel.get("mode") != "v2.5-manifest"
        ):
            raise ExecError(
                "ERR_EXEC_UNTRUSTED_V1_RUN",
                "existing V2.5 manifest suite is not adapter-owned",
                path=path,
            )
        shutil.rmtree(path)
    path.mkdir(parents=True)
    payload = {
        "tool": TOOL,
        "schema_version": SCHEMA_VERSION,
        "adapter_version": ADAPTER_VERSION,
        "run_id": suite_id,
        "mode": "v2.5-manifest",
        "created_at": now_utc(),
    }
    write_json(path / SENTINEL, payload, root=path)


def next_attempt_id(v2_dir: Path) -> str:
    attempts = v2_dir / "attempts"
    if attempts.exists() and (attempts.is_symlink() or not attempts.is_dir()):
        raise ExecError(
            "ERR_EXEC_ATTEMPT_MALFORMED",
            "attempts directory is malformed",
            path=attempts,
        )
    attempts.mkdir(exist_ok=True)
    existing = []
    for child in attempts.iterdir():
        if child.is_symlink():
            raise ExecError(
                "ERR_EXEC_ATTEMPT_MALFORMED",
                "attempt directory is symlinked",
                path=child,
            )
        if not child.is_dir() or not re.fullmatch(r"\d{4}", child.name):
            raise ExecError(
                "ERR_EXEC_ATTEMPT_MALFORMED",
                "attempts directory contains unexpected entry",
                path=child,
            )
        existing.append(int(child.name))
    if existing and sorted(existing) != list(range(max(existing) + 1)):
        raise ExecError(
            "ERR_EXEC_ATTEMPT_MALFORMED",
            "attempt IDs are not contiguous",
            path=attempts,
        )
    return f"{(max(existing) + 1) if existing else 0:04d}"


def git_text(args: list[str], cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        detail = (
            result.stderr.strip()
            or result.stdout.strip()
            or f"git {' '.join(args)} failed"
        )
        raise ExecError("ERR_EXEC_BACKEND_FAILED", detail, path=cwd)
    return result.stdout


def tracked_repo_state(cwd: Path) -> str:
    parts = {
        "status": git_text(["status", "--porcelain=v1", "--untracked-files=no"], cwd),
        "unstaged_diff": git_text(["diff", "--stat"], cwd),
        "staged_diff": git_text(["diff", "--cached", "--stat"], cwd),
        "head_diff": git_text(["diff", "HEAD", "--stat"], cwd),
    }
    return canonical_json_text(parts)


def git_symbolic_branch(cwd: Path) -> str:
    result = subprocess.run(
        ["git", "symbolic-ref", "--short", "-q", "HEAD"],
        cwd=cwd,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode not in {0, 1}:
        detail = (
            result.stderr.strip() or result.stdout.strip() or "git symbolic-ref failed"
        )
        raise ExecError("ERR_EXEC_BACKEND_FAILED", detail, path=cwd)
    return result.stdout.strip()


def run_process(
    argv: list[str],
    cwd: Path,
    *,
    input_text: str | None = None,
    timeout_seconds: int = 30,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            argv,
            cwd=cwd,
            check=False,
            text=True,
            input=input_text,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        stderr = stderr + f"\nprocess timed out after {timeout_seconds} seconds\n"
        return subprocess.CompletedProcess(argv, 124, stdout=stdout, stderr=stderr)


def validate_worktree_name(name: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name) or name in {".", ".."}:
        raise ExecError(
            "ERR_EXEC_WORKTREE_REQUIRED",
            "worktree name must be one safe path segment",
            path=name,
        )


def worktree_path(name: str) -> Path:
    validate_worktree_name(name)
    path = (WORKTREE_ROOT / name).resolve(strict=False)
    try:
        path.relative_to(WORKTREE_ROOT.resolve(strict=False))
    except ValueError as exc:
        raise ExecError(
            "ERR_EXEC_WORKTREE_REQUIRED",
            "worktree path escapes worktree root",
            path=path,
        ) from exc
    return path


def repo_worktree_paths() -> set[Path]:
    output = git_text(["worktree", "list", "--porcelain"], ROOT)
    paths = set()
    for line in output.splitlines():
        if line.startswith("worktree "):
            paths.add(Path(line.removeprefix("worktree ")).resolve(strict=False))
    return paths


def ensure_git_worktree(name: str | None, *, require_clean: bool = True) -> Path:
    if not name:
        raise ExecError(
            "ERR_EXEC_WORKTREE_REQUIRED", "local-shell execution requires --worktree"
        )
    path = worktree_path(name)
    check_components_not_symlink(path, "ERR_EXEC_DIR_SYMLINK")
    if path.exists():
        if path.is_symlink():
            raise ExecError(
                "ERR_EXEC_DIR_SYMLINK", "worktree directory is a symlink", path=path
            )
        if not path.is_dir():
            raise ExecError(
                "ERR_EXEC_WORKTREE_REQUIRED",
                "worktree path exists and is not a directory",
                path=path,
            )
        probe = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=path,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if probe.returncode != 0:
            raise ExecError(
                "ERR_EXEC_WORKTREE_REQUIRED",
                "existing worktree path is not a git worktree",
                path=path,
            )
        if path.resolve(strict=False) not in repo_worktree_paths():
            raise ExecError(
                "ERR_EXEC_WORKTREE_REQUIRED",
                "existing worktree is not owned by this repository",
                path=path,
            )
        if git_symbolic_branch(path):
            raise ExecError(
                "ERR_EXEC_WORKTREE_REQUIRED",
                "existing worktree must be detached",
                path=path,
            )
        source_head = git_text(["rev-parse", "HEAD"], ROOT).strip()
        worktree_head = git_text(["rev-parse", "HEAD"], path).strip()
        ancestor = subprocess.run(
            ["git", "merge-base", "--is-ancestor", source_head, worktree_head],
            cwd=path,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if ancestor.returncode != 0:
            raise ExecError(
                "ERR_EXEC_WORKTREE_REQUIRED",
                "existing worktree HEAD is not a source HEAD descendant",
                path=path,
            )
    else:
        WORKTREE_ROOT.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            ["git", "worktree", "add", "--detach", str(path), "HEAD"],
            cwd=ROOT,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if result.returncode != 0:
            raise ExecError(
                "ERR_EXEC_BACKEND_FAILED",
                f"git worktree add failed: {result.stderr.strip() or result.stdout.strip()}",
                path=path,
            )
    if require_clean:
        status = git_text(["status", "--short"], path)
        if status.strip():
            raise ExecError("ERR_EXEC_WORKTREE_DIRTY", "worktree is dirty", path=path)
    return path


def cleanup_manifest_worktree_paths(worktree: str | None, paths: Any) -> None:
    if paths is None:
        return
    if not isinstance(paths, list):
        raise ExecError(
            "ERR_EXEC_MANIFEST_REQUIRED_FAILED", "cleanup_worktree_paths must be a list"
        )
    if not worktree:
        raise ExecError(
            "ERR_EXEC_WORKTREE_REQUIRED", "cleanup_worktree_paths requires a worktree"
        )
    root = worktree_path(worktree)
    if not root.exists():
        return
    for value in paths:
        if not isinstance(value, str) or not value:
            raise ExecError(
                "ERR_EXEC_MANIFEST_REQUIRED_FAILED",
                "cleanup path must be a relative file path",
            )
        relative = Path(value)
        if relative.is_absolute() or any(part == ".." for part in relative.parts):
            raise ExecError(
                "ERR_EXEC_OUTSIDE_REPO", "cleanup path escapes worktree", path=relative
            )
        target = root / relative
        try:
            target.resolve(strict=False).relative_to(root.resolve(strict=False))
        except ValueError as exc:
            raise ExecError(
                "ERR_EXEC_OUTSIDE_REPO", "cleanup path escapes worktree", path=target
            ) from exc
        if not target.exists():
            continue
        if target.is_symlink() or not target.is_file():
            raise ExecError(
                "ERR_EXEC_OUTSIDE_REPO",
                "cleanup path is not a regular file",
                path=target,
            )
        target.unlink()


def verification_records(packet: dict[str, Any]) -> list[dict[str, Any]]:
    records = []
    for index, item in enumerate(packet.get("verification", [])):
        if not isinstance(item, dict):
            continue
        records.append(
            {
                "check_id": f"verification-{index:04d}",
                "claim_or_output": item.get("claim_or_output"),
                "falsifier": item.get("falsifier"),
                "mode": "manual",
                "stdout_path": None,
                "stderr_path": None,
                "exit_code": None,
                "checked_hash": None,
                "result": "manual-required",
            }
        )
    return records


def trust_v1_run(v1_run_dir: Path) -> dict[str, Any]:
    try:
        v1_run_dir = resolve_v1_run(v1_run_dir)
        resume_status = resume_run(v1_run_dir)
    except (CompileError, ExecError) as exc:
        if isinstance(exc, ExecError):
            raise
        raise ExecError(
            "ERR_EXEC_UNTRUSTED_V1_RUN", exc.message, path=exc.path
        ) from exc

    if resume_status.get("resume_state") != "resumable":
        raise ExecError(
            "ERR_EXEC_STALE_PACKET", "V1 resume check is not clean", path=v1_run_dir
        )

    run = read_json_file(v1_run_dir / "run.json", root=v1_run_dir, label="run.json")
    status = read_json_file(
        v1_run_dir / "status.json", root=v1_run_dir, label="status.json"
    )
    packet = read_json_file(v1_run_dir / PACKET_REL, root=v1_run_dir, label=PACKET_REL)
    prompt = read_text_file(v1_run_dir / PROMPT_REL, root=v1_run_dir, label=PROMPT_REL)
    approval = read_json_file(
        v1_run_dir / APPROVAL_REL, root=v1_run_dir, label=APPROVAL_REL
    )

    packet_statuses = status.get("packet_statuses")
    packet_status = (
        packet_statuses[0].get("status")
        if isinstance(packet_statuses, list)
        and packet_statuses
        and isinstance(packet_statuses[0], dict)
        else None
    )
    if packet_status != "ready":
        code = (
            "ERR_EXEC_BLOCKED_RISK"
            if packet_status == "blocked-risk-gate"
            else "ERR_EXEC_STALE_PACKET"
        )
        raise ExecError(
            code, f"V1 packet status is not ready: {packet_status}", path=v1_run_dir
        )

    gates = approval.get("gates")
    if not isinstance(gates, list):
        raise ExecError(
            "ERR_EXEC_UNTRUSTED_V1_RUN",
            "approval-state gates are malformed",
            path=v1_run_dir / APPROVAL_REL,
        )
    blocked_gates = [
        gate
        for gate in gates
        if isinstance(gate, dict) and gate.get("status") == "blocked"
    ]
    if blocked_gates:
        raise ExecError(
            "ERR_EXEC_BLOCKED_RISK",
            "V1 approval state contains blocked gates",
            path=v1_run_dir / APPROVAL_REL,
        )

    snapshots = status.get("snapshots")
    if not isinstance(snapshots, dict):
        raise ExecError(
            "ERR_EXEC_UNTRUSTED_V1_RUN",
            "status snapshots are malformed",
            path=v1_run_dir / "status.json",
        )
    packet_hash = canonical_hash(packet)
    prompt_hash = sha256_text(prompt)
    if snapshots.get("packet_hashes", {}).get(PACKET_ID) != packet_hash:
        raise ExecError(
            "ERR_EXEC_STALE_PACKET",
            "packet hash does not match V1 status snapshot",
            path=v1_run_dir / PACKET_REL,
        )
    if snapshots.get("prompt_hashes", {}).get(PROMPT_REL) != prompt_hash:
        raise ExecError(
            "ERR_EXEC_STALE_PACKET",
            "prompt hash does not match V1 status snapshot",
            path=v1_run_dir / PROMPT_REL,
        )
    if packet.get("prompt_hash") != prompt_hash:
        raise ExecError(
            "ERR_EXEC_STALE_PACKET",
            "packet prompt hash does not match prompt file",
            path=v1_run_dir / PACKET_REL,
        )
    if packet.get("prompt_path") != PROMPT_REL:
        raise ExecError(
            "ERR_EXEC_STALE_PACKET",
            "packet prompt path does not match V1 contract",
            path=v1_run_dir / PACKET_REL,
        )

    return {
        "v1_run_dir": v1_run_dir,
        "run": run,
        "status": status,
        "packet": packet,
        "prompt": prompt,
        "approval": approval,
        "packet_hash": packet_hash,
        "prompt_hash": prompt_hash,
    }


def backend_command_preview(
    backend: str,
    v1_run_dir: Path,
    prompt_path: Path,
    worktree: str | None,
    emit_only: bool,
) -> dict[str, Any]:
    if backend == "dry-run":
        return {
            "backend": "dry-run",
            "argv": [],
            "emit_only": True,
            "description": "No backend launched; evidence prepared only.",
        }
    if backend == "omx":
        if not emit_only:
            raise ExecError(
                "ERR_EXEC_BACKEND_UNAVAILABLE",
                "--backend omx requires --emit-only in V2",
            )
        argv = ["omx"]
        if worktree:
            argv.append(f"--worktree={worktree}")
        argv.extend(["--high"])
        return {
            "backend": "omx",
            "argv": argv,
            "emit_only": emit_only,
            "prompt_handoff_path": rel(prompt_path),
            "description": "Emit-only OMX launch brief; V2 does not execute OMX yet.",
        }
    if backend == "codex-cli":
        worktree_target = worktree or "<required-worktree>"
        return {
            "backend": "codex-cli",
            "argv": [
                "codex",
                "exec",
                "--skip-git-repo-check",
                "--cd",
                worktree_target,
                "--sandbox",
                "workspace-write",
                "--output-last-message",
                "transcript.md",
                "-",
            ],
            "emit_only": emit_only,
            "prompt_handoff_path": rel(prompt_path),
            "description": "Codex CLI launch preview; exact transcript path is attempt-specific.",
        }
    raise ExecError("ERR_EXEC_BACKEND_UNAVAILABLE", f"unsupported backend: {backend}")


def render_execution_brief(
    context: dict[str, Any], command: dict[str, Any], verification: list[dict[str, Any]]
) -> str:
    packet = context["packet"]
    blocked = [
        gate
        for gate in context["approval"].get("gates", [])
        if isinstance(gate, dict) and gate.get("status") == "blocked"
    ]
    lines = [
        "# V2 Execution Brief",
        "",
        f"Run ID: `{context['run']['run_id']}`",
        f"Packet: `{packet.get('packet_id')}`",
        f"Backend: `{command['backend']}`",
        "",
        "## Trust",
        "",
        f"- V1 resume state: `{context['status'].get('resume_state')}`",
        f"- Packet hash: `{context['packet_hash']}`",
        f"- Prompt hash: `{context['prompt_hash']}`",
        f"- Blocked gates: `{len(blocked)}`",
        "",
        "## Command",
        "",
        "```json",
        canonical_json_text(command),
        "```",
        "",
        "## Verification",
    ]
    if verification:
        for item in verification:
            lines.append(
                f"- `{item['check_id']}` {item.get('claim_or_output')}: {item.get('result')}"
            )
    else:
        lines.append("- none recorded")
    return "\n".join(lines) + "\n"


def attempt_record(
    context: dict[str, Any],
    *,
    attempt_id: str,
    backend: str,
    command: dict[str, Any],
    verification: list[dict[str, Any]],
    started_at: str,
    ended_at: str,
    status: str = "prepared",
    exit_code: int | None = None,
    stdout_path: str | None = None,
    stderr_path: str | None = None,
    worktree_path: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "adapter_version": ADAPTER_VERSION,
        "attempt_id": attempt_id,
        "run_id": context["run"]["run_id"],
        "v1_run_path": rel(context["v1_run_dir"]),
        "packet_id": PACKET_ID,
        "backend": backend,
        "status": status,
        "started_at": started_at,
        "ended_at": ended_at,
        "prompt_path": "prompt.md",
        "execution_brief_path": "execution-brief.md",
        "backend_command_path": "backend-command.json",
        "stdout_path": stdout_path,
        "stderr_path": stderr_path,
        "transcript_path": None,
        "git_status_path": "git-status.txt",
        "git_diff_summary_path": "git-diff-summary.txt",
        "pre_tracked_state_path": None,
        "post_tracked_state_path": None,
        "verification_path": "verification.json",
        "hashes_path": "hashes.json",
        "exit_code": exit_code,
        "verification_result": "manual-required",
        "worktree_path": worktree_path,
        "command": command,
        "verification": verification,
    }


def build_status(
    run_id: str,
    v1_run_dir: Path,
    *,
    status: str,
    attempts: list[dict[str, Any]],
    invalidators: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "adapter_version": ADAPTER_VERSION,
        "run_id": run_id,
        "v1_run_path": rel(v1_run_dir),
        "status": status,
        "attempt_count": len(attempts),
        "latest_attempt_id": attempts[-1]["attempt_id"] if attempts else None,
        "attempts": attempts,
        "invalidators": invalidators or [],
        "checked_at": now_utc(),
    }


def render_resume(status: dict[str, Any]) -> str:
    lines = [
        "# V2 Resume Check",
        "",
        f"Run ID: `{status['run_id']}`",
        f"State: `{status['status']}`",
        f"Attempt count: `{status['attempt_count']}`",
        "",
        "V2 checks execution evidence for one V1 first-slice packet. It does not advance the workflow.",
        "",
        "## Invalidators",
    ]
    invalidators = status.get("invalidators", [])
    if invalidators:
        for item in invalidators:
            lines.append(f"- `{item.get('code')}` {item.get('message')}")
    else:
        lines.append("- none")
    return "\n".join(lines) + "\n"


def write_status(v2_dir: Path, status: dict[str, Any]) -> None:
    write_json(v2_dir / "status.json", status, root=v2_dir)
    write_text(v2_dir / "resume.md", render_resume(status), root=v2_dir)


def required_hash_value_with_code(
    hashes_data: dict[str, Any], key: str, path: Path, code: str
) -> Any:
    if key not in hashes_data:
        raise ExecError(code, f"{key} is missing from hashes.json", path=path)
    return hashes_data[key]


def validate_hash_value_with_code(
    actual: str, expected: Any, label: str, path: Path, code: str
) -> None:
    if expected != actual:
        raise ExecError(code, f"{label} hash mismatch", path=path)


def next_record_id(v2_dir: Path, directory_name: str, code: str) -> str:
    records_dir = v2_dir / directory_name
    if records_dir.exists() and (records_dir.is_symlink() or not records_dir.is_dir()):
        raise ExecError(
            code, f"{directory_name} directory is malformed", path=records_dir
        )
    records_dir.mkdir(exist_ok=True)
    existing = []
    for child in records_dir.iterdir():
        if child.is_symlink():
            raise ExecError(
                code, f"{directory_name} record directory is symlinked", path=child
            )
        if not child.is_dir() or not re.fullmatch(r"\d{4}", child.name):
            raise ExecError(
                code,
                f"{directory_name} directory contains unexpected entry",
                path=child,
            )
        existing.append(int(child.name))
    if existing and sorted(existing) != list(range(max(existing) + 1)):
        raise ExecError(
            code, f"{directory_name} IDs are not contiguous", path=records_dir
        )
    return f"{(max(existing) + 1) if existing else 0:04d}"


def read_record_json(
    record_dir: Path, relative_path: str, label: str, code: str
) -> Any:
    path = record_dir / relative_path
    if not path.is_file() or path.is_symlink():
        raise ExecError(code, f"{label} is missing or symlinked", path=path)
    try:
        return json.loads(path.read_text())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExecError(code, f"{label} is malformed: {exc}", path=path) from exc


def read_record_text(
    record_dir: Path, relative_path: str | None, label: str, code: str
) -> str:
    if not isinstance(relative_path, str):
        raise ExecError(code, f"{label} path is missing", path=record_dir)
    path = record_dir / relative_path
    if not path.is_file() or path.is_symlink():
        raise ExecError(code, f"{label} is missing or symlinked", path=path)
    try:
        return path.read_text()
    except UnicodeDecodeError as exc:
        raise ExecError(code, f"{label} is not UTF-8: {exc}", path=path) from exc


def validate_record_relative_file(
    record_dir: Path, value: Any, field: str, code: str
) -> None:
    if not isinstance(value, str) or not value:
        raise ExecError(code, f"{field} must be a relative file path", path=record_dir)
    rel_path = Path(value)
    if rel_path.is_absolute() or any(part == ".." for part in rel_path.parts):
        raise ExecError(code, f"{field} escapes record directory", path=rel_path)
    target = record_dir / rel_path
    try:
        target.resolve(strict=False).relative_to(record_dir.resolve(strict=False))
    except ValueError as exc:
        raise ExecError(code, f"{field} escapes record directory", path=target) from exc
    if not target.is_file() or target.is_symlink():
        raise ExecError(code, f"{field} is missing or symlinked", path=target)


def review_contract(
    review: dict[str, Any], hashes_data: dict[str, Any]
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "review_id": review.get("review_id"),
        "run_id": review.get("run_id"),
        "source_attempt_id": review.get("source_attempt_id"),
        "verdict": review.get("verdict"),
        "findings_hash": canonical_hash(review.get("findings")),
        "source_hashes_hash": canonical_hash(review.get("source_hashes")),
        "hashes_hash": canonical_hash(hashes_data),
    }


def repair_contract(
    repair: dict[str, Any], hashes_data: dict[str, Any]
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "repair_id": repair.get("repair_id"),
        "run_id": repair.get("run_id"),
        "source_review_id": repair.get("source_review_id"),
        "source_attempt_id": repair.get("source_attempt_id"),
        "status": repair.get("status"),
        "findings_hash": canonical_hash(repair.get("findings")),
        "verification_hash": canonical_hash(repair.get("verification")),
        "hashes_hash": canonical_hash(hashes_data),
    }


def read_contracts(
    v2_dir: Path, filename: str, key: str, code: str, *, required: bool
) -> dict[str, dict[str, Any]]:
    path = v2_dir / filename
    if not path.exists():
        if required:
            raise ExecError(code, f"{filename} is missing", path=path)
        return {}
    if not path.is_file() or path.is_symlink():
        raise ExecError(code, f"{filename} is missing or symlinked", path=path)
    try:
        data = json.loads(path.read_text())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExecError(code, f"{filename} is malformed: {exc}", path=path) from exc
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        raise ExecError(code, f"{filename} schema is malformed", path=path)
    entries = data.get(key)
    if not isinstance(entries, list):
        raise ExecError(code, f"{filename} {key} must be a list", path=path)
    contracts: dict[str, dict[str, Any]] = {}
    id_key = "review_id" if key == "reviews" else "repair_id"
    for entry in entries:
        if not isinstance(entry, dict):
            raise ExecError(code, f"{filename} entry is malformed", path=path)
        item_id = entry.get(id_key)
        if (
            not isinstance(item_id, str)
            or not re.fullmatch(r"\d{4}", item_id)
            or item_id in contracts
        ):
            raise ExecError(code, f"{filename} IDs are malformed", path=path)
        contracts[item_id] = entry
    return contracts


def append_contract(
    v2_dir: Path,
    filename: str,
    key: str,
    item_id_key: str,
    contract: dict[str, Any],
    code: str,
) -> None:
    path = v2_dir / filename
    contracts = read_contracts(v2_dir, filename, key, code, required=False)
    item_id = contract.get(item_id_key)
    if not isinstance(item_id, str) or item_id in contracts:
        raise ExecError(code, f"{filename} cannot append this record", path=path)
    ordered = [contracts[item] for item in sorted(contracts)]
    ordered.append(contract)
    write_json(path, {"schema_version": SCHEMA_VERSION, key: ordered}, root=v2_dir)


def append_review_contract(
    v2_dir: Path, review: dict[str, Any], hashes_data: dict[str, Any]
) -> None:
    append_contract(
        v2_dir,
        REVIEW_CONTRACTS,
        "reviews",
        "review_id",
        review_contract(review, hashes_data),
        "ERR_REVIEW_ARTIFACT_MALFORMED",
    )


def append_repair_contract(
    v2_dir: Path, repair: dict[str, Any], hashes_data: dict[str, Any]
) -> None:
    append_contract(
        v2_dir,
        REPAIR_CONTRACTS,
        "repairs",
        "repair_id",
        repair_contract(repair, hashes_data),
        "ERR_REPAIR_ARTIFACT_MALFORMED",
    )


def attempt_contract(
    attempt: dict[str, Any], hashes_data: dict[str, Any]
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "attempt_id": attempt.get("attempt_id"),
        "run_id": attempt.get("run_id"),
        "v1_run_path": attempt.get("v1_run_path"),
        "packet_id": attempt.get("packet_id"),
        "backend": attempt.get("backend"),
        "status": attempt.get("status"),
        "exit_code": attempt.get("exit_code"),
        "verification_result": attempt.get("verification_result"),
        "command_hash": canonical_hash(attempt.get("command")),
        "verification_hash": canonical_hash(attempt.get("verification")),
        "hashes_hash": canonical_hash(hashes_data),
    }


def read_attempt_contracts(
    v2_dir: Path, *, required: bool
) -> dict[str, dict[str, Any]]:
    path = v2_dir / ATTEMPT_CONTRACTS
    if not path.exists():
        if required:
            raise ExecError(
                "ERR_EXEC_ATTEMPT_MALFORMED",
                "attempt contract ledger is missing",
                path=path,
            )
        return {}
    if not path.is_file() or path.is_symlink():
        raise ExecError(
            "ERR_EXEC_ATTEMPT_MALFORMED",
            "attempt contract ledger is missing or symlinked",
            path=path,
        )
    try:
        data = json.loads(path.read_text())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExecError(
            "ERR_EXEC_ATTEMPT_MALFORMED",
            f"attempt contract ledger is malformed: {exc}",
            path=path,
        ) from exc
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        raise ExecError(
            "ERR_EXEC_ATTEMPT_MALFORMED",
            "attempt contract ledger schema is malformed",
            path=path,
        )
    entries = data.get("attempts")
    if not isinstance(entries, list):
        raise ExecError(
            "ERR_EXEC_ATTEMPT_MALFORMED",
            "attempt contract ledger attempts must be a list",
            path=path,
        )
    contracts: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ExecError(
                "ERR_EXEC_ATTEMPT_MALFORMED",
                "attempt contract ledger entry is malformed",
                path=path,
            )
        attempt_id = entry.get("attempt_id")
        if (
            not isinstance(attempt_id, str)
            or not re.fullmatch(r"\d{4}", attempt_id)
            or attempt_id in contracts
        ):
            raise ExecError(
                "ERR_EXEC_ATTEMPT_MALFORMED",
                "attempt contract ledger IDs are malformed",
                path=path,
            )
        contracts[attempt_id] = entry
    return contracts


def append_attempt_contract(
    v2_dir: Path, attempt: dict[str, Any], hashes_data: dict[str, Any]
) -> None:
    path = v2_dir / ATTEMPT_CONTRACTS
    contracts = read_attempt_contracts(v2_dir, required=False)
    attempt_id = attempt.get("attempt_id")
    if not isinstance(attempt_id, str) or attempt_id in contracts:
        raise ExecError(
            "ERR_EXEC_ATTEMPT_MALFORMED",
            "attempt contract ledger cannot append this attempt",
            path=path,
        )
    ordered = [contracts[key] for key in sorted(contracts)]
    ordered.append(attempt_contract(attempt, hashes_data))
    write_json(
        path, {"schema_version": SCHEMA_VERSION, "attempts": ordered}, root=v2_dir
    )


def validate_attempt_contract(
    attempt_dir: Path, attempt: dict[str, Any], contract: dict[str, Any] | None
) -> None:
    if contract is None:
        raise ExecError(
            "ERR_EXEC_ATTEMPT_MALFORMED",
            "attempt contract ledger entry is missing",
            path=attempt_dir / "attempt.json",
        )
    hashes_data = read_attempt_json(
        attempt_dir, str(attempt.get("hashes_path")), "hashes.json"
    )
    if not isinstance(hashes_data, dict):
        raise ExecError(
            "ERR_EXEC_ATTEMPT_MALFORMED",
            "hashes.json root must be an object",
            path=attempt_dir / str(attempt.get("hashes_path")),
        )
    expected = attempt_contract(attempt, hashes_data)
    if contract != expected:
        raise ExecError(
            "ERR_EXEC_ATTEMPT_MALFORMED",
            "attempt does not match root contract ledger",
            path=attempt_dir / "attempt.json",
        )


def read_attempt_json(attempt_dir: Path, relative_path: str, label: str) -> Any:
    path = attempt_dir / relative_path
    if not path.is_file() or path.is_symlink():
        raise ExecError(
            "ERR_EXEC_ATTEMPT_MALFORMED", f"{label} is missing or symlinked", path=path
        )
    try:
        return json.loads(path.read_text())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExecError(
            "ERR_EXEC_ATTEMPT_MALFORMED", f"{label} is malformed: {exc}", path=path
        ) from exc


def read_attempt_text(attempt_dir: Path, relative_path: str | None) -> str:
    if not relative_path:
        return ""
    path = attempt_dir / relative_path
    if not path.is_file() or path.is_symlink():
        raise ExecError(
            "ERR_EXEC_ATTEMPT_MALFORMED",
            "attempt text sidecar is missing or symlinked",
            path=path,
        )
    try:
        return path.read_text()
    except UnicodeDecodeError as exc:
        raise ExecError(
            "ERR_EXEC_ATTEMPT_MALFORMED",
            f"attempt text sidecar is not UTF-8: {exc}",
            path=path,
        ) from exc


def evidence_status_for_attempt(
    attempt_dir: Path, attempt: dict[str, Any]
) -> tuple[str, str]:
    backend = attempt.get("backend")
    if backend == "dry-run":
        return "prepared", "manual-required"

    verification_data = read_attempt_json(
        attempt_dir, str(attempt.get("verification_path")), "verification.json"
    )
    if not isinstance(verification_data, list):
        raise ExecError(
            "ERR_EXEC_ATTEMPT_MALFORMED",
            "verification.json root must be a list",
            path=attempt_dir / str(attempt.get("verification_path")),
        )
    command_data = read_attempt_json(
        attempt_dir, str(attempt.get("backend_command_path")), "backend-command.json"
    )
    if not isinstance(command_data, dict):
        raise ExecError(
            "ERR_EXEC_ATTEMPT_MALFORMED",
            "backend-command.json root must be an object",
            path=attempt_dir / str(attempt.get("backend_command_path")),
        )
    if command_data.get("emit_only") is True:
        return "prepared", "manual-required"

    exit_code = attempt.get("exit_code")
    expected_exit = command_data.get("expected_exit_code")
    if not isinstance(exit_code, int) or not isinstance(expected_exit, int):
        raise ExecError(
            "ERR_EXEC_ATTEMPT_MALFORMED",
            "attempt exit evidence is malformed",
            path=attempt_dir / "attempt.json",
        )

    if backend == "codex-cli" and exit_code != expected_exit:
        process = subprocess.CompletedProcess(
            command_data.get("argv", []),
            exit_code,
            stdout=read_attempt_text(attempt_dir, attempt.get("stdout_path")),
            stderr=read_attempt_text(attempt_dir, attempt.get("stderr_path")),
        )
        if codex_auth_failed(process):
            return "blocked", "manual-required"

    if exit_code != expected_exit:
        return "failed", "manual-required"

    automatic = [
        item
        for item in verification_data
        if isinstance(item, dict) and item.get("mode") == "automatic"
    ]
    if automatic:
        if any(item.get("result") != "pass" for item in automatic):
            return "failed", "fail"
        return "verified", "pass"
    return "executed", "manual-required"


def invalidators_for_attempt(
    attempt_dir: Path, attempt: dict[str, Any]
) -> list[dict[str, Any]]:
    status = attempt.get("status")
    if status not in {"blocked", "failed"}:
        return []
    command_data = read_attempt_json(
        attempt_dir, str(attempt.get("backend_command_path")), "backend-command.json"
    )
    exit_code = attempt.get("exit_code")
    expected_exit = command_data.get("expected_exit_code")
    if status == "blocked" and attempt.get("backend") == "codex-cli":
        return [
            {
                "code": "ERR_EXEC_BACKEND_AUTH",
                "message": "Codex CLI authentication failed",
            }
        ]
    if status == "failed" and attempt.get("verification_result") == "fail":
        return [
            {
                "code": "ERR_EXEC_VERIFY_FAILED",
                "message": "one or more verification commands failed",
            }
        ]
    return [
        {
            "code": "ERR_EXEC_BACKEND_FAILED",
            "message": f"{attempt.get('backend')} exited {exit_code}, expected {expected_exit}",
        }
    ]


def required_hash_value(hashes_data: dict[str, Any], key: str, path: Path) -> Any:
    if key not in hashes_data:
        raise ExecError(
            "ERR_EXEC_ATTEMPT_MALFORMED",
            f"{key} is missing from hashes.json",
            path=path,
        )
    return hashes_data[key]


def validate_hash_value(actual: str, expected: Any, label: str, path: Path) -> None:
    if expected != actual:
        raise ExecError(
            "ERR_EXEC_ATTEMPT_MALFORMED", f"{label} hash mismatch", path=path
        )


def validate_attempt_hashes(
    attempt_dir: Path,
    attempt: dict[str, Any],
    *,
    expected_packet_hash: str | None = None,
    expected_prompt_hash: str | None = None,
    expected_run_id: str | None = None,
    expected_v1_run_path: str | None = None,
    expected_packet_id: str | None = None,
) -> None:
    hashes_data = read_attempt_json(
        attempt_dir, str(attempt.get("hashes_path")), "hashes.json"
    )
    if not isinstance(hashes_data, dict):
        raise ExecError(
            "ERR_EXEC_ATTEMPT_MALFORMED",
            "hashes.json root must be an object",
            path=attempt_dir / str(attempt.get("hashes_path")),
        )
    verification = read_attempt_json(
        attempt_dir, str(attempt.get("verification_path")), "verification.json"
    )
    command = read_attempt_json(
        attempt_dir, str(attempt.get("backend_command_path")), "backend-command.json"
    )
    command_backend = command.get("backend")
    if command_backend not in {"dry-run", "local-shell", "codex-cli", "omx"}:
        raise ExecError(
            "ERR_EXEC_ATTEMPT_MALFORMED",
            "backend-command backend is unsupported",
            path=attempt_dir / str(attempt.get("backend_command_path")),
        )
    if attempt.get("backend") != command_backend:
        raise ExecError(
            "ERR_EXEC_ATTEMPT_MALFORMED",
            "attempt backend does not match backend-command.json",
            path=attempt_dir / "attempt.json",
        )
    if expected_run_id is not None and attempt.get("run_id") != expected_run_id:
        raise ExecError(
            "ERR_EXEC_ATTEMPT_MALFORMED",
            "attempt run_id does not match trusted V1 run",
            path=attempt_dir / "attempt.json",
        )
    if (
        expected_v1_run_path is not None
        and attempt.get("v1_run_path") != expected_v1_run_path
    ):
        raise ExecError(
            "ERR_EXEC_ATTEMPT_MALFORMED",
            "attempt v1_run_path does not match trusted V1 run",
            path=attempt_dir / "attempt.json",
        )
    if (
        expected_packet_id is not None
        and attempt.get("packet_id") != expected_packet_id
    ):
        raise ExecError(
            "ERR_EXEC_ATTEMPT_MALFORMED",
            "attempt packet_id does not match trusted packet",
            path=attempt_dir / "attempt.json",
        )
    if attempt.get("command") != command:
        raise ExecError(
            "ERR_EXEC_ATTEMPT_MALFORMED",
            "attempt command does not match backend-command.json",
            path=attempt_dir / "attempt.json",
        )
    if attempt.get("verification") != verification:
        raise ExecError(
            "ERR_EXEC_ATTEMPT_MALFORMED",
            "attempt verification does not match verification.json",
            path=attempt_dir / "attempt.json",
        )
    tracked_evidence_required = (
        command_backend == "dry-run" or command.get("emit_only") is True
    )
    if tracked_evidence_required:
        for field in [
            "pre_git_status_path",
            "pre_git_diff_summary_path",
            "pre_tracked_state_path",
            "post_tracked_state_path",
        ]:
            if not isinstance(attempt.get(field), str):
                raise ExecError(
                    "ERR_EXEC_ATTEMPT_MALFORMED",
                    f"{field} is required for dry-run or emit-only evidence",
                    path=attempt_dir / "attempt.json",
                )
        if not isinstance(attempt.get("repo_tracked_diff_unchanged"), bool):
            raise ExecError(
                "ERR_EXEC_ATTEMPT_MALFORMED",
                "repo_tracked_diff_unchanged is required for dry-run or emit-only evidence",
                path=attempt_dir / "attempt.json",
            )
    elif command_backend in {"local-shell", "codex-cli"}:
        for field in ["stdout_path", "stderr_path"]:
            if not isinstance(attempt.get(field), str):
                raise ExecError(
                    "ERR_EXEC_ATTEMPT_MALFORMED",
                    f"{field} is required for executed backend evidence",
                    path=attempt_dir / "attempt.json",
                )
    if expected_packet_hash is not None:
        validate_hash_value(
            expected_packet_hash,
            required_hash_value(
                hashes_data, "packet_hash", attempt_dir / "hashes.json"
            ),
            "packet",
            attempt_dir / "hashes.json",
        )
    if expected_prompt_hash is not None:
        validate_hash_value(
            expected_prompt_hash,
            required_hash_value(
                hashes_data, "prompt_hash", attempt_dir / "hashes.json"
            ),
            "prompt",
            attempt_dir / "hashes.json",
        )
    validate_hash_value(
        canonical_hash(attempt),
        required_hash_value(hashes_data, "attempt_hash", attempt_dir / "hashes.json"),
        "attempt",
        attempt_dir / "attempt.json",
    )
    validate_hash_value(
        sha256_text(read_attempt_text(attempt_dir, attempt.get("prompt_path"))),
        required_hash_value(
            hashes_data, "prompt_copy_hash", attempt_dir / "hashes.json"
        ),
        "prompt copy",
        attempt_dir / str(attempt.get("prompt_path")),
    )
    validate_hash_value(
        sha256_text(
            read_attempt_text(attempt_dir, attempt.get("execution_brief_path"))
        ),
        required_hash_value(
            hashes_data, "execution_brief_hash", attempt_dir / "hashes.json"
        ),
        "execution brief",
        attempt_dir / str(attempt.get("execution_brief_path")),
    )
    validate_hash_value(
        canonical_hash(verification),
        required_hash_value(
            hashes_data, "verification_hash", attempt_dir / "hashes.json"
        ),
        "verification",
        attempt_dir / str(attempt.get("verification_path")),
    )
    validate_hash_value(
        canonical_hash(command),
        required_hash_value(
            hashes_data, "backend_command_hash", attempt_dir / "hashes.json"
        ),
        "backend command",
        attempt_dir / str(attempt.get("backend_command_path")),
    )
    for field, hash_key in [
        ("stdout_path", "stdout_hash"),
        ("stderr_path", "stderr_hash"),
        ("transcript_path", "transcript_hash"),
        ("git_status_path", "worktree_status_hash"),
        ("pre_git_status_path", "pre_git_status_hash"),
        ("pre_git_diff_summary_path", "pre_git_diff_summary_hash"),
        ("git_status_path", "post_git_status_hash"),
        ("git_diff_summary_path", "post_git_diff_summary_hash"),
        ("pre_tracked_state_path", "pre_tracked_state_hash"),
        ("post_tracked_state_path", "post_tracked_state_hash"),
    ]:
        relative_path = attempt.get(field)
        if isinstance(relative_path, str):
            validate_hash_value(
                sha256_text(read_attempt_text(attempt_dir, relative_path)),
                required_hash_value(hashes_data, hash_key, attempt_dir / "hashes.json"),
                hash_key,
                attempt_dir / str(relative_path),
            )
        elif hash_key in hashes_data:
            raise ExecError(
                "ERR_EXEC_ATTEMPT_MALFORMED",
                f"{hash_key} has no sidecar path",
                path=attempt_dir / "attempt.json",
            )
    pre_tracked_path = attempt.get("pre_tracked_state_path")
    post_tracked_path = attempt.get("post_tracked_state_path")
    if isinstance(pre_tracked_path, str) or isinstance(post_tracked_path, str):
        if not isinstance(pre_tracked_path, str) or not isinstance(
            post_tracked_path, str
        ):
            raise ExecError(
                "ERR_EXEC_ATTEMPT_MALFORMED",
                "tracked state sidecars must be paired",
                path=attempt_dir / "attempt.json",
            )
        unchanged = read_attempt_text(
            attempt_dir, pre_tracked_path
        ) == read_attempt_text(attempt_dir, post_tracked_path)
        if attempt.get("repo_tracked_diff_unchanged") != unchanged:
            raise ExecError(
                "ERR_EXEC_ATTEMPT_MALFORMED",
                "repo_tracked_diff_unchanged does not match tracked-state sidecars",
                path=attempt_dir / "attempt.json",
            )
    if isinstance(verification, list):
        for item in verification:
            if not isinstance(item, dict):
                continue
            check_id = item.get("check_id")
            if not isinstance(check_id, str):
                continue
            stdout_key = f"{check_id}.stdout_hash"
            stderr_key = f"{check_id}.stderr_hash"
            checked_key = f"{check_id}.checked_hash"
            if item.get("mode") == "automatic":
                if not isinstance(item.get("stdout_path"), str) or not isinstance(
                    item.get("stderr_path"), str
                ):
                    raise ExecError(
                        "ERR_EXEC_ATTEMPT_MALFORMED",
                        "automatic verification is missing stdout/stderr paths",
                        path=attempt_dir / str(attempt.get("verification_path")),
                    )
                validate_hash_value(
                    sha256_text(
                        read_attempt_text(attempt_dir, item.get("stdout_path"))
                    ),
                    required_hash_value(
                        hashes_data, stdout_key, attempt_dir / "hashes.json"
                    ),
                    stdout_key,
                    attempt_dir / str(item.get("stdout_path")),
                )
                validate_hash_value(
                    sha256_text(
                        read_attempt_text(attempt_dir, item.get("stderr_path"))
                    ),
                    required_hash_value(
                        hashes_data, stderr_key, attempt_dir / "hashes.json"
                    ),
                    stderr_key,
                    attempt_dir / str(item.get("stderr_path")),
                )
                checked_state_path = item.get("checked_state_path")
                if not isinstance(checked_state_path, str):
                    raise ExecError(
                        "ERR_EXEC_ATTEMPT_MALFORMED",
                        "automatic verification is missing checked_state_path",
                        path=attempt_dir / str(attempt.get("verification_path")),
                    )
                checked_state = read_attempt_json(
                    attempt_dir, checked_state_path, "verification checked state"
                )
                checked_hash = canonical_hash(checked_state)
                validate_hash_value(
                    checked_hash,
                    required_hash_value(
                        hashes_data, checked_key, attempt_dir / "hashes.json"
                    ),
                    checked_key,
                    attempt_dir / checked_state_path,
                )
                if item.get("checked_hash") != checked_hash:
                    raise ExecError(
                        "ERR_EXEC_ATTEMPT_MALFORMED",
                        f"{checked_key} hash mismatch",
                        path=attempt_dir / str(attempt.get("verification_path")),
                    )
            if (
                checked_key in hashes_data
                and item.get("checked_hash") != hashes_data[checked_key]
            ):
                raise ExecError(
                    "ERR_EXEC_ATTEMPT_MALFORMED",
                    f"{checked_key} hash mismatch",
                    path=attempt_dir / str(attempt.get("verification_path")),
                )


def existing_attempts(
    v2_dir: Path,
    *,
    expected_packet_hash: str | None = None,
    expected_prompt_hash: str | None = None,
    expected_run_id: str | None = None,
    expected_v1_run_path: str | None = None,
    expected_packet_id: str | None = None,
) -> list[dict[str, Any]]:
    attempts_dir = v2_dir / "attempts"
    if not attempts_dir.exists():
        return []
    if attempts_dir.is_symlink() or not attempts_dir.is_dir():
        raise ExecError(
            "ERR_EXEC_ATTEMPT_MALFORMED",
            "attempts directory is malformed",
            path=attempts_dir,
        )
    children = sorted(attempts_dir.iterdir(), key=lambda item: item.name)
    if not children:
        return []
    contracts = read_attempt_contracts(v2_dir, required=True)
    attempts_root = attempts_dir.resolve(strict=False)
    attempts: list[dict[str, Any]] = []
    for child in children:
        if child.is_symlink():
            raise ExecError(
                "ERR_EXEC_ATTEMPT_MALFORMED",
                "attempt directory is symlinked",
                path=child,
            )
        if not child.is_dir() or not re.fullmatch(r"\d{4}", child.name):
            raise ExecError(
                "ERR_EXEC_ATTEMPT_MALFORMED",
                "attempts directory contains unexpected entry",
                path=child,
            )
        try:
            child.resolve(strict=False).relative_to(attempts_root)
        except ValueError as exc:
            raise ExecError(
                "ERR_EXEC_ATTEMPT_MALFORMED",
                "attempt directory escapes attempts root",
                path=child,
            ) from exc
        path = child / "attempt.json"
        if not path.is_file() or path.is_symlink():
            raise ExecError(
                "ERR_EXEC_ATTEMPT_MALFORMED",
                "attempt is missing attempt.json",
                path=path,
            )
        try:
            data = json.loads(path.read_text())
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ExecError(
                "ERR_EXEC_ATTEMPT_MALFORMED",
                f"attempt JSON is malformed: {exc}",
                path=path,
            ) from exc
        if not isinstance(data, dict) or data.get("attempt_id") != child.name:
            raise ExecError(
                "ERR_EXEC_ATTEMPT_MALFORMED",
                "attempt JSON does not match directory",
                path=path,
            )
        validate_attempt_sidecars(child, data)
        validate_attempt_hashes(
            child,
            data,
            expected_packet_hash=expected_packet_hash,
            expected_prompt_hash=expected_prompt_hash,
            expected_run_id=expected_run_id,
            expected_v1_run_path=expected_v1_run_path,
            expected_packet_id=expected_packet_id,
        )
        validate_attempt_contract(child, data, contracts.get(child.name))
        status, verification_result = evidence_status_for_attempt(child, data)
        data["status"] = status
        data["verification_result"] = verification_result
        attempts.append(data)
    attempt_ids = [int(item["attempt_id"]) for item in attempts]
    if attempt_ids != list(range(len(attempt_ids))):
        raise ExecError(
            "ERR_EXEC_ATTEMPT_MALFORMED",
            "attempt IDs are not contiguous",
            path=attempts_dir,
        )
    return attempts


def validate_attempt_relative_file(attempt_dir: Path, value: Any, field: str) -> None:
    if value is None:
        return
    if not isinstance(value, str) or not value:
        raise ExecError(
            "ERR_EXEC_ATTEMPT_MALFORMED",
            f"{field} must be a relative file path or null",
            path=attempt_dir,
        )
    rel_path = Path(value)
    if rel_path.is_absolute() or any(part == ".." for part in rel_path.parts):
        raise ExecError(
            "ERR_EXEC_ATTEMPT_MALFORMED",
            f"{field} escapes attempt directory",
            path=rel_path,
        )
    target = attempt_dir / rel_path
    try:
        target.resolve(strict=False).relative_to(attempt_dir.resolve(strict=False))
    except ValueError as exc:
        raise ExecError(
            "ERR_EXEC_ATTEMPT_MALFORMED",
            f"{field} escapes attempt directory",
            path=target,
        ) from exc
    if not target.is_file() or target.is_symlink():
        raise ExecError(
            "ERR_EXEC_ATTEMPT_MALFORMED",
            f"{field} is missing or symlinked",
            path=target,
        )


def validate_attempt_sidecars(attempt_dir: Path, attempt: dict[str, Any]) -> None:
    required_fields = [
        "prompt_path",
        "execution_brief_path",
        "backend_command_path",
        "git_status_path",
        "git_diff_summary_path",
        "verification_path",
        "hashes_path",
    ]
    for field in required_fields:
        if attempt.get(field) is None:
            raise ExecError(
                "ERR_EXEC_ATTEMPT_MALFORMED",
                f"{field} is required",
                path=attempt_dir / "attempt.json",
            )
        validate_attempt_relative_file(attempt_dir, attempt.get(field), field)
    for field in ["stdout_path", "stderr_path", "transcript_path"]:
        validate_attempt_relative_file(attempt_dir, attempt.get(field), field)
    for field in [
        "pre_git_status_path",
        "pre_git_diff_summary_path",
        "pre_tracked_state_path",
        "post_tracked_state_path",
    ]:
        validate_attempt_relative_file(attempt_dir, attempt.get(field), field)
    verification = attempt.get("verification")
    if isinstance(verification, list):
        for index, item in enumerate(verification):
            if isinstance(item, dict):
                validate_attempt_relative_file(
                    attempt_dir,
                    item.get("stdout_path"),
                    f"verification[{index}].stdout_path",
                )
                validate_attempt_relative_file(
                    attempt_dir,
                    item.get("stderr_path"),
                    f"verification[{index}].stderr_path",
                )
                validate_attempt_relative_file(
                    attempt_dir,
                    item.get("checked_state_path"),
                    f"verification[{index}].checked_state_path",
                )


def status_from_attempts(attempts: list[dict[str, Any]]) -> str:
    if not attempts:
        return "not-started"
    latest = attempts[-1].get("status")
    if latest in {"prepared", "executed", "verified", "failed", "blocked"}:
        return str(latest)
    return "invalid"


def write_blocked_status(
    v1_run_dir: Path, v2_dir: Path, error: ExecError
) -> dict[str, Any]:
    run_id = v1_run_dir.name
    try:
        run = read_json_file(v1_run_dir / "run.json", root=v1_run_dir, label="run.json")
        run_id = str(run.get("run_id", run_id))
    except ExecError:
        pass
    ensure_v2_dir(v2_dir, run_id, v1_run_dir)
    attempts: list[dict[str, Any]] = []
    status_value = (
        "invalid" if error.code == "ERR_EXEC_ATTEMPT_MALFORMED" else "blocked"
    )
    invalidators = [error.to_record()]
    try:
        attempts = existing_attempts(v2_dir)
    except ExecError as attempt_error:
        if attempt_error.code == "ERR_EXEC_ATTEMPT_MALFORMED":
            status_value = "invalid"
        if attempt_error.code != error.code:
            invalidators.append(attempt_error.to_record())
    status = build_status(
        run_id,
        v1_run_dir,
        status=status_value,
        attempts=attempts,
        invalidators=invalidators,
    )
    write_status(v2_dir, status)
    return status


def trusted_v2_attempt_context(
    v1_run_dir: Path, out_dir: Path | None = None
) -> tuple[dict[str, Any], Path, list[dict[str, Any]], dict[str, dict[str, Any]]]:
    v1_run_dir = resolve_v1_run(v1_run_dir)
    out_dir = (
        resolve_v2_out(out_dir)
        if out_dir is not None
        else V2_OUT_ROOT / v1_run_dir.name
    )
    context = trust_v1_run(v1_run_dir)
    run_id = context["run"]["run_id"]
    ensure_v2_dir(out_dir, run_id, v1_run_dir)
    attempts = existing_attempts(
        out_dir,
        expected_packet_hash=context["packet_hash"],
        expected_prompt_hash=context["prompt_hash"],
        expected_run_id=run_id,
        expected_v1_run_path=rel(v1_run_dir),
        expected_packet_id=PACKET_ID,
    )
    if not attempts:
        raise ExecError(
            "ERR_REVIEW_SOURCE_INVALID",
            "V2.5 review requires at least one trusted V2 attempt",
            path=out_dir,
        )
    return context, out_dir, attempts, read_attempt_contracts(out_dir, required=True)


def source_hashes_for_review(
    context: dict[str, Any],
    out_dir: Path,
    attempts: list[dict[str, Any]],
    attempt_contracts: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    latest = attempts[-1]
    invalidators = invalidators_for_attempt(
        out_dir / "attempts" / str(latest["attempt_id"]), latest
    )
    stable_v2_status = build_status(
        context["run"]["run_id"],
        context["v1_run_dir"],
        status=status_from_attempts(attempts),
        attempts=attempts,
        invalidators=invalidators,
    )
    stable_v2_status.pop("checked_at", None)
    return {
        "packet_hash": context["packet_hash"],
        "prompt_hash": context["prompt_hash"],
        "attempt_contract_hash": canonical_hash(
            attempt_contracts[str(latest["attempt_id"])]
        ),
        "v2_status_hash": canonical_hash(stable_v2_status),
    }


def deterministic_review_findings(
    attempt: dict[str, Any],
) -> tuple[str, list[dict[str, Any]], str]:
    status = attempt.get("status")
    if status in {"executed", "verified"}:
        return (
            "approve",
            [],
            "Execution evidence is trusted and no deterministic counterexample was found.",
        )
    if status == "failed":
        finding = {
            "finding_id": "finding-0000",
            "severity": "critical",
            "file_or_artifact": f"attempts/{attempt.get('attempt_id')}/attempt.json",
            "line_or_pointer": "/status",
            "claim": "The packet execution or verification failed.",
            "evidence": f"attempt status is {status} with verification_result {attempt.get('verification_result')}",
            "falsifier": "A trusted resume showing executed or verified status would falsify this finding.",
            "suggested_fix": "Prepare a bounded repair prompt that addresses the failed execution evidence.",
            "repair_allowed": True,
        }
        return (
            "request_changes",
            [finding],
            "Deterministic review found a repairable failed attempt.",
        )
    finding = {
        "finding_id": "finding-0000",
        "severity": "warning",
        "file_or_artifact": f"attempts/{attempt.get('attempt_id')}/attempt.json",
        "line_or_pointer": "/status",
        "claim": "The attempt is not executable enough for automatic approval.",
        "evidence": f"attempt status is {status}",
        "falsifier": "Executed or verified evidence with matching contracts would falsify this finding.",
        "suggested_fix": "Ask a human to decide whether this prepared or blocked evidence is sufficient.",
        "repair_allowed": False,
    }
    return (
        "needs_human_review",
        [finding],
        "Deterministic review requires human judgment.",
    )


def render_review_markdown(review: dict[str, Any]) -> str:
    lines = [
        "# V2.5 Review",
        "",
        f"Review ID: `{review['review_id']}`",
        f"Source attempt: `{review['source_attempt_id']}`",
        f"Verdict: `{review['verdict']}`",
        "",
        review["summary"],
        "",
        "## Findings",
    ]
    findings = review.get("findings", [])
    if findings:
        for finding in findings:
            lines.append(
                f"- `{finding.get('finding_id')}` {finding.get('severity')}: {finding.get('claim')}"
            )
    else:
        lines.append("- none")
    return "\n".join(lines) + "\n"


def build_v25_status(
    run_id: str,
    v1_run_dir: Path,
    *,
    status: str,
    attempts: list[dict[str, Any]],
    reviews: list[dict[str, Any]] | None = None,
    repairs: list[dict[str, Any]] | None = None,
    invalidators: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    reviews = reviews or []
    repairs = repairs or []
    base = build_status(
        run_id, v1_run_dir, status=status, attempts=attempts, invalidators=invalidators
    )
    base.update(
        {
            "review_count": len(reviews),
            "latest_review_id": reviews[-1]["review_id"] if reviews else None,
            "reviews": reviews,
            "repair_count": len(repairs),
            "latest_repair_id": repairs[-1]["repair_id"] if repairs else None,
            "repairs": repairs,
        }
    )
    return base


def validate_review(
    review_dir: Path,
    review: dict[str, Any],
    contract: dict[str, Any] | None,
    attempts_by_id: dict[str, dict[str, Any]],
    expected_source_hashes: dict[str, Any],
    expected_source_attempt_id: str,
    *,
    require_current: bool,
) -> None:
    if contract is None:
        raise ExecError(
            "ERR_REVIEW_ARTIFACT_MALFORMED",
            "review contract ledger entry is missing",
            path=review_dir / "review.json",
        )
    if review.get("schema_version") != SCHEMA_VERSION:
        raise ExecError(
            "ERR_REVIEW_ARTIFACT_MALFORMED",
            "review schema_version is malformed",
            path=review_dir / "review.json",
        )
    review_id = review.get("review_id")
    if (
        not isinstance(review_id, str)
        or not re.fullmatch(r"\d{4}", review_id)
        or review_id != review_dir.name
    ):
        raise ExecError(
            "ERR_REVIEW_ARTIFACT_MALFORMED",
            "review_id is malformed",
            path=review_dir / "review.json",
        )
    if review.get("source_attempt_id") not in attempts_by_id:
        raise ExecError(
            "ERR_REVIEW_ARTIFACT_MALFORMED",
            "review source attempt is missing",
            path=review_dir / "review.json",
        )
    if (
        require_current
        and review.get("source_attempt_id") != expected_source_attempt_id
    ):
        raise ExecError(
            "ERR_REVIEW_ARTIFACT_MALFORMED",
            "review is stale relative to latest V2 attempt",
            path=review_dir / "review.json",
        )
    if review.get("verdict") not in {
        "approve",
        "request_changes",
        "needs_human_review",
    }:
        raise ExecError(
            "ERR_REVIEW_ARTIFACT_MALFORMED",
            "review verdict is unsupported",
            path=review_dir / "review.json",
        )
    findings = review.get("findings")
    if not isinstance(findings, list):
        raise ExecError(
            "ERR_REVIEW_ARTIFACT_MALFORMED",
            "review findings must be a list",
            path=review_dir / "review.json",
        )
    for index, finding in enumerate(findings):
        if (
            not isinstance(finding, dict)
            or not isinstance(finding.get("evidence"), str)
            or not isinstance(finding.get("repair_allowed"), bool)
        ):
            raise ExecError(
                "ERR_REVIEW_ARTIFACT_MALFORMED",
                f"review finding {index} is malformed",
                path=review_dir / "review.json",
            )
        if not finding.get("evidence").strip():
            raise ExecError(
                "ERR_REVIEW_ARTIFACT_MALFORMED",
                f"review finding {index} lacks evidence",
                path=review_dir / "review.json",
            )
    for field in ["markdown_path", "hashes_path"]:
        validate_record_relative_file(
            review_dir, review.get(field), field, "ERR_REVIEW_ARTIFACT_MALFORMED"
        )
    hashes_data = read_record_json(
        review_dir,
        str(review.get("hashes_path")),
        "review hashes.json",
        "ERR_REVIEW_ARTIFACT_MALFORMED",
    )
    if not isinstance(hashes_data, dict):
        raise ExecError(
            "ERR_REVIEW_ARTIFACT_MALFORMED",
            "review hashes.json root must be an object",
            path=review_dir / str(review.get("hashes_path")),
        )
    markdown = read_record_text(
        review_dir,
        review.get("markdown_path"),
        "review markdown",
        "ERR_REVIEW_ARTIFACT_MALFORMED",
    )
    validate_hash_value_with_code(
        canonical_hash(review),
        required_hash_value_with_code(
            hashes_data,
            "review_hash",
            review_dir / "hashes.json",
            "ERR_REVIEW_ARTIFACT_MALFORMED",
        ),
        "review",
        review_dir / "review.json",
        "ERR_REVIEW_ARTIFACT_MALFORMED",
    )
    validate_hash_value_with_code(
        sha256_text(markdown),
        required_hash_value_with_code(
            hashes_data,
            "markdown_hash",
            review_dir / "hashes.json",
            "ERR_REVIEW_ARTIFACT_MALFORMED",
        ),
        "review markdown",
        review_dir / str(review.get("markdown_path")),
        "ERR_REVIEW_ARTIFACT_MALFORMED",
    )
    validate_hash_value_with_code(
        canonical_hash(review.get("source_hashes")),
        required_hash_value_with_code(
            hashes_data,
            "source_hashes_hash",
            review_dir / "hashes.json",
            "ERR_REVIEW_ARTIFACT_MALFORMED",
        ),
        "review source_hashes",
        review_dir / "review.json",
        "ERR_REVIEW_ARTIFACT_MALFORMED",
    )
    if require_current and review.get("source_hashes") != expected_source_hashes:
        raise ExecError(
            "ERR_REVIEW_ARTIFACT_MALFORMED",
            "review source hashes are stale relative to current V2 evidence",
            path=review_dir / "review.json",
        )
    if review_contract(review, hashes_data) != contract:
        raise ExecError(
            "ERR_REVIEW_ARTIFACT_MALFORMED",
            "review does not match root contract ledger",
            path=review_dir / "review.json",
        )


def existing_reviews(
    v2_dir: Path,
    attempts: list[dict[str, Any]],
    context: dict[str, Any],
    attempt_contracts: dict[str, dict[str, Any]],
    *,
    require_current: bool = True,
) -> list[dict[str, Any]]:
    reviews_dir = v2_dir / "reviews"
    if not reviews_dir.exists():
        return []
    if reviews_dir.is_symlink() or not reviews_dir.is_dir():
        raise ExecError(
            "ERR_REVIEW_ARTIFACT_MALFORMED",
            "reviews directory is malformed",
            path=reviews_dir,
        )
    children = sorted(reviews_dir.iterdir(), key=lambda item: item.name)
    if not children:
        return []
    contracts = read_contracts(
        v2_dir,
        REVIEW_CONTRACTS,
        "reviews",
        "ERR_REVIEW_ARTIFACT_MALFORMED",
        required=True,
    )
    attempts_by_id = {str(item["attempt_id"]): item for item in attempts}
    latest_attempt_id = str(attempts[-1]["attempt_id"])
    latest_review_dir_name = children[-1].name
    expected_source_hashes = source_hashes_for_review(
        context, v2_dir, attempts, attempt_contracts
    )
    reviews = []
    for child in children:
        if (
            child.is_symlink()
            or not child.is_dir()
            or not re.fullmatch(r"\d{4}", child.name)
        ):
            raise ExecError(
                "ERR_REVIEW_ARTIFACT_MALFORMED",
                "reviews directory contains unexpected entry",
                path=child,
            )
        review = read_record_json(
            child, "review.json", "review.json", "ERR_REVIEW_ARTIFACT_MALFORMED"
        )
        if not isinstance(review, dict):
            raise ExecError(
                "ERR_REVIEW_ARTIFACT_MALFORMED",
                "review.json root must be an object",
                path=child / "review.json",
            )
        validate_review(
            child,
            review,
            contracts.get(child.name),
            attempts_by_id,
            expected_source_hashes,
            latest_attempt_id,
            require_current=require_current and child.name == latest_review_dir_name,
        )
        reviews.append(review)
    ids = [int(item["review_id"]) for item in reviews]
    if ids != list(range(len(ids))):
        raise ExecError(
            "ERR_REVIEW_ARTIFACT_MALFORMED",
            "review IDs are not contiguous",
            path=reviews_dir,
        )
    return reviews


def validate_repair(
    repair_dir: Path,
    repair: dict[str, Any],
    contract: dict[str, Any] | None,
    reviews_by_id: dict[str, dict[str, Any]],
    expected_source_review_id: str,
    expected_source_hashes: dict[str, Any],
) -> None:
    if contract is None:
        raise ExecError(
            "ERR_REPAIR_ARTIFACT_MALFORMED",
            "repair contract ledger entry is missing",
            path=repair_dir / "repair-attempt.json",
        )
    if repair.get("schema_version") != SCHEMA_VERSION:
        raise ExecError(
            "ERR_REPAIR_ARTIFACT_MALFORMED",
            "repair schema_version is malformed",
            path=repair_dir / "repair-attempt.json",
        )
    repair_id = repair.get("repair_id")
    if (
        not isinstance(repair_id, str)
        or not re.fullmatch(r"\d{4}", repair_id)
        or repair_id != repair_dir.name
    ):
        raise ExecError(
            "ERR_REPAIR_ARTIFACT_MALFORMED",
            "repair_id is malformed",
            path=repair_dir / "repair-attempt.json",
        )
    if repair.get("source_review_id") not in reviews_by_id:
        raise ExecError(
            "ERR_REPAIR_ARTIFACT_MALFORMED",
            "repair source review is missing",
            path=repair_dir / "repair-attempt.json",
        )
    if repair.get("source_review_id") != expected_source_review_id:
        raise ExecError(
            "ERR_REPAIR_ARTIFACT_MALFORMED",
            "repair is stale relative to latest review",
            path=repair_dir / "repair-attempt.json",
        )
    if repair.get("status") != "repair-prepared":
        raise ExecError(
            "ERR_REPAIR_ARTIFACT_MALFORMED",
            "first V2.5 repair slice may only prepare repair prompts",
            path=repair_dir / "repair-attempt.json",
        )
    for field in ["prompt_path", "verification_path", "hashes_path"]:
        validate_record_relative_file(
            repair_dir, repair.get(field), field, "ERR_REPAIR_ARTIFACT_MALFORMED"
        )
    hashes_data = read_record_json(
        repair_dir,
        str(repair.get("hashes_path")),
        "repair hashes.json",
        "ERR_REPAIR_ARTIFACT_MALFORMED",
    )
    verification = read_record_json(
        repair_dir,
        str(repair.get("verification_path")),
        "repair verification.json",
        "ERR_REPAIR_ARTIFACT_MALFORMED",
    )
    prompt = read_record_text(
        repair_dir,
        repair.get("prompt_path"),
        "repair prompt",
        "ERR_REPAIR_ARTIFACT_MALFORMED",
    )
    if not isinstance(hashes_data, dict) or not isinstance(verification, list):
        raise ExecError(
            "ERR_REPAIR_ARTIFACT_MALFORMED",
            "repair sidecars are malformed",
            path=repair_dir,
        )
    if repair.get("verification") != verification:
        raise ExecError(
            "ERR_REPAIR_ARTIFACT_MALFORMED",
            "repair verification does not match verification.json",
            path=repair_dir / "repair-attempt.json",
        )
    validate_hash_value_with_code(
        canonical_hash(repair),
        required_hash_value_with_code(
            hashes_data,
            "repair_attempt_hash",
            repair_dir / "hashes.json",
            "ERR_REPAIR_ARTIFACT_MALFORMED",
        ),
        "repair attempt",
        repair_dir / "repair-attempt.json",
        "ERR_REPAIR_ARTIFACT_MALFORMED",
    )
    validate_hash_value_with_code(
        sha256_text(prompt),
        required_hash_value_with_code(
            hashes_data,
            "prompt_hash",
            repair_dir / "hashes.json",
            "ERR_REPAIR_ARTIFACT_MALFORMED",
        ),
        "repair prompt",
        repair_dir / str(repair.get("prompt_path")),
        "ERR_REPAIR_ARTIFACT_MALFORMED",
    )
    validate_hash_value_with_code(
        canonical_hash(verification),
        required_hash_value_with_code(
            hashes_data,
            "verification_hash",
            repair_dir / "hashes.json",
            "ERR_REPAIR_ARTIFACT_MALFORMED",
        ),
        "repair verification",
        repair_dir / str(repair.get("verification_path")),
        "ERR_REPAIR_ARTIFACT_MALFORMED",
    )
    if repair.get("source_hashes") != expected_source_hashes:
        raise ExecError(
            "ERR_REPAIR_ARTIFACT_MALFORMED",
            "repair source hashes are stale relative to current review or attempt ledgers",
            path=repair_dir / "repair-attempt.json",
        )
    if repair_contract(repair, hashes_data) != contract:
        raise ExecError(
            "ERR_REPAIR_ARTIFACT_MALFORMED",
            "repair does not match root contract ledger",
            path=repair_dir / "repair-attempt.json",
        )


def existing_repairs(
    v2_dir: Path, reviews: list[dict[str, Any]], attempts: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    repairs_dir = v2_dir / "repairs"
    if not repairs_dir.exists():
        return []
    if repairs_dir.is_symlink() or not repairs_dir.is_dir():
        raise ExecError(
            "ERR_REPAIR_ARTIFACT_MALFORMED",
            "repairs directory is malformed",
            path=repairs_dir,
        )
    children = sorted(repairs_dir.iterdir(), key=lambda item: item.name)
    if not children:
        return []
    contracts = read_contracts(
        v2_dir,
        REPAIR_CONTRACTS,
        "repairs",
        "ERR_REPAIR_ARTIFACT_MALFORMED",
        required=True,
    )
    reviews_by_id = {str(item["review_id"]): item for item in reviews}
    review_contracts = read_contracts(
        v2_dir,
        REVIEW_CONTRACTS,
        "reviews",
        "ERR_REVIEW_ARTIFACT_MALFORMED",
        required=True,
    )
    attempt_contracts = read_attempt_contracts(v2_dir, required=True)
    latest_review_id = str(reviews[-1]["review_id"]) if reviews else ""
    repairs = []
    for child in children:
        if (
            child.is_symlink()
            or not child.is_dir()
            or not re.fullmatch(r"\d{4}", child.name)
        ):
            raise ExecError(
                "ERR_REPAIR_ARTIFACT_MALFORMED",
                "repairs directory contains unexpected entry",
                path=child,
            )
        repair = read_record_json(
            child,
            "repair-attempt.json",
            "repair-attempt.json",
            "ERR_REPAIR_ARTIFACT_MALFORMED",
        )
        if not isinstance(repair, dict):
            raise ExecError(
                "ERR_REPAIR_ARTIFACT_MALFORMED",
                "repair-attempt.json root must be an object",
                path=child / "repair-attempt.json",
            )
        source_review_id = repair.get("source_review_id")
        source_attempt_id = repair.get("source_attempt_id")
        if not isinstance(source_review_id, str) or not isinstance(
            source_attempt_id, str
        ):
            raise ExecError(
                "ERR_REPAIR_ARTIFACT_MALFORMED",
                "repair source IDs are malformed",
                path=child / "repair-attempt.json",
            )
        if (
            source_review_id not in review_contracts
            or source_attempt_id not in attempt_contracts
        ):
            raise ExecError(
                "ERR_REPAIR_ARTIFACT_MALFORMED",
                "repair source contracts are missing",
                path=child / "repair-attempt.json",
            )
        expected_source_hashes = {
            "source_review_contract_hash": canonical_hash(
                review_contracts[source_review_id]
            ),
            "source_attempt_contract_hash": canonical_hash(
                attempt_contracts[source_attempt_id]
            ),
        }
        validate_repair(
            child,
            repair,
            contracts.get(child.name),
            reviews_by_id,
            latest_review_id,
            expected_source_hashes,
        )
        repairs.append(repair)
    ids = [int(item["repair_id"]) for item in repairs]
    if ids != list(range(len(ids))):
        raise ExecError(
            "ERR_REPAIR_ARTIFACT_MALFORMED",
            "repair IDs are not contiguous",
            path=repairs_dir,
        )
    return repairs


def status_from_review_repair(
    reviews: list[dict[str, Any]], repairs: list[dict[str, Any]]
) -> str:
    if repairs:
        return str(repairs[-1].get("status", "invalid"))
    if not reviews:
        return "review-pending"
    verdict = reviews[-1].get("verdict")
    if verdict == "approve":
        return "review-approved"
    if verdict == "request_changes":
        return "changes-requested"
    if verdict == "needs_human_review":
        return "needs-human"
    return "invalid"


def write_v25_error_status(
    v1_run_dir: Path, v2_dir: Path, error: ExecError
) -> dict[str, Any]:
    run_id = v1_run_dir.name
    try:
        run = read_json_file(v1_run_dir / "run.json", root=v1_run_dir, label="run.json")
        run_id = str(run.get("run_id", run_id))
        ensure_v2_dir(v2_dir, run_id, v1_run_dir)
    except ExecError:
        pass
    attempts: list[dict[str, Any]] = []
    try:
        attempts = existing_attempts(v2_dir)
    except ExecError:
        attempts = []
    status_value = (
        "invalid"
        if error.code
        in {
            "ERR_REVIEW_ARTIFACT_MALFORMED",
            "ERR_REPAIR_ARTIFACT_MALFORMED",
            "ERR_EXEC_ATTEMPT_MALFORMED",
        }
        else "needs-human"
    )
    status = build_v25_status(
        run_id,
        v1_run_dir,
        status=status_value,
        attempts=attempts,
        reviews=[],
        repairs=[],
        invalidators=[error.to_record()],
    )
    write_status(v2_dir, status)
    return status


def review_execution(
    v1_run_dir: Path, *, out_dir: Path | None = None
) -> dict[str, Any]:
    v1_run_dir = resolve_v1_run(v1_run_dir)
    out_dir = (
        resolve_v2_out(out_dir)
        if out_dir is not None
        else V2_OUT_ROOT / v1_run_dir.name
    )
    try:
        context, out_dir, attempts, attempt_contracts = trusted_v2_attempt_context(
            v1_run_dir, out_dir
        )
        existing = existing_reviews(
            out_dir, attempts, context, attempt_contracts, require_current=False
        )
        review_id = next_record_id(out_dir, "reviews", "ERR_REVIEW_ARTIFACT_MALFORMED")
        review_dir = out_dir / "reviews" / review_id
        review_dir.mkdir(parents=True, exist_ok=False)
        latest = attempts[-1]
        verdict, findings, summary = deterministic_review_findings(latest)
        review = {
            "schema_version": SCHEMA_VERSION,
            "adapter_version": ADAPTER_VERSION,
            "review_id": review_id,
            "run_id": context["run"]["run_id"],
            "v1_run_path": rel(context["v1_run_dir"]),
            "source_attempt_id": latest["attempt_id"],
            "reviewer_role": "deterministic-v2.5-reviewer",
            "scope": "one trusted V2 first-slice packet attempt",
            "findings": findings,
            "summary": summary,
            "verdict": verdict,
            "created_at": now_utc(),
            "source_hashes": source_hashes_for_review(
                context, out_dir, attempts, attempt_contracts
            ),
            "markdown_path": "review.md",
            "hashes_path": "hashes.json",
        }
        markdown = render_review_markdown(review)
        hashes = {
            "review_hash": canonical_hash(review),
            "markdown_hash": sha256_text(markdown),
            "source_hashes_hash": canonical_hash(review["source_hashes"]),
        }
        write_json(review_dir / "review.json", review, root=out_dir)
        write_text(review_dir / "review.md", markdown, root=out_dir)
        write_json(review_dir / "hashes.json", hashes, root=out_dir)
        append_review_contract(out_dir, review, hashes)
        reviews = existing + [review]
        status = build_v25_status(
            context["run"]["run_id"],
            context["v1_run_dir"],
            status=status_from_review_repair(reviews, []),
            attempts=attempts,
            reviews=reviews,
            repairs=[],
        )
    except ExecError as exc:
        status = write_v25_error_status(v1_run_dir, out_dir, exc)
        return {"status": status, "out_dir": out_dir}
    write_status(out_dir, status)
    return {
        "status": status,
        "out_dir": out_dir,
        "review": reviews[-1],
        "review_dir": out_dir / "reviews" / reviews[-1]["review_id"],
    }


def review_resume(v1_run_dir: Path, *, out_dir: Path | None = None) -> dict[str, Any]:
    v1_run_dir = resolve_v1_run(v1_run_dir)
    out_dir = (
        resolve_v2_out(out_dir)
        if out_dir is not None
        else V2_OUT_ROOT / v1_run_dir.name
    )
    try:
        context, out_dir, attempts, attempt_contracts = trusted_v2_attempt_context(
            v1_run_dir, out_dir
        )
        reviews = existing_reviews(out_dir, attempts, context, attempt_contracts)
        repairs = existing_repairs(out_dir, reviews, attempts)
        status = build_v25_status(
            context["run"]["run_id"],
            context["v1_run_dir"],
            status=status_from_review_repair(reviews, repairs),
            attempts=attempts,
            reviews=reviews,
            repairs=repairs,
        )
    except ExecError as exc:
        status = write_v25_error_status(v1_run_dir, out_dir, exc)
        return {"status": status, "out_dir": out_dir}
    write_status(out_dir, status)
    return {"status": status, "out_dir": out_dir}


def render_repair_prompt(review: dict[str, Any]) -> str:
    lines = [
        "# V2.5 Repair Prompt",
        "",
        f"Run ID: `{review['run_id']}`",
        f"Source review: `{review['review_id']}`",
        f"Source attempt: `{review['source_attempt_id']}`",
        "",
        "Prepare a bounded patch for the findings below. Do not merge, push, deploy, install dependencies, access secrets, send external messages, rewrite history, delete files, or advance later workflow packets.",
        "",
        "## Actionable Findings",
    ]
    for finding in review.get("findings", []):
        if isinstance(finding, dict) and finding.get("repair_allowed") is True:
            lines.extend(
                [
                    "",
                    f"### {finding.get('finding_id')}",
                    f"- Claim: {finding.get('claim')}",
                    f"- Evidence: {finding.get('evidence')}",
                    f"- Falsifier: {finding.get('falsifier')}",
                    f"- Suggested fix: {finding.get('suggested_fix')}",
                ]
            )
    return "\n".join(lines) + "\n"


def prepare_repair(v1_run_dir: Path, *, out_dir: Path | None = None) -> dict[str, Any]:
    v1_run_dir = resolve_v1_run(v1_run_dir)
    out_dir = (
        resolve_v2_out(out_dir)
        if out_dir is not None
        else V2_OUT_ROOT / v1_run_dir.name
    )
    try:
        context, out_dir, attempts, attempt_contracts = trusted_v2_attempt_context(
            v1_run_dir, out_dir
        )
        reviews = existing_reviews(out_dir, attempts, context, attempt_contracts)
        repairs = existing_repairs(out_dir, reviews, attempts)
        if not reviews:
            raise ExecError(
                "ERR_REPAIR_NOT_ALLOWED",
                "repair requires a trusted review first",
                path=out_dir,
            )
        latest_review = reviews[-1]
        actionable = [
            finding
            for finding in latest_review.get("findings", [])
            if isinstance(finding, dict) and finding.get("repair_allowed") is True
        ]
        if latest_review.get("verdict") != "request_changes" or not actionable:
            status = build_v25_status(
                context["run"]["run_id"],
                context["v1_run_dir"],
                status="needs-human",
                attempts=attempts,
                reviews=reviews,
                repairs=repairs,
                invalidators=[
                    {
                        "code": "ERR_REPAIR_NOT_ALLOWED",
                        "message": "latest review does not authorize deterministic repair",
                    }
                ],
            )
            write_status(out_dir, status)
            return {"status": status, "out_dir": out_dir}
        if repairs:
            status = build_v25_status(
                context["run"]["run_id"],
                context["v1_run_dir"],
                status="needs-human",
                attempts=attempts,
                reviews=reviews,
                repairs=repairs,
                invalidators=[
                    {
                        "code": "ERR_REPAIR_NOT_ALLOWED",
                        "message": "V2.5 first release caps repair at one prepared attempt",
                    }
                ],
            )
            write_status(out_dir, status)
            return {"status": status, "out_dir": out_dir}
        repair_id = next_record_id(out_dir, "repairs", "ERR_REPAIR_ARTIFACT_MALFORMED")
        repair_dir = out_dir / "repairs" / repair_id
        repair_dir.mkdir(parents=True, exist_ok=False)
        verification = [
            {
                "check_id": f"repair-finding-{index:04d}",
                "claim_or_output": finding.get("claim"),
                "falsifier": finding.get("falsifier"),
                "mode": "manual",
                "result": "manual-required",
            }
            for index, finding in enumerate(actionable)
        ]
        repair = {
            "schema_version": SCHEMA_VERSION,
            "adapter_version": ADAPTER_VERSION,
            "repair_id": repair_id,
            "run_id": context["run"]["run_id"],
            "v1_run_path": rel(context["v1_run_dir"]),
            "source_attempt_id": latest_review["source_attempt_id"],
            "source_review_id": latest_review["review_id"],
            "status": "repair-prepared",
            "created_at": now_utc(),
            "findings": actionable,
            "prompt_path": "prompt.md",
            "verification_path": "verification.json",
            "hashes_path": "hashes.json",
            "verification": verification,
            "source_hashes": {
                "source_review_contract_hash": canonical_hash(
                    read_contracts(
                        out_dir,
                        REVIEW_CONTRACTS,
                        "reviews",
                        "ERR_REVIEW_ARTIFACT_MALFORMED",
                        required=True,
                    )[latest_review["review_id"]]
                ),
                "source_attempt_contract_hash": canonical_hash(
                    attempt_contracts[latest_review["source_attempt_id"]]
                ),
            },
        }
        prompt = render_repair_prompt(latest_review)
        hashes = {
            "repair_attempt_hash": canonical_hash(repair),
            "prompt_hash": sha256_text(prompt),
            "verification_hash": canonical_hash(verification),
            "source_hashes_hash": canonical_hash(repair["source_hashes"]),
        }
        write_json(repair_dir / "repair-attempt.json", repair, root=out_dir)
        write_text(repair_dir / "prompt.md", prompt, root=out_dir)
        write_json(repair_dir / "verification.json", verification, root=out_dir)
        write_json(repair_dir / "hashes.json", hashes, root=out_dir)
        append_repair_contract(out_dir, repair, hashes)
        repairs.append(repair)
        status = build_v25_status(
            context["run"]["run_id"],
            context["v1_run_dir"],
            status="repair-prepared",
            attempts=attempts,
            reviews=reviews,
            repairs=repairs,
        )
    except ExecError as exc:
        status = write_v25_error_status(v1_run_dir, out_dir, exc)
        return {"status": status, "out_dir": out_dir}
    write_status(out_dir, status)
    return {
        "status": status,
        "out_dir": out_dir,
        "repair": repairs[-1],
        "repair_dir": out_dir / "repairs" / repairs[-1]["repair_id"],
    }


def execute_dry_run(
    v1_run_dir: Path,
    *,
    out_dir: Path | None = None,
    backend: str = "dry-run",
    worktree: str | None = None,
    emit_only: bool = False,
) -> dict[str, Any]:
    v1_run_dir = resolve_v1_run(v1_run_dir)
    out_dir = (
        resolve_v2_out(out_dir)
        if out_dir is not None
        else V2_OUT_ROOT / v1_run_dir.name
    )
    try:
        if backend == "omx" and not emit_only:
            raise ExecError(
                "ERR_EXEC_BACKEND_UNAVAILABLE",
                "--backend omx requires --emit-only in V2",
            )
        context = trust_v1_run(v1_run_dir)
    except ExecError as exc:
        status = write_blocked_status(v1_run_dir, out_dir, exc)
        return {"status": status, "out_dir": out_dir}

    run_id = context["run"]["run_id"]
    ensure_v2_dir(out_dir, run_id, v1_run_dir)
    try:
        attempts = existing_attempts(
            out_dir,
            expected_packet_hash=context["packet_hash"],
            expected_prompt_hash=context["prompt_hash"],
            expected_run_id=run_id,
            expected_v1_run_path=rel(v1_run_dir),
            expected_packet_id=PACKET_ID,
        )
    except ExecError as exc:
        status = write_blocked_status(v1_run_dir, out_dir, exc)
        return {"status": status, "out_dir": out_dir}
    attempt_id = next_attempt_id(out_dir)
    attempt_dir = out_dir / "attempts" / attempt_id
    attempt_dir.mkdir(parents=True, exist_ok=False)

    started_at = now_utc()
    pre_git_status = git_text(["status", "--short"], ROOT)
    pre_git_diff = git_text(["diff", "--stat"], ROOT)
    pre_tracked_state = tracked_repo_state(ROOT)
    prompt_path = v1_run_dir / PROMPT_REL
    command = backend_command_preview(
        backend, v1_run_dir, prompt_path, worktree, emit_only
    )
    verification = verification_records(context["packet"])
    brief = render_execution_brief(context, command, verification)
    ended_at = now_utc()
    post_git_status = git_text(["status", "--short"], ROOT)
    post_git_diff = git_text(["diff", "--stat"], ROOT)
    post_tracked_state = tracked_repo_state(ROOT)
    attempt = attempt_record(
        context,
        attempt_id=attempt_id,
        backend=backend,
        command=command,
        verification=verification,
        started_at=started_at,
        ended_at=ended_at,
    )
    attempt["pre_git_status_path"] = "pre-git-status.txt"
    attempt["pre_git_diff_summary_path"] = "pre-git-diff-summary.txt"
    attempt["pre_tracked_state_path"] = "pre-tracked-state.txt"
    attempt["post_tracked_state_path"] = "post-tracked-state.txt"
    attempt["repo_tracked_diff_unchanged"] = pre_tracked_state == post_tracked_state
    hashes = {
        "packet_hash": context["packet_hash"],
        "prompt_hash": context["prompt_hash"],
        "attempt_hash": canonical_hash(attempt),
        "prompt_copy_hash": sha256_text(context["prompt"]),
        "execution_brief_hash": sha256_text(brief),
        "verification_hash": canonical_hash(verification),
        "backend_command_hash": canonical_hash(command),
        "pre_git_status_hash": sha256_text(pre_git_status),
        "pre_git_diff_summary_hash": sha256_text(pre_git_diff),
        "pre_tracked_state_hash": sha256_text(pre_tracked_state),
        "worktree_status_hash": sha256_text(post_git_status),
        "post_git_status_hash": sha256_text(post_git_status),
        "post_git_diff_summary_hash": sha256_text(post_git_diff),
        "post_tracked_state_hash": sha256_text(post_tracked_state),
    }

    write_json(attempt_dir / "attempt.json", attempt, root=out_dir)
    write_text(attempt_dir / "execution-brief.md", brief, root=out_dir)
    write_text(attempt_dir / "prompt.md", context["prompt"], root=out_dir)
    write_json(attempt_dir / "backend-command.json", command, root=out_dir)
    write_text(attempt_dir / "pre-git-status.txt", pre_git_status, root=out_dir)
    write_text(attempt_dir / "pre-git-diff-summary.txt", pre_git_diff, root=out_dir)
    write_text(attempt_dir / "pre-tracked-state.txt", pre_tracked_state, root=out_dir)
    write_text(attempt_dir / "post-tracked-state.txt", post_tracked_state, root=out_dir)
    write_text(attempt_dir / "git-status.txt", post_git_status, root=out_dir)
    write_text(attempt_dir / "git-diff-summary.txt", post_git_diff, root=out_dir)
    write_json(attempt_dir / "verification.json", verification, root=out_dir)
    write_json(attempt_dir / "hashes.json", hashes, root=out_dir)
    append_attempt_contract(out_dir, attempt, hashes)

    attempts.append(attempt)
    status = build_status(run_id, v1_run_dir, status="prepared", attempts=attempts)
    write_status(out_dir, status)
    return {
        "status": status,
        "attempt": attempt,
        "out_dir": out_dir,
        "attempt_dir": attempt_dir,
    }


def local_shell_command(local_shell: dict[str, Any]) -> tuple[list[str], int]:
    argv = local_shell.get("argv")
    if (
        not isinstance(argv, list)
        or not argv
        or not all(isinstance(item, str) and item for item in argv)
    ):
        raise ExecError(
            "ERR_EXEC_BACKEND_UNAVAILABLE",
            "local_shell.argv must be a non-empty string list",
        )
    expected_exit = local_shell.get("expected_exit_code", 0)
    if not isinstance(expected_exit, int):
        raise ExecError(
            "ERR_EXEC_BACKEND_UNAVAILABLE",
            "local_shell.expected_exit_code must be an integer",
        )
    return trusted_fixture_argv(argv), expected_exit


def validate_fixture_command_policy(argv: list[str]) -> None:
    if argv[0] != "python" or len(argv) != 3 or argv[1] != "-c":
        raise ExecError(
            "ERR_EXEC_BACKEND_UNAVAILABLE",
            "fixture commands must be approved python -c snippets",
        )
    if argv[2] not in ALLOWED_PYTHON_FIXTURE_SNIPPETS:
        raise ExecError(
            "ERR_EXEC_BACKEND_UNAVAILABLE", "fixture python snippet is not approved"
        )


def trusted_fixture_argv(argv: list[str]) -> list[str]:
    validate_fixture_command_policy(argv)
    return [sys.executable, "-c", argv[2]]


def resolve_public_manifest(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(
        raw,
        "ERR_EXEC_MANIFEST_REQUIRED_FAILED",
        "manifest path must not contain parent traversal",
    )
    candidate = raw if raw.is_absolute() else ROOT / raw
    check_components_not_symlink(candidate, "ERR_EXEC_DIR_SYMLINK")
    resolved = candidate.resolve(strict=False)
    trusted_manifests = {
        TRUSTED_V2_MANIFEST.resolve(strict=False),
        TRUSTED_V25_MANIFEST.resolve(strict=False),
    }
    if resolved not in trusted_manifests:
        raise ExecError(
            "ERR_EXEC_MANIFEST_REQUIRED_FAILED",
            "public --manifest is limited to fixtures/v2/manifest.json or fixtures/v2.5/manifest.json",
            path=value,
        )
    return resolved


def parse_verification_commands(commands: Any) -> list[dict[str, Any]]:
    if commands is None:
        return []
    if not isinstance(commands, list):
        raise ExecError(
            "ERR_EXEC_BACKEND_UNAVAILABLE", "verification_commands must be a list"
        )
    parsed: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, command in enumerate(commands):
        if not isinstance(command, dict):
            raise ExecError(
                "ERR_EXEC_BACKEND_UNAVAILABLE", "verification command must be an object"
            )
        check_id = command.get("id", f"auto-verification-{index:04d}")
        if not isinstance(check_id, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._-]*", check_id
        ):
            raise ExecError(
                "ERR_EXEC_BACKEND_UNAVAILABLE",
                "verification command id must be a safe token",
            )
        if check_id in seen:
            raise ExecError(
                "ERR_EXEC_BACKEND_UNAVAILABLE",
                "verification command ids must be unique",
            )
        seen.add(check_id)
        argv = command.get("argv")
        if (
            not isinstance(argv, list)
            or not argv
            or not all(isinstance(item, str) and item for item in argv)
        ):
            raise ExecError(
                "ERR_EXEC_BACKEND_UNAVAILABLE",
                "verification command argv must be a non-empty string list",
            )
        argv = trusted_fixture_argv(argv)
        expected_exit = command.get("expected_exit_code", 0)
        if not isinstance(expected_exit, int):
            raise ExecError(
                "ERR_EXEC_BACKEND_UNAVAILABLE",
                "verification expected_exit_code must be an integer",
            )
        parsed.append(
            {"check_id": check_id, "argv": argv, "expected_exit_code": expected_exit}
        )
    return parsed


def run_verification_commands(
    commands: list[dict[str, Any]],
    *,
    cwd: Path,
    attempt_dir: Path,
    out_dir: Path,
) -> tuple[list[dict[str, Any]], bool, dict[str, str]]:
    records: list[dict[str, Any]] = []
    output_hashes: dict[str, str] = {}
    for command in commands:
        check_id = command["check_id"]
        process = run_process(command["argv"], cwd)
        stdout_name = f"{check_id}.stdout.txt"
        stderr_name = f"{check_id}.stderr.txt"
        checked_state_name = f"{check_id}.checked-state.json"
        write_text(attempt_dir / stdout_name, process.stdout, root=out_dir)
        write_text(attempt_dir / stderr_name, process.stderr, root=out_dir)
        git_status = git_text(["status", "--short"], cwd)
        git_diff = git_text(["diff", "--stat"], cwd)
        checked_state = {"git_status": git_status, "git_diff": git_diff}
        write_json(attempt_dir / checked_state_name, checked_state, root=out_dir)
        checked_hash = canonical_hash(checked_state)
        passed = process.returncode == command["expected_exit_code"]
        records.append(
            {
                "check_id": check_id,
                "claim_or_output": f"manifest verification command {check_id}",
                "falsifier": f"exit code differs from {command['expected_exit_code']}",
                "mode": "automatic",
                "argv": command["argv"],
                "expected_exit_code": command["expected_exit_code"],
                "stdout_path": stdout_name,
                "stderr_path": stderr_name,
                "checked_state_path": checked_state_name,
                "exit_code": process.returncode,
                "checked_hash": checked_hash,
                "result": "pass" if passed else "fail",
            }
        )
        output_hashes[f"{check_id}.stdout_hash"] = sha256_text(process.stdout)
        output_hashes[f"{check_id}.stderr_hash"] = sha256_text(process.stderr)
        output_hashes[f"{check_id}.checked_hash"] = checked_hash
    return records, all(record["result"] == "pass" for record in records), output_hashes


def execute_local_shell(
    v1_run_dir: Path,
    *,
    out_dir: Path | None = None,
    worktree: str | None,
    local_shell: dict[str, Any] | None,
    verification_commands: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    v1_run_dir = resolve_v1_run(v1_run_dir)
    out_dir = (
        resolve_v2_out(out_dir)
        if out_dir is not None
        else V2_OUT_ROOT / v1_run_dir.name
    )
    try:
        context = trust_v1_run(v1_run_dir)
        argv, expected_exit = local_shell_command(local_shell or {})
        parsed_verification_commands = parse_verification_commands(
            verification_commands
        )
    except ExecError as exc:
        status = write_blocked_status(v1_run_dir, out_dir, exc)
        return {"status": status, "out_dir": out_dir}

    run_id = context["run"]["run_id"]
    ensure_v2_dir(out_dir, run_id, v1_run_dir)
    try:
        attempts = existing_attempts(
            out_dir,
            expected_packet_hash=context["packet_hash"],
            expected_prompt_hash=context["prompt_hash"],
            expected_run_id=run_id,
            expected_v1_run_path=rel(v1_run_dir),
            expected_packet_id=PACKET_ID,
        )
    except ExecError as exc:
        status = write_blocked_status(v1_run_dir, out_dir, exc)
        return {"status": status, "out_dir": out_dir}
    try:
        wt_path = ensure_git_worktree(worktree)
    except ExecError as exc:
        status = write_blocked_status(v1_run_dir, out_dir, exc)
        return {"status": status, "out_dir": out_dir}
    attempt_id = next_attempt_id(out_dir)
    attempt_dir = out_dir / "attempts" / attempt_id
    attempt_dir.mkdir(parents=True, exist_ok=False)

    started_at = now_utc()
    process = run_process(argv, wt_path)
    ended_at = now_utc()
    command = {
        "backend": "local-shell",
        "argv": argv,
        "expected_exit_code": expected_exit,
        "cwd": rel(wt_path),
        "emit_only": False,
        "description": "Deterministic manifest fixture command.",
    }
    attempt_status = "executed" if process.returncode == expected_exit else "failed"
    verification = verification_records(context["packet"])
    verification_hashes: dict[str, str] = {}
    verification_result = "manual-required"
    if attempt_status == "executed" and parsed_verification_commands:
        auto_records, verification_passed, verification_hashes = (
            run_verification_commands(
                parsed_verification_commands,
                cwd=wt_path,
                attempt_dir=attempt_dir,
                out_dir=out_dir,
            )
        )
        verification = [*verification, *auto_records]
        verification_result = "pass" if verification_passed else "fail"
        attempt_status = "verified" if verification_passed else "failed"
    attempt = attempt_record(
        context,
        attempt_id=attempt_id,
        backend="local-shell",
        command=command,
        verification=verification,
        started_at=started_at,
        ended_at=ended_at,
        status=attempt_status,
        exit_code=process.returncode,
        stdout_path="stdout.txt",
        stderr_path="stderr.txt",
        worktree_path=rel(wt_path),
    )
    attempt["verification_result"] = verification_result
    brief = render_execution_brief(context, command, verification)
    hashes = {
        "packet_hash": context["packet_hash"],
        "prompt_hash": context["prompt_hash"],
        "attempt_hash": canonical_hash(attempt),
        "prompt_copy_hash": sha256_text(context["prompt"]),
        "execution_brief_hash": sha256_text(brief),
        "verification_hash": canonical_hash(verification),
        "backend_command_hash": canonical_hash(command),
        "stdout_hash": sha256_text(process.stdout),
        "stderr_hash": sha256_text(process.stderr),
        "worktree_status_hash": sha256_text(git_text(["status", "--short"], wt_path)),
        "post_git_status_hash": sha256_text(git_text(["status", "--short"], wt_path)),
        "post_git_diff_summary_hash": sha256_text(
            git_text(["diff", "--stat"], wt_path)
        ),
        **verification_hashes,
    }

    write_json(attempt_dir / "attempt.json", attempt, root=out_dir)
    write_text(attempt_dir / "execution-brief.md", brief, root=out_dir)
    write_text(attempt_dir / "prompt.md", context["prompt"], root=out_dir)
    write_json(attempt_dir / "backend-command.json", command, root=out_dir)
    write_text(attempt_dir / "stdout.txt", process.stdout, root=out_dir)
    write_text(attempt_dir / "stderr.txt", process.stderr, root=out_dir)
    write_text(
        attempt_dir / "git-status.txt",
        git_text(["status", "--short"], wt_path),
        root=out_dir,
    )
    write_text(
        attempt_dir / "git-diff-summary.txt",
        git_text(["diff", "--stat"], wt_path),
        root=out_dir,
    )
    write_json(attempt_dir / "verification.json", verification, root=out_dir)
    write_json(attempt_dir / "hashes.json", hashes, root=out_dir)
    append_attempt_contract(out_dir, attempt, hashes)

    attempts.append(attempt)
    invalidators = []
    if attempt_status == "failed":
        if process.returncode != expected_exit:
            invalidators.append(
                {
                    "code": "ERR_EXEC_BACKEND_FAILED",
                    "message": f"local-shell exited {process.returncode}, expected {expected_exit}",
                }
            )
        elif verification_result == "fail":
            invalidators.append(
                {
                    "code": "ERR_EXEC_VERIFY_FAILED",
                    "message": "one or more verification commands failed",
                }
            )
    status = build_status(
        run_id,
        v1_run_dir,
        status=attempt_status,
        attempts=attempts,
        invalidators=invalidators,
    )
    write_status(out_dir, status)
    return {
        "status": status,
        "attempt": attempt,
        "out_dir": out_dir,
        "attempt_dir": attempt_dir,
    }


def timeout_from_config(config: dict[str, Any], default: int) -> int:
    value = config.get("timeout_seconds", default)
    if not isinstance(value, int) or value < 1 or value > 3600:
        raise ExecError(
            "ERR_EXEC_BACKEND_UNAVAILABLE",
            "timeout_seconds must be an integer between 1 and 3600",
        )
    return value


def preflight_codex_cli(codex_cli: dict[str, Any] | None) -> None:
    config = codex_cli or {}
    mode = config.get("mode", "installed-codex")
    if mode == "fixture-command":
        argv = config.get("argv")
        if (
            not isinstance(argv, list)
            or not argv
            or not all(isinstance(item, str) and item for item in argv)
        ):
            raise ExecError(
                "ERR_EXEC_BACKEND_UNAVAILABLE",
                "codex_cli.argv must be a non-empty string list",
            )
        expected_exit = config.get("expected_exit_code", 0)
        if not isinstance(expected_exit, int):
            raise ExecError(
                "ERR_EXEC_BACKEND_UNAVAILABLE",
                "codex_cli.expected_exit_code must be an integer",
            )
        trusted_fixture_argv(argv)
        timeout_from_config(config, 30)
        return
    if mode != "installed-codex":
        raise ExecError(
            "ERR_EXEC_BACKEND_UNAVAILABLE", f"unsupported codex_cli mode: {mode}"
        )
    if shutil.which("codex") is None:
        raise ExecError(
            "ERR_EXEC_BACKEND_UNAVAILABLE", "codex executable not found on PATH"
        )
    timeout_from_config(config, 120)


def parse_codex_cli(
    codex_cli: dict[str, Any] | None, *, attempt_dir: Path, wt_path: Path
) -> tuple[list[str], int, str, int]:
    config = codex_cli or {}
    mode = config.get("mode", "installed-codex")
    if mode == "fixture-command":
        argv = config.get("argv")
        if (
            not isinstance(argv, list)
            or not argv
            or not all(isinstance(item, str) and item for item in argv)
        ):
            raise ExecError(
                "ERR_EXEC_BACKEND_UNAVAILABLE",
                "codex_cli.argv must be a non-empty string list",
            )
        expected_exit = config.get("expected_exit_code", 0)
        if not isinstance(expected_exit, int):
            raise ExecError(
                "ERR_EXEC_BACKEND_UNAVAILABLE",
                "codex_cli.expected_exit_code must be an integer",
            )
        return (
            trusted_fixture_argv(argv),
            expected_exit,
            mode,
            timeout_from_config(config, 30),
        )
    if mode != "installed-codex":
        raise ExecError(
            "ERR_EXEC_BACKEND_UNAVAILABLE", f"unsupported codex_cli mode: {mode}"
        )
    codex_bin = shutil.which("codex")
    if codex_bin is None:
        raise ExecError(
            "ERR_EXEC_BACKEND_UNAVAILABLE", "codex executable not found on PATH"
        )
    transcript_path = attempt_dir / "transcript.md"
    # Optional config (defaults preserve the original first-slice behavior). The
    # research-orchestration Codex driver uses these: sandbox="read-only" to read
    # out-of-worktree sources, and output_schema to constrain the model's final
    # JSON response (codex exec --output-schema).
    sandbox = config.get("sandbox", "workspace-write")
    if sandbox not in ("read-only", "workspace-write", "danger-full-access"):
        raise ExecError(
            "ERR_EXEC_BACKEND_UNAVAILABLE",
            f"codex_cli.sandbox must be read-only|workspace-write|danger-full-access, got {sandbox!r}",
        )
    argv = [
        codex_bin,
        "exec",
        "--skip-git-repo-check",
        "--cd",
        str(wt_path),
        "--sandbox",
        sandbox,
        "--output-last-message",
        str(transcript_path),
    ]
    output_schema = config.get("output_schema")
    if output_schema is not None:
        if not isinstance(output_schema, str) or not output_schema:
            raise ExecError(
                "ERR_EXEC_BACKEND_UNAVAILABLE",
                "codex_cli.output_schema must be a non-empty string path",
            )
        schema_path = Path(output_schema)
        if not schema_path.is_file():
            raise ExecError(
                "ERR_EXEC_BACKEND_UNAVAILABLE",
                f"codex_cli.output_schema file not found: {output_schema}",
            )
        argv += ["--output-schema", str(schema_path)]
    argv.append("-")
    return argv, 0, mode, timeout_from_config(config, 120)


def codex_auth_failed(process: subprocess.CompletedProcess[str]) -> bool:
    text = f"{process.stdout}\n{process.stderr}".lower()
    patterns = [
        "invalid authentication credentials",
        "not logged in",
        "login",
        "unauthorized",
        "authentication",
        "401",
    ]
    return process.returncode != 0 and any(pattern in text for pattern in patterns)


def execute_codex_cli(
    v1_run_dir: Path,
    *,
    out_dir: Path | None = None,
    worktree: str | None,
    codex_cli: dict[str, Any] | None = None,
    verification_commands: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    v1_run_dir = resolve_v1_run(v1_run_dir)
    out_dir = (
        resolve_v2_out(out_dir)
        if out_dir is not None
        else V2_OUT_ROOT / v1_run_dir.name
    )
    try:
        context = trust_v1_run(v1_run_dir)
        parsed_verification_commands = parse_verification_commands(
            verification_commands
        )
    except ExecError as exc:
        status = write_blocked_status(v1_run_dir, out_dir, exc)
        return {"status": status, "out_dir": out_dir}

    run_id = context["run"]["run_id"]
    ensure_v2_dir(out_dir, run_id, v1_run_dir)
    try:
        attempts = existing_attempts(
            out_dir,
            expected_packet_hash=context["packet_hash"],
            expected_prompt_hash=context["prompt_hash"],
            expected_run_id=run_id,
            expected_v1_run_path=rel(v1_run_dir),
            expected_packet_id=PACKET_ID,
        )
    except ExecError as exc:
        status = write_blocked_status(v1_run_dir, out_dir, exc)
        return {"status": status, "out_dir": out_dir}
    attempt_id = next_attempt_id(out_dir)
    attempt_dir = out_dir / "attempts" / attempt_id

    try:
        preflight_codex_cli(codex_cli)
        wt_path = ensure_git_worktree(worktree)
        argv, expected_exit, mode, timeout_seconds = parse_codex_cli(
            codex_cli, attempt_dir=attempt_dir, wt_path=wt_path
        )
    except ExecError as exc:
        status = write_blocked_status(v1_run_dir, out_dir, exc)
        return {"status": status, "out_dir": out_dir}

    attempt_dir.mkdir(parents=True, exist_ok=False)
    started_at = now_utc()
    process = run_process(
        argv, wt_path, input_text=context["prompt"], timeout_seconds=timeout_seconds
    )
    ended_at = now_utc()
    transcript_path = attempt_dir / "transcript.md"
    if not transcript_path.exists():
        write_text(transcript_path, process.stdout, root=out_dir)
    command = {
        "backend": "codex-cli",
        "argv": argv,
        "expected_exit_code": expected_exit,
        "cwd": rel(wt_path),
        "mode": mode,
        "timeout_seconds": timeout_seconds,
        "emit_only": False,
        "description": "Codex CLI backend command.",
    }
    attempt_status = "executed" if process.returncode == expected_exit else "failed"
    invalidators: list[dict[str, Any]] = []
    if codex_auth_failed(process):
        attempt_status = "blocked"
        invalidators.append(
            {
                "code": "ERR_EXEC_BACKEND_AUTH",
                "message": "Codex CLI authentication failed",
            }
        )
    elif process.returncode != expected_exit:
        invalidators.append(
            {
                "code": "ERR_EXEC_BACKEND_FAILED",
                "message": f"codex-cli exited {process.returncode}, expected {expected_exit}",
            }
        )

    verification = verification_records(context["packet"])
    verification_hashes: dict[str, str] = {}
    verification_result = "manual-required"
    if attempt_status == "executed" and parsed_verification_commands:
        auto_records, verification_passed, verification_hashes = (
            run_verification_commands(
                parsed_verification_commands,
                cwd=wt_path,
                attempt_dir=attempt_dir,
                out_dir=out_dir,
            )
        )
        verification = [*verification, *auto_records]
        verification_result = "pass" if verification_passed else "fail"
        attempt_status = "verified" if verification_passed else "failed"
        if not verification_passed:
            invalidators.append(
                {
                    "code": "ERR_EXEC_VERIFY_FAILED",
                    "message": "one or more verification commands failed",
                }
            )

    attempt = attempt_record(
        context,
        attempt_id=attempt_id,
        backend="codex-cli",
        command=command,
        verification=verification,
        started_at=started_at,
        ended_at=ended_at,
        status=attempt_status,
        exit_code=process.returncode,
        stdout_path="stdout.txt",
        stderr_path="stderr.txt",
        worktree_path=rel(wt_path),
    )
    attempt["verification_result"] = verification_result
    attempt["transcript_path"] = "transcript.md"
    brief = render_execution_brief(context, command, verification)
    hashes = {
        "packet_hash": context["packet_hash"],
        "prompt_hash": context["prompt_hash"],
        "attempt_hash": canonical_hash(attempt),
        "prompt_copy_hash": sha256_text(context["prompt"]),
        "execution_brief_hash": sha256_text(brief),
        "verification_hash": canonical_hash(verification),
        "backend_command_hash": canonical_hash(command),
        "stdout_hash": sha256_text(process.stdout),
        "stderr_hash": sha256_text(process.stderr),
        "transcript_hash": sha256_text(transcript_path.read_text()),
        "worktree_status_hash": sha256_text(git_text(["status", "--short"], wt_path)),
        "post_git_status_hash": sha256_text(git_text(["status", "--short"], wt_path)),
        "post_git_diff_summary_hash": sha256_text(
            git_text(["diff", "--stat"], wt_path)
        ),
        **verification_hashes,
    }

    write_json(attempt_dir / "attempt.json", attempt, root=out_dir)
    write_text(attempt_dir / "execution-brief.md", brief, root=out_dir)
    write_text(attempt_dir / "prompt.md", context["prompt"], root=out_dir)
    write_json(attempt_dir / "backend-command.json", command, root=out_dir)
    write_text(attempt_dir / "stdout.txt", process.stdout, root=out_dir)
    write_text(attempt_dir / "stderr.txt", process.stderr, root=out_dir)
    write_text(
        attempt_dir / "git-status.txt",
        git_text(["status", "--short"], wt_path),
        root=out_dir,
    )
    write_text(
        attempt_dir / "git-diff-summary.txt",
        git_text(["diff", "--stat"], wt_path),
        root=out_dir,
    )
    write_json(attempt_dir / "verification.json", verification, root=out_dir)
    write_json(attempt_dir / "hashes.json", hashes, root=out_dir)
    append_attempt_contract(out_dir, attempt, hashes)

    attempts.append(attempt)
    status = build_status(
        run_id,
        v1_run_dir,
        status=attempt_status,
        attempts=attempts,
        invalidators=invalidators,
    )
    write_status(out_dir, status)
    return {
        "status": status,
        "attempt": attempt,
        "out_dir": out_dir,
        "attempt_dir": attempt_dir,
    }


def resume_execution(
    v1_run_dir: Path, *, out_dir: Path | None = None
) -> dict[str, Any]:
    v1_run_dir = resolve_v1_run(v1_run_dir)
    out_dir = (
        resolve_v2_out(out_dir)
        if out_dir is not None
        else V2_OUT_ROOT / v1_run_dir.name
    )
    try:
        context = trust_v1_run(v1_run_dir)
        run_id = context["run"]["run_id"]
        ensure_v2_dir(out_dir, run_id, v1_run_dir)
        attempts = existing_attempts(
            out_dir,
            expected_packet_hash=context["packet_hash"],
            expected_prompt_hash=context["prompt_hash"],
            expected_run_id=run_id,
            expected_v1_run_path=rel(v1_run_dir),
            expected_packet_id=PACKET_ID,
        )
        current = status_from_attempts(attempts)
        invalidators = []
        if attempts:
            invalidators = invalidators_for_attempt(
                out_dir / "attempts" / str(attempts[-1]["attempt_id"]), attempts[-1]
            )
        status = build_status(
            run_id,
            v1_run_dir,
            status=current,
            attempts=attempts,
            invalidators=invalidators,
        )
    except ExecError as exc:
        status = write_blocked_status(v1_run_dir, out_dir, exc)
        return {"status": status, "out_dir": out_dir}
    write_status(out_dir, status)
    return {"status": status, "out_dir": out_dir}


def write_temp_plan(
    base_plan_path: Path,
    fixture: dict[str, Any],
    temp_root: Path,
    *,
    root: Path | None = None,
) -> Path:
    plan = read_json(base_plan_path)
    if fixture.get("mutation"):
        plan = mutate_plan(plan, fixture["mutation"])
    plan_path = temp_root / f"{fixture['id']}.workflow.plan.json"
    if root is None:
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(canonical_json_text(plan) + "\n")
    else:
        write_json(plan_path, plan, root=root)
    return plan_path


def make_source_plan_stale(plan_path: Path, *, root: Path | None = None) -> None:
    plan = read_json(plan_path)
    objective = plan.get("objective")
    plan["objective"] = (
        f"{objective} stale-source-fixture"
        if isinstance(objective, str)
        else "stale-source-fixture"
    )
    if root is None:
        plan_path.write_text(canonical_json_text(plan) + "\n")
    else:
        write_json(plan_path, plan, root=root)


def run_manifest_required_failure_probe(
    fixture_out: Path, *, out_dir: Path
) -> dict[str, Any]:
    required_manifest = {
        "schema_version": SCHEMA_VERSION,
        "suite": "required-failure-probe",
        "fixtures": [
            {
                "id": "intentional-required-failure",
                "type": "dry-run",
                "plan": "fixtures/v1/plans/ready-readonly.workflow.plan.json",
                "required": True,
                "expected_status": "blocked",
            }
        ],
    }
    optional_manifest = {
        "schema_version": SCHEMA_VERSION,
        "suite": "optional-failure-probe",
        "fixtures": [
            {
                "id": "intentional-optional-failure",
                "type": "dry-run",
                "plan": "fixtures/v1/plans/ready-readonly.workflow.plan.json",
                "required": False,
                "expected_status": "blocked",
            }
        ],
    }
    required_manifest_path = fixture_out / "required-nested-manifest.json"
    optional_manifest_path = fixture_out / "optional-nested-manifest.json"
    required_out = fixture_out / "nested-required-failure"
    optional_out = fixture_out / "nested-optional-failure"
    write_json(required_manifest_path, required_manifest, root=out_dir)
    write_json(optional_manifest_path, optional_manifest, root=out_dir)
    required_summary = run_manifest(required_manifest_path, required_out)
    optional_summary = run_manifest(optional_manifest_path, optional_out)
    probe_summary = {
        "required_failure": required_summary,
        "optional_failure": optional_summary,
    }
    write_json(fixture_out / "summary.json", probe_summary, root=out_dir)
    if required_summary["decision"] != "kill" or required_summary["failed"] != 1:
        raise ExecError(
            "ERR_EXEC_MANIFEST_REQUIRED_FAILED",
            "required fixture failure did not kill nested manifest",
        )
    if optional_summary["decision"] != "keep" or optional_summary["failed"] != 1:
        raise ExecError(
            "ERR_EXEC_MANIFEST_REQUIRED_FAILED",
            "optional fixture failure incorrectly killed nested manifest",
        )
    status = {
        "schema_version": SCHEMA_VERSION,
        "adapter_version": ADAPTER_VERSION,
        "run_id": fixture_out.name,
        "v1_run_path": None,
        "status": "pass",
        "attempt_count": 0,
        "latest_attempt_id": None,
        "attempts": [],
        "invalidators": [
            {
                "code": "ERR_EXEC_MANIFEST_REQUIRED_FAILED",
                "message": "required fixture failure kills, optional fixture failure does not",
            }
        ],
        "checked_at": now_utc(),
    }
    write_json(fixture_out / "status.json", status, root=out_dir)
    return {"status": status, "out_dir": fixture_out}


def validate_fixture_id(fixture_id: str) -> None:
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", fixture_id) or fixture_id in {
        ".",
        "..",
    }:
        raise ExecError(
            "ERR_EXEC_OUTSIDE_REPO",
            "fixture ID must be one safe path segment",
            fixture_id=fixture_id,
        )


def validate_manifest_definition(fixtures: list[Any], manifest_path: Path) -> None:
    seen: set[str] = set()
    for fixture in fixtures:
        if not isinstance(fixture, dict):
            raise ExecError(
                "ERR_EXEC_MANIFEST_REQUIRED_FAILED",
                "manifest fixture must be an object",
                path=manifest_path,
            )
        fixture_id = fixture.get("id")
        if not isinstance(fixture_id, str):
            raise ExecError(
                "ERR_EXEC_MANIFEST_REQUIRED_FAILED",
                "fixture id must be a string",
                path=manifest_path,
            )
        validate_fixture_id(fixture_id)
        if fixture_id in seen:
            raise ExecError(
                "ERR_EXEC_MANIFEST_REQUIRED_FAILED",
                "duplicate fixture ID",
                fixture_id=fixture_id,
            )
        seen.add(fixture_id)
        fixture_type = fixture.get("type")
        if (
            not isinstance(fixture_type, str)
            or fixture_type not in ALLOWED_FIXTURE_TYPES
        ):
            raise ExecError(
                "ERR_EXEC_MANIFEST_REQUIRED_FAILED",
                "fixture type is unsupported",
                fixture_id=fixture_id,
            )
        if "required" in fixture and not isinstance(fixture["required"], bool):
            raise ExecError(
                "ERR_EXEC_MANIFEST_REQUIRED_FAILED",
                "fixture required must be a JSON boolean",
                fixture_id=fixture_id,
            )
        if fixture_type != "manifest-required-failure":
            plan = fixture.get("plan")
            if not isinstance(plan, str) or not plan:
                raise ExecError(
                    "ERR_EXEC_MANIFEST_REQUIRED_FAILED",
                    "fixture plan must be a non-empty string",
                    fixture_id=fixture_id,
                )
        if fixture_type == "codex-cli":
            codex_cli = fixture.get("codex_cli")
            if (
                not isinstance(codex_cli, dict)
                or codex_cli.get("mode") != "fixture-command"
            ):
                raise ExecError(
                    "ERR_EXEC_MANIFEST_REQUIRED_FAILED",
                    "codex-cli fixtures must use fixture-command mode",
                    fixture_id=fixture_id,
                )
        if "repeat" in fixture and (
            not isinstance(fixture["repeat"], int) or fixture["repeat"] < 1
        ):
            raise ExecError(
                "ERR_EXEC_MANIFEST_REQUIRED_FAILED",
                "fixture repeat must be a positive integer",
                fixture_id=fixture_id,
            )


def run_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    try:
        manifest = read_json(manifest_path)
    except CompileError as exc:
        raise ExecError(
            "ERR_EXEC_MANIFEST_REQUIRED_FAILED", exc.message, path=exc.path
        ) from exc
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ExecError(
            "ERR_EXEC_MANIFEST_REQUIRED_FAILED",
            "manifest schema_version is missing or unsupported",
            path=manifest_path,
        )
    fixtures = manifest.get("fixtures")
    if not isinstance(fixtures, list):
        raise ExecError(
            "ERR_EXEC_MANIFEST_REQUIRED_FAILED",
            "manifest fixtures must be a list",
            path=manifest_path,
        )
    validate_manifest_definition(fixtures, manifest_path)
    suite_id = out_dir.name
    prepare_manifest_suite(out_dir, suite_id)
    records = []
    passed = 0
    failed = 0
    skipped = 0
    required_passed = 0
    required_total = 0
    temp_root = out_dir / ".fixture-plans"
    for fixture in fixtures:
        fixture_id = fixture["id"]
        if "required" in fixture:
            required = fixture["required"]
        else:
            required = True
        if required:
            required_total += 1
        fixture_out = out_dir / fixture_id
        record: dict[str, Any] = {"id": fixture_id, "required": required}
        try:
            if fixture.get("type") == "manifest-required-failure":
                result = run_manifest_required_failure_probe(
                    fixture_out, out_dir=out_dir
                )
                status = result["status"]
                actual_status = status["status"]
                expected_status = fixture.get("expected_status", "pass")
                actual_codes = [
                    item.get("code") for item in status.get("invalidators", [])
                ]
                if actual_status != expected_status:
                    raise ExecError(
                        "ERR_EXEC_MANIFEST_REQUIRED_FAILED",
                        f"expected status {expected_status}, got {actual_status}",
                        fixture_id=fixture_id,
                    )
                record.update(
                    {
                        "status": "pass",
                        "actual_status": actual_status,
                        "invalidator_codes": actual_codes,
                    }
                )
                passed += 1
                if required:
                    required_passed += 1
                records.append(record)
                continue
            fixture_worktree = fixture.get("worktree")
            if isinstance(fixture_worktree, str):
                fixture_head = git_text(
                    ["rev-parse", "--short=12", "HEAD"], ROOT
                ).strip()
                fixture_worktree = f"{suite_id}-{fixture_head}-{fixture_worktree}"
            cleanup_manifest_worktree_paths(
                str(fixture_worktree) if isinstance(fixture_worktree, str) else None,
                fixture.get("cleanup_worktree_paths"),
            )
            plan_path = write_temp_plan(
                ROOT / fixture["plan"], fixture, temp_root, root=out_dir
            )
            v1_run = V1_OUT_ROOT / f"v2-{suite_id}-{fixture_id}"
            compile_plan(plan_path, v1_run, run_id=f"v2-{suite_id}-{fixture_id}")
            if fixture.get("stale_source_plan"):
                make_source_plan_stale(plan_path, root=out_dir)
            if fixture.get("stale_prompt"):
                prompt_path = v1_run / PROMPT_REL
                prompt_path.write_text(
                    prompt_path.read_text() + "\nV2 stale prompt fixture.\n"
                )
            if fixture.get("dirty_worktree") and fixture_worktree:
                dirty_path = ensure_git_worktree(
                    str(fixture_worktree), require_clean=False
                )
                (dirty_path / f"{fixture_id}.dirty").write_text("dirty\n")
            repeat = fixture.get("repeat", 1)
            result: dict[str, Any] | None = None
            for _ in range(repeat):
                if fixture.get("type") == "local-shell":
                    result = execute_local_shell(
                        v1_run,
                        out_dir=fixture_out,
                        worktree=fixture_worktree,
                        local_shell=fixture.get("local_shell"),
                        verification_commands=fixture.get("verification_commands"),
                    )
                elif fixture.get("type") == "codex-cli":
                    result = execute_codex_cli(
                        v1_run,
                        out_dir=fixture_out,
                        worktree=fixture_worktree,
                        codex_cli=fixture.get("codex_cli"),
                        verification_commands=fixture.get("verification_commands"),
                    )
                else:
                    result = execute_dry_run(v1_run, out_dir=fixture_out)
                if fixture.get("malformed_attempt"):
                    if not result or "attempt_dir" not in result:
                        raise ExecError(
                            "ERR_EXEC_MANIFEST_REQUIRED_FAILED",
                            "malformed attempt fixture did not create an attempt",
                            fixture_id=fixture_id,
                        )
                    (result["attempt_dir"] / "attempt.json").write_text(
                        "{ malformed attempt\n"
                    )
                    result = resume_execution(v1_run, out_dir=fixture_out)
                if fixture.get("resume_after_prepare"):
                    result = resume_execution(v1_run, out_dir=fixture_out)
            if result is None:
                raise ExecError(
                    "ERR_EXEC_MANIFEST_REQUIRED_FAILED",
                    "fixture did not run",
                    fixture_id=fixture_id,
                )
            cleanup_manifest_worktree_paths(
                str(fixture_worktree) if isinstance(fixture_worktree, str) else None,
                fixture.get("cleanup_worktree_paths"),
            )
            status = result["status"] if isinstance(result, dict) else result
            actual_status = status["status"]
            expected_status = fixture.get("expected_status", "prepared")
            expected_error = fixture.get("expected_error")
            expected_attempt_count = fixture.get("expected_attempt_count")
            actual_codes = [item.get("code") for item in status.get("invalidators", [])]
            if actual_status != expected_status:
                raise ExecError(
                    "ERR_EXEC_MANIFEST_REQUIRED_FAILED",
                    f"expected status {expected_status}, got {actual_status}",
                    fixture_id=fixture_id,
                )
            if expected_error and expected_error not in actual_codes:
                raise ExecError(
                    "ERR_EXEC_MANIFEST_REQUIRED_FAILED",
                    f"expected error {expected_error}, got {actual_codes}",
                    fixture_id=fixture_id,
                )
            if actual_status in {"prepared", "executed", "failed"} and not status.get(
                "latest_attempt_id"
            ):
                raise ExecError(
                    "ERR_EXEC_MANIFEST_REQUIRED_FAILED",
                    "prepared fixture did not create an attempt",
                    fixture_id=fixture_id,
                )
            if (
                actual_status == "blocked"
                and status.get("latest_attempt_id") is not None
                and expected_attempt_count is None
            ):
                raise ExecError(
                    "ERR_EXEC_MANIFEST_REQUIRED_FAILED",
                    "blocked fixture created an attempt",
                    fixture_id=fixture_id,
                )
            if (
                expected_attempt_count is not None
                and status.get("attempt_count") != expected_attempt_count
            ):
                raise ExecError(
                    "ERR_EXEC_MANIFEST_REQUIRED_FAILED",
                    f"expected {expected_attempt_count} attempts, got {status.get('attempt_count')}",
                    fixture_id=fixture_id,
                )
            record.update(
                {
                    "status": "pass",
                    "actual_status": actual_status,
                    "invalidator_codes": actual_codes,
                }
            )
            passed += 1
            if required:
                required_passed += 1
        except Exception as exc:  # noqa: BLE001 - manifest records structured failures.
            failed += 1
            record.update({"status": "fail", "error": str(exc)})
        records.append(record)
    decision = "keep" if skipped == 0 and required_passed == required_total else "kill"
    summary = {
        "suite_id": suite_id,
        "fixture_count": len(fixtures),
        "required_fixture_count": required_total,
        "required_passed": required_passed,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "decision": decision,
        "fixtures": records,
    }
    write_json(out_dir / "summary.json", summary, root=out_dir)
    return summary


def validate_v25_manifest_definition(fixtures: list[Any], manifest_path: Path) -> None:
    seen: set[str] = set()
    for fixture in fixtures:
        if not isinstance(fixture, dict):
            raise ExecError(
                "ERR_EXEC_MANIFEST_REQUIRED_FAILED",
                "V2.5 manifest fixture must be an object",
                path=manifest_path,
            )
        fixture_id = fixture.get("id")
        if not isinstance(fixture_id, str):
            raise ExecError(
                "ERR_EXEC_MANIFEST_REQUIRED_FAILED",
                "V2.5 fixture id must be a string",
                path=manifest_path,
            )
        validate_fixture_id(fixture_id)
        if fixture_id in seen:
            raise ExecError(
                "ERR_EXEC_MANIFEST_REQUIRED_FAILED",
                "duplicate V2.5 fixture ID",
                fixture_id=fixture_id,
            )
        seen.add(fixture_id)
        fixture_type = fixture.get("type")
        if (
            not isinstance(fixture_type, str)
            or fixture_type not in ALLOWED_V25_FIXTURE_TYPES
        ):
            raise ExecError(
                "ERR_EXEC_MANIFEST_REQUIRED_FAILED",
                "V2.5 fixture type is unsupported",
                fixture_id=fixture_id,
            )
        if "required" in fixture and not isinstance(fixture["required"], bool):
            raise ExecError(
                "ERR_EXEC_MANIFEST_REQUIRED_FAILED",
                "V2.5 fixture required must be a JSON boolean",
                fixture_id=fixture_id,
            )


def reset_owned_v2_output(path: Path) -> None:
    if not path.exists():
        return
    sentinel = read_sentinel(path)
    if sentinel is None or sentinel.get("tool") != TOOL:
        raise ExecError(
            "ERR_EXEC_UNTRUSTED_V1_RUN",
            "existing V2 output is not adapter-owned",
            path=path,
        )
    shutil.rmtree(path)


def v25_fixture_worktree(
    suite_id: str, fixture_id: str, suffix: str | None = None
) -> str:
    head = git_text(["rev-parse", "--short=12", "HEAD"], ROOT).strip()
    parts = ["v25", suite_id, head, fixture_id]
    if suffix:
        parts.append(suffix)
    return "-".join(parts)


def prepare_v25_fixture_attempt(
    suite_id: str, fixture_id: str, fixture_type: str, fixture_out: Path
) -> tuple[Path, Path, dict[str, Any]]:
    ready_plan = (
        ROOT / "fixtures" / "v1" / "plans" / "ready-readonly.workflow.plan.json"
    )
    run_id = f"v25-{suite_id}-{fixture_id}"
    v1_run = V1_OUT_ROOT / run_id
    v2_run = V2_OUT_ROOT / run_id
    reset_owned_v2_output(v2_run)
    compile_plan(ready_plan, v1_run, run_id=run_id)
    worktree = v25_fixture_worktree(suite_id, fixture_id)
    if fixture_type in {
        "review-approved",
        "review-resume",
        "review-stale-after-new-attempt",
        "review-replacement-after-new-attempt",
    }:
        result = execute_local_shell(
            v1_run,
            out_dir=v2_run,
            worktree=worktree,
            local_shell={
                "argv": ["python", "-c", "print('local shell ok')"],
                "expected_exit_code": 0,
            },
        )
    elif fixture_type in {
        "review-request-changes",
        "review-tamper-invalid",
        "repair-prepared",
        "repair-stale-after-new-review",
    }:
        result = execute_local_shell(
            v1_run,
            out_dir=v2_run,
            worktree=worktree,
            local_shell={
                "argv": ["python", "-c", "import sys; sys.exit(2)"],
                "expected_exit_code": 0,
            },
        )
    elif fixture_type == "repair-no-actionable":
        result = execute_dry_run(v1_run, out_dir=v2_run)
    else:
        raise ExecError(
            "ERR_EXEC_MANIFEST_REQUIRED_FAILED",
            "unsupported V2.5 fixture setup",
            fixture_id=fixture_id,
        )
    write_json(fixture_out / "setup-status.json", result["status"], root=fixture_out)
    return v1_run, v2_run, result


def run_v25_fixture(
    suite_id: str, fixture: dict[str, Any], fixture_out: Path
) -> dict[str, Any]:
    fixture_id = fixture["id"]
    fixture_type = fixture["type"]
    fixture_out.mkdir(parents=True, exist_ok=True)
    v1_run, v2_run, _setup = prepare_v25_fixture_attempt(
        suite_id, fixture_id, fixture_type, fixture_out
    )
    if fixture_type in {"review-approved", "review-request-changes"}:
        result = review_execution(v1_run, out_dir=v2_run)
    elif fixture_type == "review-resume":
        review_execution(v1_run, out_dir=v2_run)
        result = review_resume(v1_run, out_dir=v2_run)
    elif fixture_type == "review-tamper-invalid":
        reviewed = review_execution(v1_run, out_dir=v2_run)
        review_dir = reviewed["review_dir"]
        review_path = review_dir / "review.json"
        hashes_path = review_dir / "hashes.json"
        review = json.loads(review_path.read_text())
        review["summary"] = "Tampered coherent review summary."
        hashes = json.loads(hashes_path.read_text())
        hashes["review_hash"] = canonical_hash(review)
        write_json(review_path, review, root=v2_run)
        write_json(hashes_path, hashes, root=v2_run)
        result = review_resume(v1_run, out_dir=v2_run)
    elif fixture_type == "review-stale-after-new-attempt":
        review_execution(v1_run, out_dir=v2_run)
        execute_local_shell(
            v1_run,
            out_dir=v2_run,
            worktree=v25_fixture_worktree(suite_id, fixture_id, "new-attempt"),
            local_shell={
                "argv": ["python", "-c", "import sys; sys.exit(2)"],
                "expected_exit_code": 0,
            },
        )
        result = review_resume(v1_run, out_dir=v2_run)
    elif fixture_type == "review-replacement-after-new-attempt":
        review_execution(v1_run, out_dir=v2_run)
        execute_local_shell(
            v1_run,
            out_dir=v2_run,
            worktree=v25_fixture_worktree(suite_id, fixture_id, "new-attempt"),
            local_shell={
                "argv": ["python", "-c", "import sys; sys.exit(2)"],
                "expected_exit_code": 0,
            },
        )
        review_execution(v1_run, out_dir=v2_run)
        result = review_resume(v1_run, out_dir=v2_run)
    elif fixture_type == "repair-prepared":
        review_execution(v1_run, out_dir=v2_run)
        result = prepare_repair(v1_run, out_dir=v2_run)
    elif fixture_type == "repair-no-actionable":
        review_execution(v1_run, out_dir=v2_run)
        result = prepare_repair(v1_run, out_dir=v2_run)
    elif fixture_type == "repair-stale-after-new-review":
        review_execution(v1_run, out_dir=v2_run)
        prepare_repair(v1_run, out_dir=v2_run)
        review_execution(v1_run, out_dir=v2_run)
        result = review_resume(v1_run, out_dir=v2_run)
    else:
        raise ExecError(
            "ERR_EXEC_MANIFEST_REQUIRED_FAILED",
            "unsupported V2.5 fixture type",
            fixture_id=fixture_id,
        )
    write_json(fixture_out / "status.json", result["status"], root=fixture_out)
    write_text(fixture_out / "v1-run.txt", rel(v1_run) + "\n", root=fixture_out)
    write_text(fixture_out / "v2-run.txt", rel(v2_run) + "\n", root=fixture_out)
    return result["status"]


def run_v25_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    try:
        manifest = read_json(manifest_path)
    except CompileError as exc:
        raise ExecError(
            "ERR_EXEC_MANIFEST_REQUIRED_FAILED", exc.message, path=exc.path
        ) from exc
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ExecError(
            "ERR_EXEC_MANIFEST_REQUIRED_FAILED",
            "V2.5 manifest schema_version is missing or unsupported",
            path=manifest_path,
        )
    fixtures = manifest.get("fixtures")
    if not isinstance(fixtures, list):
        raise ExecError(
            "ERR_EXEC_MANIFEST_REQUIRED_FAILED",
            "V2.5 manifest fixtures must be a list",
            path=manifest_path,
        )
    validate_v25_manifest_definition(fixtures, manifest_path)
    suite_id = out_dir.name
    prepare_v25_manifest_suite(out_dir, suite_id)
    records = []
    passed = 0
    failed = 0
    skipped = 0
    required_passed = 0
    required_total = 0
    for fixture in fixtures:
        fixture_id = fixture["id"]
        required = fixture.get("required", True)
        if required:
            required_total += 1
        record: dict[str, Any] = {"id": fixture_id, "required": required}
        try:
            status = run_v25_fixture(suite_id, fixture, out_dir / fixture_id)
            actual_status = status["status"]
            expected_status = fixture.get("expected_status")
            expected_error = fixture.get("expected_error")
            actual_codes = [item.get("code") for item in status.get("invalidators", [])]
            if expected_status != actual_status:
                raise ExecError(
                    "ERR_EXEC_MANIFEST_REQUIRED_FAILED",
                    f"expected status {expected_status}, got {actual_status}",
                    fixture_id=fixture_id,
                )
            if expected_error and expected_error not in actual_codes:
                raise ExecError(
                    "ERR_EXEC_MANIFEST_REQUIRED_FAILED",
                    f"expected error {expected_error}, got {actual_codes}",
                    fixture_id=fixture_id,
                )
            record.update(
                {
                    "status": "pass",
                    "actual_status": actual_status,
                    "invalidator_codes": actual_codes,
                }
            )
            passed += 1
            if required:
                required_passed += 1
        except Exception as exc:  # noqa: BLE001 - manifest records structured failures.
            failed += 1
            record.update({"status": "fail", "error": str(exc)})
        records.append(record)
    decision = "keep" if skipped == 0 and required_passed == required_total else "kill"
    summary = {
        "suite_id": suite_id,
        "fixture_count": len(fixtures),
        "required_fixture_count": required_total,
        "required_passed": required_passed,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "decision": decision,
        "fixtures": records,
    }
    write_json(out_dir / "summary.json", summary, root=out_dir)
    return summary


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ExecError("ERR_EXEC_SELF_TEST_FAILED", message)


def self_test() -> None:
    def reset_owned_v2(path: Path) -> None:
        if path.exists():
            sentinel = read_sentinel(path)
            if sentinel and sentinel.get("tool") == TOOL:
                shutil.rmtree(path)

    self_test_head = git_text(["rev-parse", "--short=12", "HEAD"], ROOT).strip()

    def wt(name: str) -> str:
        return f"execute-self-test-v2h-{self_test_head}-{name}"

    for old_self_test in sorted(V2_OUT_ROOT.glob("execute-self-test*")):
        reset_owned_v2(old_self_test)

    ready_plan = (
        ROOT / "fixtures" / "v1" / "plans" / "ready-readonly.workflow.plan.json"
    )
    ready_v1 = V1_OUT_ROOT / "execute-self-test-ready"
    ready_v2 = V2_OUT_ROOT / "execute-self-test-ready"
    result = compile_plan(ready_plan, ready_v1, run_id="execute-self-test-ready")
    require(
        result["status"]["packet_statuses"][0]["status"] == "ready",
        "ready fixture did not compile ready",
    )
    dry = execute_dry_run(ready_v1, out_dir=ready_v2)
    require(dry["status"]["status"] == "prepared", "dry run did not prepare evidence")
    require(
        (ready_v2 / "attempts" / "0000" / "attempt.json").is_file(),
        "dry run did not write first attempt",
    )
    attempt = json.loads((ready_v2 / "attempts" / "0000" / "attempt.json").read_text())
    require(
        attempt["stdout_path"] is None and attempt["transcript_path"] is None,
        "dry run should record missing backend outputs as null",
    )
    require(
        attempt["repo_tracked_diff_unchanged"] is True,
        "dry run should record unchanged tracked diff",
    )
    fixture_argv, _ = local_shell_command(
        {"argv": ["python", "-c", "print('local shell ok')"], "expected_exit_code": 0}
    )
    require(
        Path(fixture_argv[0]).resolve() == Path(sys.executable).resolve(),
        "fixture commands should use trusted Python executable",
    )
    parsed_verification = parse_verification_commands(
        [
            {
                "id": "verify-path",
                "argv": ["python", "-c", "print('verify ok')"],
                "expected_exit_code": 0,
            }
        ]
    )
    require(
        Path(parsed_verification[0]["argv"][0]).resolve()
        == Path(sys.executable).resolve(),
        "verification commands should use trusted Python executable",
    )
    codex_fixture_argv, _, _, _ = parse_codex_cli(
        {
            "mode": "fixture-command",
            "argv": [
                "python",
                "-c",
                "import sys; print('codex ok'); print(len(sys.stdin.read()))",
            ],
            "expected_exit_code": 0,
        },
        attempt_dir=ready_v2 / "codex-parse-only",
        wt_path=ROOT,
    )
    require(
        Path(codex_fixture_argv[0]).resolve() == Path(sys.executable).resolve(),
        "codex fixture commands should use trusted Python executable",
    )

    omx_v1 = V1_OUT_ROOT / "execute-self-test-omx-emit"
    omx_v2 = V2_OUT_ROOT / "execute-self-test-omx-emit"
    compile_plan(ready_plan, omx_v1, run_id="execute-self-test-omx-emit")
    omx = execute_dry_run(
        omx_v1, out_dir=omx_v2, backend="omx", worktree=wt("omx-emit"), emit_only=True
    )
    require(
        omx["status"]["status"] == "prepared", "OMX emit-only should prepare evidence"
    )
    omx_resume = resume_execution(omx_v1, out_dir=omx_v2)
    require(
        omx_resume["status"]["status"] == "prepared",
        "OMX emit-only resume should stay prepared",
    )
    omx_no_emit_v1 = V1_OUT_ROOT / "execute-self-test-omx-no-emit"
    omx_no_emit_v2 = V2_OUT_ROOT / "execute-self-test-omx-no-emit"
    reset_owned_v2(omx_no_emit_v2)
    compile_plan(ready_plan, omx_no_emit_v1, run_id="execute-self-test-omx-no-emit")
    omx_no_emit_cli = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--run",
            str(omx_no_emit_v1),
            "--out",
            str(omx_no_emit_v2),
            "--backend",
            "omx",
            "--worktree",
            wt("omx-no-emit"),
        ],
        cwd=ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    require(omx_no_emit_cli.returncode == 1, "CLI OMX without emit-only should fail")
    require(
        "ERR_EXEC_BACKEND_UNAVAILABLE" in omx_no_emit_cli.stderr,
        "CLI OMX without emit-only wrong refusal",
    )
    omx_no_emit_direct_v2 = V2_OUT_ROOT / "execute-self-test-omx-no-emit-direct"
    reset_owned_v2(omx_no_emit_direct_v2)
    omx_no_emit_direct = execute_dry_run(
        omx_no_emit_v1,
        out_dir=omx_no_emit_direct_v2,
        backend="omx",
        worktree=wt("omx-no-emit-direct"),
        emit_only=False,
    )
    require(
        omx_no_emit_direct["status"]["status"] == "blocked",
        "direct OMX without emit-only should block",
    )
    require(
        omx_no_emit_direct["status"]["invalidators"][0]["code"]
        == "ERR_EXEC_BACKEND_UNAVAILABLE",
        "direct OMX without emit-only wrong refusal",
    )
    require(
        not (omx_no_emit_direct_v2 / "attempts").exists(),
        "direct OMX without emit-only should not create attempts",
    )

    blocked_plan_dir = ready_v2 / ".self-test-plans"
    blocked_plan = write_temp_plan(
        ready_plan,
        {
            "id": "blocked",
            "mutation": {
                "plan_id": "execute-self-test-blocked",
                "surface_write": True,
                "gate_trigger": "write action",
            },
        },
        blocked_plan_dir,
        root=ready_v2,
    )
    blocked_v1 = V1_OUT_ROOT / "execute-self-test-blocked"
    blocked_v2 = V2_OUT_ROOT / "execute-self-test-blocked"
    compile_plan(blocked_plan, blocked_v1, run_id="execute-self-test-blocked")
    blocked = execute_dry_run(blocked_v1, out_dir=blocked_v2)
    require(
        blocked["status"]["status"] == "blocked", "blocked V1 packet should not execute"
    )
    require(
        blocked["status"]["attempt_count"] == 0,
        "blocked V1 packet should not create attempts",
    )
    require(
        blocked["status"]["invalidators"][0]["code"] == "ERR_EXEC_BLOCKED_RISK",
        "blocked packet wrong invalidator",
    )

    stale_v1 = V1_OUT_ROOT / "execute-self-test-stale"
    stale_v2 = V2_OUT_ROOT / "execute-self-test-stale"
    compile_plan(ready_plan, stale_v1, run_id="execute-self-test-stale")
    prompt_path = stale_v1 / PROMPT_REL
    prompt_path.write_text(prompt_path.read_text() + "\nStale prompt.\n")
    stale = execute_dry_run(stale_v1, out_dir=stale_v2)
    require(
        stale["status"]["status"] == "blocked", "stale V1 packet should block execution"
    )
    require(
        stale["status"]["attempt_count"] == 0,
        "stale V1 packet should not create attempts",
    )
    require(
        stale["status"]["invalidators"][0]["code"] == "ERR_EXEC_STALE_PACKET",
        "stale packet wrong invalidator",
    )

    stale_source_plan = write_temp_plan(
        ready_plan,
        {"id": "stale-source"},
        blocked_plan_dir,
        root=ready_v2,
    )
    stale_source_v1 = V1_OUT_ROOT / "execute-self-test-stale-source"
    stale_source_v2 = V2_OUT_ROOT / "execute-self-test-stale-source"
    reset_owned_v2(stale_source_v2)
    compile_plan(
        stale_source_plan, stale_source_v1, run_id="execute-self-test-stale-source"
    )
    make_source_plan_stale(stale_source_plan, root=ready_v2)
    stale_source = execute_dry_run(stale_source_v1, out_dir=stale_source_v2)
    require(
        stale_source["status"]["status"] == "blocked",
        "stale source plan should block execution",
    )
    require(
        stale_source["status"]["attempt_count"] == 0,
        "stale source plan should not create attempts",
    )
    require(
        stale_source["status"]["invalidators"][0]["code"] == "ERR_EXEC_STALE_PACKET",
        "stale source wrong invalidator",
    )

    resumed = resume_execution(ready_v1, out_dir=ready_v2)
    require(
        resumed["status"]["status"] == "prepared",
        "resume should preserve prepared status",
    )

    malformed_v1 = V1_OUT_ROOT / "execute-self-test-malformed-attempt"
    malformed_v2 = V2_OUT_ROOT / "execute-self-test-malformed-attempt"
    reset_owned_v2(malformed_v2)
    compile_plan(ready_plan, malformed_v1, run_id="execute-self-test-malformed-attempt")
    malformed_first = execute_dry_run(malformed_v1, out_dir=malformed_v2)
    (malformed_first["attempt_dir"] / "attempt.json").write_text(
        "{ malformed attempt\n"
    )
    malformed_resume = resume_execution(malformed_v1, out_dir=malformed_v2)
    require(
        malformed_resume["status"]["status"] == "invalid",
        "malformed attempt should produce invalid status",
    )
    require(
        malformed_resume["status"]["invalidators"][0]["code"]
        == "ERR_EXEC_ATTEMPT_MALFORMED",
        "malformed attempt wrong invalidator",
    )

    missing_sidecar_v1 = V1_OUT_ROOT / "execute-self-test-missing-sidecar"
    missing_sidecar_v2 = V2_OUT_ROOT / "execute-self-test-missing-sidecar"
    reset_owned_v2(missing_sidecar_v2)
    compile_plan(
        ready_plan, missing_sidecar_v1, run_id="execute-self-test-missing-sidecar"
    )
    missing_sidecar_first = execute_dry_run(
        missing_sidecar_v1, out_dir=missing_sidecar_v2
    )
    (missing_sidecar_first["attempt_dir"] / "verification.json").unlink()
    missing_sidecar_resume = resume_execution(
        missing_sidecar_v1, out_dir=missing_sidecar_v2
    )
    require(
        missing_sidecar_resume["status"]["status"] == "invalid",
        "missing sidecar should produce invalid status",
    )
    require(
        missing_sidecar_resume["status"]["invalidators"][0]["code"]
        == "ERR_EXEC_ATTEMPT_MALFORMED",
        "missing sidecar wrong invalidator",
    )
    missing_sidecar_rerun = execute_dry_run(
        missing_sidecar_v1, out_dir=missing_sidecar_v2
    )
    require(
        missing_sidecar_rerun["status"]["status"] == "invalid",
        "rerun with missing sidecar should preserve invalid status",
    )
    resume_cli = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--resume",
            str(missing_sidecar_v1),
            "--out",
            str(missing_sidecar_v2),
        ],
        cwd=ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    require(
        resume_cli.returncode == 1,
        "CLI resume should exit nonzero for invalid evidence",
    )

    missing_brief_v1 = V1_OUT_ROOT / "execute-self-test-missing-brief"
    missing_brief_v2 = V2_OUT_ROOT / "execute-self-test-missing-brief"
    compile_plan(ready_plan, missing_brief_v1, run_id="execute-self-test-missing-brief")
    missing_brief_first = execute_dry_run(missing_brief_v1, out_dir=missing_brief_v2)
    (missing_brief_first["attempt_dir"] / "execution-brief.md").unlink()
    missing_brief_resume = resume_execution(missing_brief_v1, out_dir=missing_brief_v2)
    require(
        missing_brief_resume["status"]["status"] == "invalid",
        "missing execution brief should produce invalid status",
    )
    require(
        missing_brief_resume["status"]["invalidators"][0]["code"]
        == "ERR_EXEC_ATTEMPT_MALFORMED",
        "missing execution brief wrong invalidator",
    )

    missing_hash_v1 = V1_OUT_ROOT / "execute-self-test-missing-hash"
    missing_hash_v2 = V2_OUT_ROOT / "execute-self-test-missing-hash"
    reset_owned_v2(missing_hash_v2)
    compile_plan(ready_plan, missing_hash_v1, run_id="execute-self-test-missing-hash")
    missing_hash_first = execute_dry_run(missing_hash_v1, out_dir=missing_hash_v2)
    hashes_path = missing_hash_first["attempt_dir"] / "hashes.json"
    hashes = json.loads(hashes_path.read_text())
    hashes.pop("attempt_hash", None)
    write_json(hashes_path, hashes, root=missing_hash_v2)
    missing_hash_resume = resume_execution(missing_hash_v1, out_dir=missing_hash_v2)
    require(
        missing_hash_resume["status"]["status"] == "invalid",
        "missing hash key should invalidate attempt",
    )
    require(
        missing_hash_resume["status"]["invalidators"][0]["code"]
        == "ERR_EXEC_ATTEMPT_MALFORMED",
        "missing hash key wrong invalidator",
    )

    packet_hash_v1 = V1_OUT_ROOT / "execute-self-test-packet-hash-tamper"
    packet_hash_v2 = V2_OUT_ROOT / "execute-self-test-packet-hash-tamper"
    reset_owned_v2(packet_hash_v2)
    compile_plan(
        ready_plan, packet_hash_v1, run_id="execute-self-test-packet-hash-tamper"
    )
    packet_hash_first = execute_dry_run(packet_hash_v1, out_dir=packet_hash_v2)
    hashes_path = packet_hash_first["attempt_dir"] / "hashes.json"
    hashes = json.loads(hashes_path.read_text())
    hashes["packet_hash"] = "0" * 64
    write_json(hashes_path, hashes, root=packet_hash_v2)
    packet_hash_resume = resume_execution(packet_hash_v1, out_dir=packet_hash_v2)
    require(
        packet_hash_resume["status"]["status"] == "invalid",
        "packet hash tamper should invalidate attempt",
    )
    require(
        packet_hash_resume["status"]["invalidators"][0]["code"]
        == "ERR_EXEC_ATTEMPT_MALFORMED",
        "packet hash tamper wrong invalidator",
    )

    prompt_tamper_v1 = V1_OUT_ROOT / "execute-self-test-prompt-sidecar-tamper"
    prompt_tamper_v2 = V2_OUT_ROOT / "execute-self-test-prompt-sidecar-tamper"
    reset_owned_v2(prompt_tamper_v2)
    compile_plan(
        ready_plan, prompt_tamper_v1, run_id="execute-self-test-prompt-sidecar-tamper"
    )
    prompt_tamper_first = execute_dry_run(prompt_tamper_v1, out_dir=prompt_tamper_v2)
    (prompt_tamper_first["attempt_dir"] / "prompt.md").write_text(
        "tampered prompt sidecar\n"
    )
    prompt_tamper_resume = resume_execution(prompt_tamper_v1, out_dir=prompt_tamper_v2)
    require(
        prompt_tamper_resume["status"]["status"] == "invalid",
        "prompt sidecar tamper should invalidate attempt",
    )
    require(
        prompt_tamper_resume["status"]["invalidators"][0]["code"]
        == "ERR_EXEC_ATTEMPT_MALFORMED",
        "prompt sidecar tamper wrong invalidator",
    )

    run_binding_v1 = V1_OUT_ROOT / "execute-self-test-run-binding-tamper"
    run_binding_v2 = V2_OUT_ROOT / "execute-self-test-run-binding-tamper"
    reset_owned_v2(run_binding_v2)
    compile_plan(
        ready_plan, run_binding_v1, run_id="execute-self-test-run-binding-tamper"
    )
    run_binding_first = execute_dry_run(run_binding_v1, out_dir=run_binding_v2)
    attempt_path = run_binding_first["attempt_dir"] / "attempt.json"
    hashes_path = run_binding_first["attempt_dir"] / "hashes.json"
    attempt = json.loads(attempt_path.read_text())
    attempt["run_id"] = "forged-run"
    attempt["v1_run_path"] = "out/v1/forged-run"
    attempt["packet_id"] = "001-forged"
    hashes = json.loads(hashes_path.read_text())
    hashes["attempt_hash"] = canonical_hash(attempt)
    write_json(attempt_path, attempt, root=run_binding_v2)
    write_json(hashes_path, hashes, root=run_binding_v2)
    run_binding_resume = resume_execution(run_binding_v1, out_dir=run_binding_v2)
    require(
        run_binding_resume["status"]["status"] == "invalid",
        "run-binding tamper should invalidate attempt",
    )
    require(
        run_binding_resume["status"]["invalidators"][0]["code"]
        == "ERR_EXEC_ATTEMPT_MALFORMED",
        "run-binding tamper wrong invalidator",
    )

    command_mismatch_v1 = V1_OUT_ROOT / "execute-self-test-command-mismatch"
    command_mismatch_v2 = V2_OUT_ROOT / "execute-self-test-command-mismatch"
    reset_owned_v2(command_mismatch_v2)
    compile_plan(
        ready_plan, command_mismatch_v1, run_id="execute-self-test-command-mismatch"
    )
    command_mismatch_first = execute_dry_run(
        command_mismatch_v1, out_dir=command_mismatch_v2
    )
    attempt_path = command_mismatch_first["attempt_dir"] / "attempt.json"
    hashes_path = command_mismatch_first["attempt_dir"] / "hashes.json"
    attempt = json.loads(attempt_path.read_text())
    attempt["command"]["description"] = "forged command"
    hashes = json.loads(hashes_path.read_text())
    hashes["attempt_hash"] = canonical_hash(attempt)
    write_json(attempt_path, attempt, root=command_mismatch_v2)
    write_json(hashes_path, hashes, root=command_mismatch_v2)
    command_mismatch_resume = resume_execution(
        command_mismatch_v1, out_dir=command_mismatch_v2
    )
    require(
        command_mismatch_resume["status"]["status"] == "invalid",
        "attempt command mismatch should invalidate evidence",
    )
    require(
        command_mismatch_resume["status"]["invalidators"][0]["code"]
        == "ERR_EXEC_ATTEMPT_MALFORMED",
        "attempt command mismatch wrong invalidator",
    )

    verification_mismatch_v1 = V1_OUT_ROOT / "execute-self-test-verification-mismatch"
    verification_mismatch_v2 = V2_OUT_ROOT / "execute-self-test-verification-mismatch"
    reset_owned_v2(verification_mismatch_v2)
    compile_plan(
        ready_plan,
        verification_mismatch_v1,
        run_id="execute-self-test-verification-mismatch",
    )
    verification_mismatch_first = execute_dry_run(
        verification_mismatch_v1, out_dir=verification_mismatch_v2
    )
    attempt_path = verification_mismatch_first["attempt_dir"] / "attempt.json"
    hashes_path = verification_mismatch_first["attempt_dir"] / "hashes.json"
    attempt = json.loads(attempt_path.read_text())
    attempt["verification"][0]["result"] = "pass"
    hashes = json.loads(hashes_path.read_text())
    hashes["attempt_hash"] = canonical_hash(attempt)
    write_json(attempt_path, attempt, root=verification_mismatch_v2)
    write_json(hashes_path, hashes, root=verification_mismatch_v2)
    verification_mismatch_resume = resume_execution(
        verification_mismatch_v1, out_dir=verification_mismatch_v2
    )
    require(
        verification_mismatch_resume["status"]["status"] == "invalid",
        "attempt verification mismatch should invalidate evidence",
    )
    require(
        verification_mismatch_resume["status"]["invalidators"][0]["code"]
        == "ERR_EXEC_ATTEMPT_MALFORMED",
        "attempt verification mismatch wrong invalidator",
    )

    tracked_state_mismatch_v1 = V1_OUT_ROOT / "execute-self-test-tracked-state-mismatch"
    tracked_state_mismatch_v2 = V2_OUT_ROOT / "execute-self-test-tracked-state-mismatch"
    reset_owned_v2(tracked_state_mismatch_v2)
    compile_plan(
        ready_plan,
        tracked_state_mismatch_v1,
        run_id="execute-self-test-tracked-state-mismatch",
    )
    tracked_state_mismatch_first = execute_dry_run(
        tracked_state_mismatch_v1, out_dir=tracked_state_mismatch_v2
    )
    attempt_path = tracked_state_mismatch_first["attempt_dir"] / "attempt.json"
    hashes_path = tracked_state_mismatch_first["attempt_dir"] / "hashes.json"
    attempt = json.loads(attempt_path.read_text())
    attempt["repo_tracked_diff_unchanged"] = not attempt["repo_tracked_diff_unchanged"]
    hashes = json.loads(hashes_path.read_text())
    hashes["attempt_hash"] = canonical_hash(attempt)
    write_json(attempt_path, attempt, root=tracked_state_mismatch_v2)
    write_json(hashes_path, hashes, root=tracked_state_mismatch_v2)
    tracked_state_mismatch_resume = resume_execution(
        tracked_state_mismatch_v1, out_dir=tracked_state_mismatch_v2
    )
    require(
        tracked_state_mismatch_resume["status"]["status"] == "invalid",
        "tracked-state mismatch should invalidate evidence",
    )
    require(
        tracked_state_mismatch_resume["status"]["invalidators"][0]["code"]
        == "ERR_EXEC_ATTEMPT_MALFORMED",
        "tracked-state mismatch wrong invalidator",
    )

    missing_tracked_state_v1 = V1_OUT_ROOT / "execute-self-test-missing-tracked-state"
    missing_tracked_state_v2 = V2_OUT_ROOT / "execute-self-test-missing-tracked-state"
    reset_owned_v2(missing_tracked_state_v2)
    compile_plan(
        ready_plan,
        missing_tracked_state_v1,
        run_id="execute-self-test-missing-tracked-state",
    )
    missing_tracked_state_first = execute_dry_run(
        missing_tracked_state_v1, out_dir=missing_tracked_state_v2
    )
    attempt_path = missing_tracked_state_first["attempt_dir"] / "attempt.json"
    hashes_path = missing_tracked_state_first["attempt_dir"] / "hashes.json"
    attempt = json.loads(attempt_path.read_text())
    attempt["pre_tracked_state_path"] = None
    attempt["post_tracked_state_path"] = None
    hashes = json.loads(hashes_path.read_text())
    hashes.pop("pre_tracked_state_hash", None)
    hashes.pop("post_tracked_state_hash", None)
    hashes["attempt_hash"] = canonical_hash(attempt)
    write_json(attempt_path, attempt, root=missing_tracked_state_v2)
    write_json(hashes_path, hashes, root=missing_tracked_state_v2)
    missing_tracked_state_resume = resume_execution(
        missing_tracked_state_v1, out_dir=missing_tracked_state_v2
    )
    require(
        missing_tracked_state_resume["status"]["status"] == "invalid",
        "missing tracked-state evidence should invalidate resume",
    )
    require(
        missing_tracked_state_resume["status"]["invalidators"][0]["code"]
        == "ERR_EXEC_ATTEMPT_MALFORMED",
        "missing tracked-state wrong invalidator",
    )

    malformed_precedence_v1 = V1_OUT_ROOT / "execute-self-test-malformed-precedence"
    malformed_precedence_v2 = V2_OUT_ROOT / "execute-self-test-malformed-precedence"
    reset_owned_v2(malformed_precedence_v2)
    compile_plan(
        ready_plan,
        malformed_precedence_v1,
        run_id="execute-self-test-malformed-precedence",
    )
    malformed_precedence = execute_dry_run(
        malformed_precedence_v1, out_dir=malformed_precedence_v2
    )
    (malformed_precedence["attempt_dir"] / "attempt.json").write_text(
        "{ malformed attempt\n"
    )
    malformed_precedence_result = execute_local_shell(
        malformed_precedence_v1,
        out_dir=malformed_precedence_v2,
        worktree=None,
        local_shell={
            "argv": ["python", "-c", "print('local shell ok')"],
            "expected_exit_code": 0,
        },
    )
    require(
        malformed_precedence_result["status"]["status"] == "invalid",
        "malformed evidence should beat worktree blockers",
    )
    require(
        malformed_precedence_result["status"]["invalidators"][0]["code"]
        == "ERR_EXEC_ATTEMPT_MALFORMED",
        "malformed precedence wrong invalidator",
    )

    escaped_tracked_state_v1 = V1_OUT_ROOT / "execute-self-test-escaped-tracked-state"
    escaped_tracked_state_v2 = V2_OUT_ROOT / "execute-self-test-escaped-tracked-state"
    reset_owned_v2(escaped_tracked_state_v2)
    compile_plan(
        ready_plan,
        escaped_tracked_state_v1,
        run_id="execute-self-test-escaped-tracked-state",
    )
    escaped_tracked_state_first = execute_dry_run(
        escaped_tracked_state_v1, out_dir=escaped_tracked_state_v2
    )
    attempt_path = escaped_tracked_state_first["attempt_dir"] / "attempt.json"
    hashes_path = escaped_tracked_state_first["attempt_dir"] / "hashes.json"
    attempt = json.loads(attempt_path.read_text())
    attempt["pre_tracked_state_path"] = "../attempt.json"
    hashes = json.loads(hashes_path.read_text())
    hashes["attempt_hash"] = canonical_hash(attempt)
    write_json(attempt_path, attempt, root=escaped_tracked_state_v2)
    write_json(hashes_path, hashes, root=escaped_tracked_state_v2)
    escaped_tracked_state_resume = resume_execution(
        escaped_tracked_state_v1, out_dir=escaped_tracked_state_v2
    )
    require(
        escaped_tracked_state_resume["status"]["status"] == "invalid",
        "escaped tracked-state path should invalidate resume",
    )
    require(
        escaped_tracked_state_resume["status"]["invalidators"][0]["code"]
        == "ERR_EXEC_ATTEMPT_MALFORMED",
        "escaped tracked-state wrong invalidator",
    )

    symlink_attempt_v1 = V1_OUT_ROOT / "execute-self-test-symlink-attempt"
    symlink_attempt_v2 = V2_OUT_ROOT / "execute-self-test-symlink-attempt"
    reset_owned_v2(symlink_attempt_v2)
    compile_plan(
        ready_plan, symlink_attempt_v1, run_id="execute-self-test-symlink-attempt"
    )
    symlink_first = execute_dry_run(symlink_attempt_v1, out_dir=symlink_attempt_v2)
    moved_attempt = symlink_attempt_v2 / "external-attempt"
    if moved_attempt.exists():
        shutil.rmtree(moved_attempt)
    shutil.move(str(symlink_first["attempt_dir"]), moved_attempt)
    (symlink_attempt_v2 / "attempts" / "0000").symlink_to(
        moved_attempt, target_is_directory=True
    )
    symlink_resume = resume_execution(symlink_attempt_v1, out_dir=symlink_attempt_v2)
    require(
        symlink_resume["status"]["status"] == "invalid",
        "symlinked attempt directory should produce invalid status",
    )
    require(
        symlink_resume["status"]["invalidators"][0]["code"]
        == "ERR_EXEC_ATTEMPT_MALFORMED",
        "symlinked attempt wrong invalidator",
    )

    renamed_attempt_v1 = V1_OUT_ROOT / "execute-self-test-renamed-attempt"
    renamed_attempt_v2 = V2_OUT_ROOT / "execute-self-test-renamed-attempt"
    reset_owned_v2(renamed_attempt_v2)
    compile_plan(
        ready_plan, renamed_attempt_v1, run_id="execute-self-test-renamed-attempt"
    )
    renamed_first = execute_dry_run(renamed_attempt_v1, out_dir=renamed_attempt_v2)
    shutil.move(
        str(renamed_first["attempt_dir"]), renamed_attempt_v2 / "attempts" / "old-0000"
    )
    renamed_resume = resume_execution(renamed_attempt_v1, out_dir=renamed_attempt_v2)
    require(
        renamed_resume["status"]["status"] == "invalid",
        "renamed attempt directory should invalidate evidence",
    )
    require(
        renamed_resume["status"]["invalidators"][0]["code"]
        == "ERR_EXEC_ATTEMPT_MALFORMED",
        "renamed attempt wrong invalidator",
    )

    dangerous_v1 = V1_OUT_ROOT / "execute-self-test-dangerous-command"
    dangerous_v2 = V2_OUT_ROOT / "execute-self-test-dangerous-command"
    reset_owned_v2(dangerous_v2)
    compile_plan(ready_plan, dangerous_v1, run_id="execute-self-test-dangerous-command")
    dangerous = execute_local_shell(
        dangerous_v1,
        out_dir=dangerous_v2,
        worktree=None,
        local_shell={"argv": ["git", "push"], "expected_exit_code": 0},
    )
    require(
        dangerous["status"]["status"] == "blocked",
        "dangerous fixture command should be blocked",
    )
    require(
        dangerous["status"]["invalidators"][0]["code"]
        == "ERR_EXEC_BACKEND_UNAVAILABLE",
        "dangerous command wrong invalidator",
    )

    bypass_v1 = V1_OUT_ROOT / "execute-self-test-command-bypass"
    bypass_v2 = V2_OUT_ROOT / "execute-self-test-command-bypass"
    reset_owned_v2(bypass_v2)
    compile_plan(ready_plan, bypass_v1, run_id="execute-self-test-command-bypass")
    bypass = execute_local_shell(
        bypass_v1,
        out_dir=bypass_v2,
        worktree=None,
        local_shell={
            "argv": ["python", "-c", "import os; print(os.getcwd())"],
            "expected_exit_code": 0,
        },
    )
    require(
        bypass["status"]["status"] == "blocked",
        "unapproved python fixture snippet should be blocked",
    )
    require(
        bypass["status"]["invalidators"][0]["code"] == "ERR_EXEC_BACKEND_UNAVAILABLE",
        "python bypass wrong invalidator",
    )

    path_bypass_v1 = V1_OUT_ROOT / "execute-self-test-command-path-bypass"
    path_bypass_v2 = V2_OUT_ROOT / "execute-self-test-command-path-bypass"
    reset_owned_v2(path_bypass_v2)
    compile_plan(
        ready_plan, path_bypass_v1, run_id="execute-self-test-command-path-bypass"
    )
    path_bypass = execute_local_shell(
        path_bypass_v1,
        out_dir=path_bypass_v2,
        worktree=None,
        local_shell={
            "argv": ["./python", "-c", "print('local shell ok')"],
            "expected_exit_code": 0,
        },
    )
    require(
        path_bypass["status"]["status"] == "blocked",
        "relative python fixture executable should be blocked",
    )
    require(
        path_bypass["status"]["invalidators"][0]["code"]
        == "ERR_EXEC_BACKEND_UNAVAILABLE",
        "relative python bypass wrong invalidator",
    )

    dangerous_verification_v1 = V1_OUT_ROOT / "execute-self-test-dangerous-verification"
    dangerous_verification_v2 = V2_OUT_ROOT / "execute-self-test-dangerous-verification"
    reset_owned_v2(dangerous_verification_v2)
    compile_plan(
        ready_plan,
        dangerous_verification_v1,
        run_id="execute-self-test-dangerous-verification",
    )
    dangerous_verification = execute_local_shell(
        dangerous_verification_v1,
        out_dir=dangerous_verification_v2,
        worktree=wt("dangerous-verification"),
        local_shell={
            "argv": ["python", "-c", "print('backend ready')"],
            "expected_exit_code": 0,
        },
        verification_commands=[
            {"id": "verify-danger", "argv": ["git", "push"], "expected_exit_code": 0}
        ],
    )
    require(
        dangerous_verification["status"]["status"] == "blocked",
        "dangerous verification command should be blocked",
    )
    require(
        dangerous_verification["status"]["invalidators"][0]["code"]
        == "ERR_EXEC_BACKEND_UNAVAILABLE",
        "dangerous verification wrong invalidator",
    )

    foreign_name = wt("foreign-worktree")
    foreign_path = worktree_path(foreign_name)
    if foreign_path.exists():
        shutil.rmtree(foreign_path)
    foreign_path.mkdir(parents=True)
    subprocess.run(
        ["git", "init"],
        cwd=foreign_path,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    foreign_v1 = V1_OUT_ROOT / "execute-self-test-foreign-worktree"
    foreign_v2 = V2_OUT_ROOT / "execute-self-test-foreign-worktree"
    reset_owned_v2(foreign_v2)
    compile_plan(ready_plan, foreign_v1, run_id="execute-self-test-foreign-worktree")
    foreign = execute_local_shell(
        foreign_v1,
        out_dir=foreign_v2,
        worktree=foreign_name,
        local_shell={
            "argv": ["python", "-c", "print('wrong repo')"],
            "expected_exit_code": 0,
        },
    )
    require(
        foreign["status"]["status"] == "blocked", "foreign worktree should be blocked"
    )
    require(
        foreign["status"]["invalidators"][0]["code"] == "ERR_EXEC_WORKTREE_REQUIRED",
        "foreign worktree wrong invalidator",
    )

    local_v1 = V1_OUT_ROOT / "execute-self-test-local-shell"
    local_v2 = V2_OUT_ROOT / "execute-self-test-local-shell"
    compile_plan(ready_plan, local_v1, run_id="execute-self-test-local-shell")
    local = execute_local_shell(
        local_v1,
        out_dir=local_v2,
        worktree=wt("local-shell"),
        local_shell={
            "argv": ["python", "-c", "print('local shell ok')"],
            "expected_exit_code": 0,
        },
    )
    require(
        local["status"]["status"] == "executed",
        "local-shell success should be executed",
    )
    require(
        (local_v2 / "attempts" / "0000" / "stdout.txt").read_text()
        == "local shell ok\n",
        "local-shell stdout not captured",
    )

    backend_identity_v1 = V1_OUT_ROOT / "execute-self-test-backend-identity"
    backend_identity_v2 = V2_OUT_ROOT / "execute-self-test-backend-identity"
    reset_owned_v2(backend_identity_v2)
    compile_plan(
        ready_plan, backend_identity_v1, run_id="execute-self-test-backend-identity"
    )
    backend_identity = execute_local_shell(
        backend_identity_v1,
        out_dir=backend_identity_v2,
        worktree=wt("backend-identity"),
        local_shell={
            "argv": ["python", "-c", "print('local shell ok')"],
            "expected_exit_code": 0,
        },
    )
    attempt_path = backend_identity["attempt_dir"] / "attempt.json"
    hashes_path = backend_identity["attempt_dir"] / "hashes.json"
    attempt = json.loads(attempt_path.read_text())
    attempt["backend"] = "dry-run"
    hashes = json.loads(hashes_path.read_text())
    hashes["attempt_hash"] = canonical_hash(attempt)
    write_json(attempt_path, attempt, root=backend_identity_v2)
    write_json(hashes_path, hashes, root=backend_identity_v2)
    backend_identity_resume = resume_execution(
        backend_identity_v1, out_dir=backend_identity_v2
    )
    require(
        backend_identity_resume["status"]["status"] == "invalid",
        "backend identity tamper should invalidate resume",
    )
    require(
        backend_identity_resume["status"]["invalidators"][0]["code"]
        == "ERR_EXEC_ATTEMPT_MALFORMED",
        "backend identity wrong invalidator",
    )

    missing_backend_output_v1 = V1_OUT_ROOT / "execute-self-test-missing-backend-output"
    missing_backend_output_v2 = V2_OUT_ROOT / "execute-self-test-missing-backend-output"
    reset_owned_v2(missing_backend_output_v2)
    compile_plan(
        ready_plan,
        missing_backend_output_v1,
        run_id="execute-self-test-missing-backend-output",
    )
    missing_backend_output = execute_local_shell(
        missing_backend_output_v1,
        out_dir=missing_backend_output_v2,
        worktree=wt("missing-backend-output"),
        local_shell={
            "argv": ["python", "-c", "print('local shell ok')"],
            "expected_exit_code": 0,
        },
    )
    attempt_path = missing_backend_output["attempt_dir"] / "attempt.json"
    hashes_path = missing_backend_output["attempt_dir"] / "hashes.json"
    attempt = json.loads(attempt_path.read_text())
    attempt["stdout_path"] = None
    attempt["stderr_path"] = None
    hashes = json.loads(hashes_path.read_text())
    hashes.pop("stdout_hash", None)
    hashes.pop("stderr_hash", None)
    hashes["attempt_hash"] = canonical_hash(attempt)
    write_json(attempt_path, attempt, root=missing_backend_output_v2)
    write_json(hashes_path, hashes, root=missing_backend_output_v2)
    missing_backend_output_resume = resume_execution(
        missing_backend_output_v1, out_dir=missing_backend_output_v2
    )
    require(
        missing_backend_output_resume["status"]["status"] == "invalid",
        "missing backend output evidence should invalidate resume",
    )
    require(
        missing_backend_output_resume["status"]["invalidators"][0]["code"]
        == "ERR_EXEC_ATTEMPT_MALFORMED",
        "missing backend output wrong invalidator",
    )

    cli_local_v1 = V1_OUT_ROOT / "execute-self-test-cli-local-shell-blocked"
    cli_local_v2 = V2_OUT_ROOT / "execute-self-test-cli-local-shell-blocked"
    reset_owned_v2(cli_local_v2)
    compile_plan(
        ready_plan, cli_local_v1, run_id="execute-self-test-cli-local-shell-blocked"
    )
    cli_local = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--run",
            str(cli_local_v1),
            "--out",
            str(cli_local_v2),
            "--backend",
            "local-shell",
            "--worktree",
            wt("cli-local-shell-blocked"),
        ],
        cwd=ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    require(
        cli_local.returncode == 1, "CLI local-shell should be fixture-manifest only"
    )
    require(
        "ERR_EXEC_BACKEND_UNAVAILABLE" in cli_local.stderr,
        "CLI local-shell wrong refusal",
    )

    untrusted_manifest_path = ready_v2 / "untrusted-manifest.json"
    write_json(
        untrusted_manifest_path,
        {
            "schema_version": SCHEMA_VERSION,
            "fixtures": [
                {
                    "id": "untrusted-local-shell",
                    "type": "local-shell",
                    "plan": "fixtures/v1/plans/ready-readonly.workflow.plan.json",
                    "local_shell": {
                        "argv": ["python", "-c", "print('local shell ok')"],
                        "expected_exit_code": 0,
                    },
                }
            ],
        },
        root=ready_v2,
    )
    untrusted_manifest_cli = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--manifest",
            str(untrusted_manifest_path),
            "--out",
            "out/v2/execute-self-test-untrusted-manifest",
        ],
        cwd=ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    require(
        untrusted_manifest_cli.returncode == 1,
        "CLI should reject untrusted manifest paths",
    )
    require(
        "public --manifest is limited" in untrusted_manifest_cli.stderr,
        "untrusted manifest wrong refusal",
    )

    wrong_schema_manifest_path = ready_v2 / "wrong-schema-manifest.json"
    wrong_schema_out = V2_OUT_ROOT / "execute-self-test-wrong-schema-manifest"
    reset_owned_v2(wrong_schema_out)
    write_json(
        wrong_schema_manifest_path,
        {
            "schema_version": "0.0",
            "fixtures": [
                {
                    "id": "wrong-schema",
                    "type": "dry-run",
                    "plan": "fixtures/v1/plans/ready-readonly.workflow.plan.json",
                }
            ],
        },
        root=ready_v2,
    )
    try:
        run_manifest(wrong_schema_manifest_path, wrong_schema_out)
    except ExecError as exc:
        require(
            exc.code == "ERR_EXEC_MANIFEST_REQUIRED_FAILED",
            "wrong schema_version wrong invalidator",
        )
    else:
        raise ExecError(
            "ERR_EXEC_SELF_TEST_FAILED",
            "wrong schema_version should fail manifest parsing",
        )

    missing_schema_manifest_path = ready_v2 / "missing-schema-manifest.json"
    missing_schema_out = V2_OUT_ROOT / "execute-self-test-missing-schema-manifest"
    reset_owned_v2(missing_schema_out)
    write_json(
        missing_schema_manifest_path,
        {
            "fixtures": [
                {
                    "id": "missing-schema",
                    "type": "dry-run",
                    "plan": "fixtures/v1/plans/ready-readonly.workflow.plan.json",
                }
            ],
        },
        root=ready_v2,
    )
    try:
        run_manifest(missing_schema_manifest_path, missing_schema_out)
    except ExecError as exc:
        require(
            exc.code == "ERR_EXEC_MANIFEST_REQUIRED_FAILED",
            "missing schema_version wrong invalidator",
        )
    else:
        raise ExecError(
            "ERR_EXEC_SELF_TEST_FAILED",
            "missing schema_version should fail manifest parsing",
        )

    nonbool_required_manifest_path = ready_v2 / "nonbool-required-manifest.json"
    nonbool_required_out = V2_OUT_ROOT / "execute-self-test-nonbool-required"
    reset_owned_v2(nonbool_required_out)
    write_json(
        nonbool_required_manifest_path,
        {
            "schema_version": SCHEMA_VERSION,
            "fixtures": [
                {
                    "id": "nonbool-required",
                    "type": "dry-run",
                    "plan": "fixtures/v1/plans/ready-readonly.workflow.plan.json",
                    "required": "false",
                }
            ],
        },
        root=ready_v2,
    )
    try:
        run_manifest(nonbool_required_manifest_path, nonbool_required_out)
    except ExecError as exc:
        require(
            exc.code == "ERR_EXEC_MANIFEST_REQUIRED_FAILED",
            "non-boolean required wrong invalidator",
        )
    else:
        raise ExecError(
            "ERR_EXEC_SELF_TEST_FAILED",
            "non-boolean required should fail manifest parsing",
        )

    duplicate_fixture_manifest_path = ready_v2 / "duplicate-fixture-manifest.json"
    duplicate_fixture_out = V2_OUT_ROOT / "execute-self-test-duplicate-fixture"
    reset_owned_v2(duplicate_fixture_out)
    write_json(
        duplicate_fixture_manifest_path,
        {
            "schema_version": SCHEMA_VERSION,
            "fixtures": [
                {
                    "id": "duplicate-fixture",
                    "type": "dry-run",
                    "plan": "fixtures/v1/plans/ready-readonly.workflow.plan.json",
                },
                {
                    "id": "duplicate-fixture",
                    "type": "dry-run",
                    "plan": "fixtures/v1/plans/ready-readonly.workflow.plan.json",
                },
            ],
        },
        root=ready_v2,
    )
    try:
        run_manifest(duplicate_fixture_manifest_path, duplicate_fixture_out)
    except ExecError as exc:
        require(
            exc.code == "ERR_EXEC_MANIFEST_REQUIRED_FAILED",
            "duplicate fixture wrong invalidator",
        )
    else:
        raise ExecError(
            "ERR_EXEC_SELF_TEST_FAILED",
            "duplicate fixture ID should fail manifest parsing",
        )

    malformed_optional_manifest_path = ready_v2 / "malformed-optional-manifest.json"
    malformed_optional_out = V2_OUT_ROOT / "execute-self-test-malformed-optional"
    reset_owned_v2(malformed_optional_out)
    write_json(
        malformed_optional_manifest_path,
        {
            "schema_version": SCHEMA_VERSION,
            "fixtures": [
                {
                    "id": "malformed-optional",
                    "type": "dry-run",
                    "required": False,
                }
            ],
        },
        root=ready_v2,
    )
    try:
        run_manifest(malformed_optional_manifest_path, malformed_optional_out)
    except ExecError as exc:
        require(
            exc.code == "ERR_EXEC_MANIFEST_REQUIRED_FAILED",
            "malformed optional wrong invalidator",
        )
    else:
        raise ExecError(
            "ERR_EXEC_SELF_TEST_FAILED",
            "malformed optional fixture should fail manifest parsing",
        )

    codex_installed_manifest_path = ready_v2 / "codex-installed-manifest.json"
    codex_installed_out = V2_OUT_ROOT / "execute-self-test-codex-installed-manifest"
    reset_owned_v2(codex_installed_out)
    write_json(
        codex_installed_manifest_path,
        {
            "schema_version": SCHEMA_VERSION,
            "fixtures": [
                {
                    "id": "codex-installed",
                    "type": "codex-cli",
                    "plan": "fixtures/v1/plans/ready-readonly.workflow.plan.json",
                    "codex_cli": {"mode": "installed-codex"},
                    "worktree": "codex-installed",
                }
            ],
        },
        root=ready_v2,
    )
    try:
        run_manifest(codex_installed_manifest_path, codex_installed_out)
    except ExecError as exc:
        require(
            exc.code == "ERR_EXEC_MANIFEST_REQUIRED_FAILED",
            "codex installed manifest wrong invalidator",
        )
    else:
        raise ExecError(
            "ERR_EXEC_SELF_TEST_FAILED",
            "codex-cli manifest fixtures should require fixture-command mode",
        )

    failed_v1 = V1_OUT_ROOT / "execute-self-test-local-shell-failed"
    failed_v2 = V2_OUT_ROOT / "execute-self-test-local-shell-failed"
    compile_plan(ready_plan, failed_v1, run_id="execute-self-test-local-shell-failed")
    failed = execute_local_shell(
        failed_v1,
        out_dir=failed_v2,
        worktree=wt("local-shell-failed"),
        local_shell={
            "argv": ["python", "-c", "import sys; sys.exit(2)"],
            "expected_exit_code": 0,
        },
    )
    require(
        failed["status"]["status"] == "failed", "local-shell failure should be failed"
    )
    require(
        failed["status"]["invalidators"][0]["code"] == "ERR_EXEC_BACKEND_FAILED",
        "local-shell failure wrong invalidator",
    )
    failed_resume_cli = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--resume",
            str(failed_v1),
            "--out",
            str(failed_v2),
        ],
        cwd=ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    require(
        failed_resume_cli.returncode == 1,
        "CLI resume should exit nonzero for failed attempts",
    )
    failed_attempt_dir = failed["attempt_dir"]
    failed_attempt_path = failed_attempt_dir / "attempt.json"
    failed_command_path = failed_attempt_dir / "backend-command.json"
    failed_hashes_path = failed_attempt_dir / "hashes.json"
    failed_attempt = json.loads(failed_attempt_path.read_text())
    failed_command = json.loads(failed_command_path.read_text())
    failed_command["expected_exit_code"] = 2
    failed_attempt["command"] = failed_command
    failed_attempt["status"] = "executed"
    failed_hashes = json.loads(failed_hashes_path.read_text())
    failed_hashes["backend_command_hash"] = canonical_hash(failed_command)
    failed_hashes["attempt_hash"] = canonical_hash(failed_attempt)
    write_json(failed_command_path, failed_command, root=failed_v2)
    write_json(failed_attempt_path, failed_attempt, root=failed_v2)
    write_json(failed_hashes_path, failed_hashes, root=failed_v2)
    failed_contract_tamper = resume_execution(failed_v1, out_dir=failed_v2)
    require(
        failed_contract_tamper["status"]["status"] == "invalid",
        "coherent command tamper should invalidate resume",
    )
    require(
        failed_contract_tamper["status"]["invalidators"][0]["code"]
        == "ERR_EXEC_ATTEMPT_MALFORMED",
        "coherent command tamper wrong invalidator",
    )

    verification_inject_v1 = V1_OUT_ROOT / "execute-self-test-verification-inject"
    verification_inject_v2 = V2_OUT_ROOT / "execute-self-test-verification-inject"
    reset_owned_v2(verification_inject_v2)
    compile_plan(
        ready_plan,
        verification_inject_v1,
        run_id="execute-self-test-verification-inject",
    )
    verification_inject = execute_local_shell(
        verification_inject_v1,
        out_dir=verification_inject_v2,
        worktree=wt("verification-inject"),
        local_shell={
            "argv": ["python", "-c", "print('backend ready')"],
            "expected_exit_code": 0,
        },
    )
    inject_attempt_dir = verification_inject["attempt_dir"]
    inject_attempt_path = inject_attempt_dir / "attempt.json"
    inject_verification_path = inject_attempt_dir / "verification.json"
    inject_hashes_path = inject_attempt_dir / "hashes.json"
    write_text(
        inject_attempt_dir / "injected.stdout.txt",
        "injected\n",
        root=verification_inject_v2,
    )
    write_text(
        inject_attempt_dir / "injected.stderr.txt", "", root=verification_inject_v2
    )
    injected_state = {"git_status": "", "git_diff": ""}
    write_json(
        inject_attempt_dir / "injected.checked-state.json",
        injected_state,
        root=verification_inject_v2,
    )
    injected_hash = canonical_hash(injected_state)
    injected_record = {
        "check_id": "injected",
        "claim_or_output": "injected verification",
        "falsifier": "injected",
        "mode": "automatic",
        "argv": [sys.executable, "-c", "print('verify ok')"],
        "expected_exit_code": 0,
        "stdout_path": "injected.stdout.txt",
        "stderr_path": "injected.stderr.txt",
        "checked_state_path": "injected.checked-state.json",
        "exit_code": 0,
        "checked_hash": injected_hash,
        "result": "pass",
    }
    injected_verification = json.loads(inject_verification_path.read_text())
    injected_verification.append(injected_record)
    injected_attempt = json.loads(inject_attempt_path.read_text())
    injected_attempt["verification"] = injected_verification
    injected_attempt["status"] = "verified"
    injected_attempt["verification_result"] = "pass"
    injected_hashes = json.loads(inject_hashes_path.read_text())
    injected_hashes["verification_hash"] = canonical_hash(injected_verification)
    injected_hashes["attempt_hash"] = canonical_hash(injected_attempt)
    injected_hashes["injected.stdout_hash"] = sha256_text("injected\n")
    injected_hashes["injected.stderr_hash"] = sha256_text("")
    injected_hashes["injected.checked_hash"] = injected_hash
    write_json(
        inject_verification_path, injected_verification, root=verification_inject_v2
    )
    write_json(inject_attempt_path, injected_attempt, root=verification_inject_v2)
    write_json(inject_hashes_path, injected_hashes, root=verification_inject_v2)
    verification_inject_resume = resume_execution(
        verification_inject_v1, out_dir=verification_inject_v2
    )
    require(
        verification_inject_resume["status"]["status"] == "invalid",
        "coherent verification injection should invalidate resume",
    )
    require(
        verification_inject_resume["status"]["invalidators"][0]["code"]
        == "ERR_EXEC_ATTEMPT_MALFORMED",
        "coherent verification injection wrong invalidator",
    )

    output_sidecar_tamper_v1 = V1_OUT_ROOT / "execute-self-test-output-sidecar-tamper"
    output_sidecar_tamper_v2 = V2_OUT_ROOT / "execute-self-test-output-sidecar-tamper"
    reset_owned_v2(output_sidecar_tamper_v2)
    compile_plan(
        ready_plan,
        output_sidecar_tamper_v1,
        run_id="execute-self-test-output-sidecar-tamper",
    )
    output_sidecar_tamper = execute_local_shell(
        output_sidecar_tamper_v1,
        out_dir=output_sidecar_tamper_v2,
        worktree=wt("output-sidecar-tamper"),
        local_shell={
            "argv": ["python", "-c", "print('local shell ok')"],
            "expected_exit_code": 0,
        },
    )
    output_attempt_dir = output_sidecar_tamper["attempt_dir"]
    output_hashes_path = output_attempt_dir / "hashes.json"
    write_text(
        output_attempt_dir / "stdout.txt",
        "forged stdout\n",
        root=output_sidecar_tamper_v2,
    )
    output_hashes = json.loads(output_hashes_path.read_text())
    output_hashes["stdout_hash"] = sha256_text("forged stdout\n")
    write_json(output_hashes_path, output_hashes, root=output_sidecar_tamper_v2)
    output_sidecar_tamper_resume = resume_execution(
        output_sidecar_tamper_v1, out_dir=output_sidecar_tamper_v2
    )
    require(
        output_sidecar_tamper_resume["status"]["status"] == "invalid",
        "coherent output sidecar tamper should invalidate resume",
    )
    require(
        output_sidecar_tamper_resume["status"]["invalidators"][0]["code"]
        == "ERR_EXEC_ATTEMPT_MALFORMED",
        "coherent output sidecar tamper wrong invalidator",
    )

    verified_v1 = V1_OUT_ROOT / "execute-self-test-verified"
    verified_v2 = V2_OUT_ROOT / "execute-self-test-verified"
    compile_plan(ready_plan, verified_v1, run_id="execute-self-test-verified")
    verified = execute_local_shell(
        verified_v1,
        out_dir=verified_v2,
        worktree=wt("verified"),
        local_shell={
            "argv": ["python", "-c", "print('backend ready')"],
            "expected_exit_code": 0,
        },
        verification_commands=[
            {
                "id": "verify-pass",
                "argv": ["python", "-c", "print('verify ok')"],
                "expected_exit_code": 0,
            }
        ],
    )
    require(
        verified["status"]["status"] == "verified",
        "passing verification should produce verified status",
    )
    resumed_verified = resume_execution(verified_v1, out_dir=verified_v2)
    require(
        resumed_verified["status"]["status"] == "verified",
        "resume should preserve verified status",
    )
    verification = json.loads(
        (verified_v2 / "attempts" / "0000" / "verification.json").read_text()
    )
    require(
        any(
            item["mode"] == "automatic" and item["result"] == "pass"
            for item in verification
        ),
        "automatic pass verification not recorded",
    )
    automatic_record = next(
        item for item in verification if item.get("mode") == "automatic"
    )
    require(
        (
            verified_v2 / "attempts" / "0000" / automatic_record["checked_state_path"]
        ).is_file(),
        "automatic verification checked state not captured",
    )
    verification[0]["result"] = "fail"
    write_json(
        verified_v2 / "attempts" / "0000" / "verification.json",
        verification,
        root=verified_v2,
    )
    tampered_verification_resume = resume_execution(verified_v1, out_dir=verified_v2)
    require(
        tampered_verification_resume["status"]["status"] == "invalid",
        "verification sidecar tamper should invalidate attempt",
    )
    require(
        tampered_verification_resume["status"]["invalidators"][0]["code"]
        == "ERR_EXEC_ATTEMPT_MALFORMED",
        "verification sidecar tamper wrong invalidator",
    )

    missing_auto_output_v1 = V1_OUT_ROOT / "execute-self-test-missing-auto-output"
    missing_auto_output_v2 = V2_OUT_ROOT / "execute-self-test-missing-auto-output"
    reset_owned_v2(missing_auto_output_v2)
    compile_plan(
        ready_plan,
        missing_auto_output_v1,
        run_id="execute-self-test-missing-auto-output",
    )
    missing_auto_output = execute_local_shell(
        missing_auto_output_v1,
        out_dir=missing_auto_output_v2,
        worktree=wt("missing-auto-output"),
        local_shell={
            "argv": ["python", "-c", "print('backend ready')"],
            "expected_exit_code": 0,
        },
        verification_commands=[
            {
                "id": "verify-pass",
                "argv": ["python", "-c", "print('verify ok')"],
                "expected_exit_code": 0,
            }
        ],
    )
    attempt_path = missing_auto_output["attempt_dir"] / "attempt.json"
    verification_path = missing_auto_output["attempt_dir"] / "verification.json"
    hashes_path = missing_auto_output["attempt_dir"] / "hashes.json"
    verification = json.loads(verification_path.read_text())
    for item in verification:
        if item.get("mode") == "automatic":
            item["stdout_path"] = None
            item["stderr_path"] = None
    attempt = json.loads(attempt_path.read_text())
    attempt["verification"] = verification
    hashes = json.loads(hashes_path.read_text())
    hashes.pop("verify-pass.stdout_hash", None)
    hashes.pop("verify-pass.stderr_hash", None)
    hashes["verification_hash"] = canonical_hash(verification)
    hashes["attempt_hash"] = canonical_hash(attempt)
    write_json(verification_path, verification, root=missing_auto_output_v2)
    write_json(attempt_path, attempt, root=missing_auto_output_v2)
    write_json(hashes_path, hashes, root=missing_auto_output_v2)
    missing_auto_output_resume = resume_execution(
        missing_auto_output_v1, out_dir=missing_auto_output_v2
    )
    require(
        missing_auto_output_resume["status"]["status"] == "invalid",
        "missing automatic verification output should invalidate resume",
    )
    require(
        missing_auto_output_resume["status"]["invalidators"][0]["code"]
        == "ERR_EXEC_ATTEMPT_MALFORMED",
        "missing automatic output wrong invalidator",
    )

    verify_failed_v1 = V1_OUT_ROOT / "execute-self-test-verify-failed"
    verify_failed_v2 = V2_OUT_ROOT / "execute-self-test-verify-failed"
    compile_plan(ready_plan, verify_failed_v1, run_id="execute-self-test-verify-failed")
    verify_failed = execute_local_shell(
        verify_failed_v1,
        out_dir=verify_failed_v2,
        worktree=wt("verify-failed"),
        local_shell={
            "argv": ["python", "-c", "print('backend ready')"],
            "expected_exit_code": 0,
        },
        verification_commands=[
            {
                "id": "verify-fail",
                "argv": ["python", "-c", "import sys; sys.exit(7)"],
                "expected_exit_code": 0,
            }
        ],
    )
    require(
        verify_failed["status"]["status"] == "failed",
        "failing verification should produce failed status",
    )
    require(
        verify_failed["status"]["invalidators"][0]["code"] == "ERR_EXEC_VERIFY_FAILED",
        "verification failure wrong invalidator",
    )
    tampered_attempt_path = verify_failed_v2 / "attempts" / "0000" / "attempt.json"
    tampered_attempt = json.loads(tampered_attempt_path.read_text())
    tampered_attempt["status"] = "verified"
    tampered_attempt["verification_result"] = "pass"
    write_json(tampered_attempt_path, tampered_attempt, root=verify_failed_v2)
    tampered_resume = resume_execution(verify_failed_v1, out_dir=verify_failed_v2)
    require(
        tampered_resume["status"]["status"] == "invalid",
        "resume should reject tampered attempt status upgrade",
    )
    require(
        tampered_resume["status"]["invalidators"][0]["code"]
        == "ERR_EXEC_ATTEMPT_MALFORMED",
        "tampered status wrong invalidator",
    )

    codex_v1 = V1_OUT_ROOT / "execute-self-test-codex-cli"
    codex_v2 = V2_OUT_ROOT / "execute-self-test-codex-cli"
    compile_plan(ready_plan, codex_v1, run_id="execute-self-test-codex-cli")
    codex = execute_codex_cli(
        codex_v1,
        out_dir=codex_v2,
        worktree=wt("codex-cli"),
        codex_cli={
            "mode": "fixture-command",
            "argv": [
                "python",
                "-c",
                "import sys; print('codex ok'); print(len(sys.stdin.read()))",
            ],
            "expected_exit_code": 0,
        },
    )
    require(
        codex["status"]["status"] == "executed",
        "codex fixture success should be executed",
    )
    require(
        (codex_v2 / "attempts" / "0000" / "transcript.md").is_file(),
        "codex fixture transcript not recorded",
    )

    codex_worktree_v1 = V1_OUT_ROOT / "execute-self-test-codex-worktree-required"
    codex_worktree_v2 = V2_OUT_ROOT / "execute-self-test-codex-worktree-required"
    reset_owned_v2(codex_worktree_v2)
    compile_plan(
        ready_plan,
        codex_worktree_v1,
        run_id="execute-self-test-codex-worktree-required",
    )
    codex_worktree = execute_codex_cli(
        codex_worktree_v1,
        out_dir=codex_worktree_v2,
        worktree=None,
        codex_cli={
            "mode": "fixture-command",
            "argv": ["python", "-c", "print('should not run')"],
            "expected_exit_code": 0,
        },
    )
    require(
        codex_worktree["status"]["status"] == "blocked",
        "codex missing worktree should block",
    )
    require(
        codex_worktree["status"]["invalidators"][0]["code"]
        == "ERR_EXEC_WORKTREE_REQUIRED",
        "codex missing worktree wrong invalidator",
    )

    codex_auth_v1 = V1_OUT_ROOT / "execute-self-test-codex-auth"
    codex_auth_v2 = V2_OUT_ROOT / "execute-self-test-codex-auth"
    compile_plan(ready_plan, codex_auth_v1, run_id="execute-self-test-codex-auth")
    codex_auth = execute_codex_cli(
        codex_auth_v1,
        out_dir=codex_auth_v2,
        worktree=wt("codex-auth"),
        codex_cli={
            "mode": "fixture-command",
            "argv": [
                "python",
                "-c",
                "import sys; print('Invalid authentication credentials', file=sys.stderr); sys.exit(1)",
            ],
            "expected_exit_code": 0,
        },
    )
    require(
        codex_auth["status"]["status"] == "blocked",
        "codex auth fixture should be blocked",
    )
    require(
        codex_auth["status"]["invalidators"][0]["code"] == "ERR_EXEC_BACKEND_AUTH",
        "codex auth wrong invalidator",
    )

    review_ok_v1 = V1_OUT_ROOT / "execute-self-test-review-approved"
    review_ok_v2 = V2_OUT_ROOT / "execute-self-test-review-approved"
    reset_owned_v2(review_ok_v2)
    compile_plan(ready_plan, review_ok_v1, run_id="execute-self-test-review-approved")
    execute_local_shell(
        review_ok_v1,
        out_dir=review_ok_v2,
        worktree=wt("review-approved"),
        local_shell={
            "argv": ["python", "-c", "print('local shell ok')"],
            "expected_exit_code": 0,
        },
    )
    reviewed_ok = review_execution(review_ok_v1, out_dir=review_ok_v2)
    require(
        reviewed_ok["status"]["status"] == "review-approved",
        "executed attempt should review-approved",
    )
    reviewed_ok_resume = review_resume(review_ok_v1, out_dir=review_ok_v2)
    require(
        reviewed_ok_resume["status"]["status"] == "review-approved",
        "review resume should preserve approval",
    )

    review_fail_v1 = V1_OUT_ROOT / "execute-self-test-review-request-changes"
    review_fail_v2 = V2_OUT_ROOT / "execute-self-test-review-request-changes"
    reset_owned_v2(review_fail_v2)
    compile_plan(
        ready_plan, review_fail_v1, run_id="execute-self-test-review-request-changes"
    )
    execute_local_shell(
        review_fail_v1,
        out_dir=review_fail_v2,
        worktree=wt("review-request-changes"),
        local_shell={
            "argv": ["python", "-c", "import sys; sys.exit(2)"],
            "expected_exit_code": 0,
        },
    )
    reviewed_fail = review_execution(review_fail_v1, out_dir=review_fail_v2)
    require(
        reviewed_fail["status"]["status"] == "changes-requested",
        "failed attempt should request changes",
    )
    repair_prepared = prepare_repair(review_fail_v1, out_dir=review_fail_v2)
    require(
        repair_prepared["status"]["status"] == "repair-prepared",
        "request changes should prepare repair",
    )
    newer_review = review_execution(review_fail_v1, out_dir=review_fail_v2)
    require(
        newer_review["status"]["status"] == "changes-requested",
        "new review should not preserve stale repair-prepared status",
    )
    stale_repair_resume = review_resume(review_fail_v1, out_dir=review_fail_v2)
    require(
        stale_repair_resume["status"]["status"] == "invalid",
        "new review should stale existing repair",
    )
    require(
        stale_repair_resume["status"]["invalidators"][0]["code"]
        == "ERR_REPAIR_ARTIFACT_MALFORMED",
        "stale repair wrong invalidator",
    )

    review_tamper_v1 = V1_OUT_ROOT / "execute-self-test-review-tamper"
    review_tamper_v2 = V2_OUT_ROOT / "execute-self-test-review-tamper"
    reset_owned_v2(review_tamper_v2)
    compile_plan(ready_plan, review_tamper_v1, run_id="execute-self-test-review-tamper")
    execute_local_shell(
        review_tamper_v1,
        out_dir=review_tamper_v2,
        worktree=wt("review-tamper"),
        local_shell={
            "argv": ["python", "-c", "import sys; sys.exit(2)"],
            "expected_exit_code": 0,
        },
    )
    tamper_reviewed = review_execution(review_tamper_v1, out_dir=review_tamper_v2)
    tamper_review_path = tamper_reviewed["review_dir"] / "review.json"
    tamper_hashes_path = tamper_reviewed["review_dir"] / "hashes.json"
    tamper_review = json.loads(tamper_review_path.read_text())
    tamper_review["summary"] = "Coherently tampered review."
    tamper_hashes = json.loads(tamper_hashes_path.read_text())
    tamper_hashes["review_hash"] = canonical_hash(tamper_review)
    write_json(tamper_review_path, tamper_review, root=review_tamper_v2)
    write_json(tamper_hashes_path, tamper_hashes, root=review_tamper_v2)
    tampered_review_resume = review_resume(review_tamper_v1, out_dir=review_tamper_v2)
    require(
        tampered_review_resume["status"]["status"] == "invalid",
        "coherent review tamper should invalidate resume",
    )
    require(
        tampered_review_resume["status"]["invalidators"][0]["code"]
        == "ERR_REVIEW_ARTIFACT_MALFORMED",
        "coherent review tamper wrong invalidator",
    )

    stale_review_v1 = V1_OUT_ROOT / "execute-self-test-stale-review"
    stale_review_v2 = V2_OUT_ROOT / "execute-self-test-stale-review"
    reset_owned_v2(stale_review_v2)
    compile_plan(ready_plan, stale_review_v1, run_id="execute-self-test-stale-review")
    execute_local_shell(
        stale_review_v1,
        out_dir=stale_review_v2,
        worktree=wt("stale-review-first"),
        local_shell={
            "argv": ["python", "-c", "print('local shell ok')"],
            "expected_exit_code": 0,
        },
    )
    review_execution(stale_review_v1, out_dir=stale_review_v2)
    execute_local_shell(
        stale_review_v1,
        out_dir=stale_review_v2,
        worktree=wt("stale-review-second"),
        local_shell={
            "argv": ["python", "-c", "import sys; sys.exit(2)"],
            "expected_exit_code": 0,
        },
    )
    stale_review_resume = review_resume(stale_review_v1, out_dir=stale_review_v2)
    require(
        stale_review_resume["status"]["status"] == "invalid",
        "new attempt should stale existing review",
    )
    require(
        stale_review_resume["status"]["invalidators"][0]["code"]
        == "ERR_REVIEW_ARTIFACT_MALFORMED",
        "stale review wrong invalidator",
    )
    replacement_review = review_execution(stale_review_v1, out_dir=stale_review_v2)
    require(
        replacement_review["status"]["status"] == "changes-requested",
        "replacement review after new attempt should append",
    )
    require(
        replacement_review["status"]["review_count"] == 2,
        "replacement review should preserve append-only review history",
    )
    replacement_resume = review_resume(stale_review_v1, out_dir=stale_review_v2)
    require(
        replacement_resume["status"]["status"] == "changes-requested",
        "replacement review should restore clean resume",
    )
    require(
        replacement_resume["status"]["review_count"] == 2,
        "replacement resume should preserve review history",
    )

    print("execute_packet self-test: pass")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", help="V1 run directory under out/v1")
    parser.add_argument(
        "--resume", help="resume-check V2 evidence for a V1 run directory"
    )
    parser.add_argument(
        "--review", help="write V2.5 review artifacts for a V1 run directory"
    )
    parser.add_argument(
        "--review-resume",
        help="resume-check V2.5 review and repair evidence for a V1 run directory",
    )
    parser.add_argument(
        "--repair", help="prepare one V2.5 repair prompt for a V1 run directory"
    )
    parser.add_argument("--manifest", help="V2 fixture manifest")
    parser.add_argument("--out", help="V2 output directory")
    parser.add_argument("--mode", choices=["dry-run"], default="dry-run")
    parser.add_argument(
        "--backend",
        choices=["dry-run", "local-shell", "codex-cli", "omx"],
        default="dry-run",
    )
    parser.add_argument("--worktree")
    parser.add_argument("--emit-only", action="store_true")
    parser.add_argument(
        "--timeout-seconds", type=int, help="backend process timeout for live backends"
    )
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if args.self_test:
            self_test()
            return 0
        if args.manifest:
            if not args.out:
                raise ExecError(
                    "ERR_EXEC_MANIFEST_REQUIRED_FAILED", "--manifest requires --out"
                )
            manifest_path = resolve_public_manifest(args.manifest)
            if manifest_path.resolve(strict=False) == TRUSTED_V25_MANIFEST.resolve(
                strict=False
            ):
                summary = run_v25_manifest(manifest_path, resolve_v25_out(args.out))
            else:
                summary = run_manifest(manifest_path, resolve_v2_out(args.out))
            print(
                canonical_json_text(
                    {key: value for key, value in summary.items() if key != "fixtures"}
                )
            )
            return 0 if summary["decision"] == "keep" else 1
        if args.review:
            result = review_execution(
                Path(args.review), out_dir=Path(args.out) if args.out else None
            )
            print(canonical_json_text(result["status"]))
            return (
                0
                if result["status"]["status"]
                in {"review-approved", "changes-requested", "needs-human"}
                else 1
            )
        if args.review_resume:
            result = review_resume(
                Path(args.review_resume), out_dir=Path(args.out) if args.out else None
            )
            print(canonical_json_text(result["status"]))
            return (
                0
                if result["status"]["status"]
                in {
                    "review-approved",
                    "changes-requested",
                    "needs-human",
                    "repair-prepared",
                }
                else 1
            )
        if args.repair:
            result = prepare_repair(
                Path(args.repair), out_dir=Path(args.out) if args.out else None
            )
            print(canonical_json_text(result["status"]))
            return (
                0
                if result["status"]["status"] in {"repair-prepared", "needs-human"}
                else 1
            )
        if args.resume:
            result = resume_execution(
                Path(args.resume), out_dir=Path(args.out) if args.out else None
            )
            print(canonical_json_text(result["status"]))
            return (
                0
                if result["status"]["status"] in {"prepared", "executed", "verified"}
                else 1
            )
        if args.run:
            backend = args.backend if args.backend != "dry-run" else args.mode
            if backend == "local-shell":
                raise ExecError(
                    "ERR_EXEC_BACKEND_UNAVAILABLE",
                    "--backend local-shell is fixture-manifest only in V2",
                )
            elif backend == "codex-cli":
                codex_config = (
                    {"timeout_seconds": args.timeout_seconds}
                    if args.timeout_seconds is not None
                    else None
                )
                result = execute_codex_cli(
                    Path(args.run),
                    out_dir=Path(args.out) if args.out else None,
                    worktree=args.worktree,
                    codex_cli=codex_config,
                )
            else:
                if backend == "omx" and not args.emit_only:
                    raise ExecError(
                        "ERR_EXEC_BACKEND_UNAVAILABLE",
                        "--backend omx requires --emit-only in V2",
                    )
                result = execute_dry_run(
                    Path(args.run),
                    out_dir=Path(args.out) if args.out else None,
                    backend=backend,
                    worktree=args.worktree,
                    emit_only=args.emit_only,
                )
            print(canonical_json_text(result["status"]))
            return (
                0
                if result["status"]["status"] in {"prepared", "executed", "verified"}
                else 1
            )
        raise ExecError(
            "ERR_EXEC_MANIFEST_REQUIRED_FAILED",
            "expected --run, --resume, --manifest, or --self-test",
        )
    except ExecError as exc:
        print(canonical_json_text(exc.to_record()), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
