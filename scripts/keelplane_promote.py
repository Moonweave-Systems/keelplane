#!/usr/bin/env python3
"""Keelplane output promotion stage."""

from __future__ import annotations

import argparse
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
    canonical_hash,
    read_json,
    sha256_bytes,
    write_json_atomic,
    write_text_atomic,
)
from execute_packet import git_text  # noqa: E402
from keelplane_loop import (  # noqa: E402
    JOURNAL,
    SCHEMA_VERSION as LOOP_SCHEMA_VERSION,
    SENTINEL as LOOP_SENTINEL,
    STATUS,
    verify_journal_chain,
)


TOOL = "keelplane_promote.py"
SCHEMA_VERSION = "keelplane-promote-v1"
OUT_ROOT = ROOT / "out" / "keelplane-promote"
LOOP_OUT_DIRNAME = Path("out") / "keelplane-loop"
PROMOTION = "promotion.json"
PATCH_FILE = "bounded-target.patch"
SENTINEL = ".keelplane-promote-owned.json"
DEFAULT_MAIN_REF = "main"


class PromoteError(ValueError):
    """Structured Keelplane promotion failure."""

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


def reject_traversal(path: Path, *, code: str) -> None:
    if any(part == ".." for part in path.parts):
        raise PromoteError(code, "path must not contain parent traversal", path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise PromoteError(code, "path contains a symlink", path=current)


def resolve_repo(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_KEELPLANE_PROMOTE_REPO_UNSAFE")
    repo = raw if raw.is_absolute() else ROOT / raw
    check_components_not_symlink(repo, code="ERR_KEELPLANE_PROMOTE_PATH_SYMLINK")
    resolved = repo.resolve(strict=False)
    if not (resolved / ".git").exists():
        completed = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=resolved,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if completed.returncode != 0:
            raise PromoteError("ERR_KEELPLANE_PROMOTE_REPO_UNSAFE", "repo must be a git repository", path=value)
        resolved = Path(completed.stdout.strip()).resolve(strict=False)
    return resolved


def resolve_run_dir(value: str | Path, *, repo_root: Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_KEELPLANE_PROMOTE_RUN_UNSAFE")
    candidate = raw if raw.is_absolute() else repo_root / raw
    check_components_not_symlink(candidate, code="ERR_KEELPLANE_PROMOTE_PATH_SYMLINK")
    resolved = candidate.resolve(strict=False)
    expected_root = (repo_root / LOOP_OUT_DIRNAME).resolve(strict=False)
    try:
        resolved.relative_to(expected_root)
    except ValueError as exc:
        raise PromoteError("ERR_KEELPLANE_PROMOTE_NOT_OWNED", f"run must resolve under {expected_root}", path=value) from exc
    if resolved == expected_root:
        raise PromoteError("ERR_KEELPLANE_PROMOTE_NOT_OWNED", "run must name a loop output directory", path=value)
    return resolved


def resolve_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_KEELPLANE_PROMOTE_OUT_UNSAFE")
    candidate = raw if raw.is_absolute() else ROOT / raw
    check_components_not_symlink(candidate, code="ERR_KEELPLANE_PROMOTE_PATH_SYMLINK")
    resolved = candidate.resolve(strict=False)
    root = OUT_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise PromoteError("ERR_KEELPLANE_PROMOTE_OUT_UNSAFE", f"output must resolve under {root}", path=value) from exc
    if resolved == root:
        raise PromoteError("ERR_KEELPLANE_PROMOTE_OUT_UNSAFE", "output must name a suite directory", path=value)
    return resolved


def prepare_out_dir(path: Path, suite_id: str) -> None:
    if path.exists():
        if path.is_symlink() or not path.is_dir():
            raise PromoteError("ERR_KEELPLANE_PROMOTE_OUT_UNSAFE", "output exists and is not a directory", path=path)
        sentinel = path / SENTINEL
        if not sentinel.is_file() or sentinel.is_symlink():
            raise PromoteError("ERR_KEELPLANE_PROMOTE_OUT_UNSAFE", "existing output is not promote-owned", path=path)
        shutil.rmtree(path)
    path.mkdir(parents=True)
    write_json_atomic(path / SENTINEL, {"tool": TOOL, "schema_version": SCHEMA_VERSION, "suite_id": suite_id, "created_at": now_utc()}, root=path)


def safe_target_path(value: str) -> str:
    path = Path(value)
    if path.is_absolute() or not value:
        raise PromoteError("ERR_KEELPLANE_PROMOTE_TARGET_UNSAFE", "target file must be repo-relative", path=value)
    reject_traversal(path, code="ERR_KEELPLANE_PROMOTE_TARGET_UNSAFE")
    if path in {Path("."), Path("..")}:
        raise PromoteError("ERR_KEELPLANE_PROMOTE_TARGET_UNSAFE", "target file must name a file", path=value)
    return path.as_posix()


def git(args: list[str], cwd: Path) -> str:
    try:
        return git_text(args, cwd).strip()
    except Exception as exc:  # noqa: BLE001 - normalize shared git failures to this stage.
        raise PromoteError("ERR_KEELPLANE_PROMOTE_GIT", str(exc), path=cwd) from exc


def git_bytes(args: list[str], cwd: Path) -> bytes:
    completed = subprocess.run(["git", *args], cwd=cwd, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip() or f"git {' '.join(args)} failed"
        raise PromoteError("ERR_KEELPLANE_PROMOTE_GIT", detail, path=cwd)
    return completed.stdout


def git_optional_bytes(args: list[str], cwd: Path) -> bytes | None:
    completed = subprocess.run(["git", *args], cwd=cwd, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if completed.returncode != 0:
        return None
    return completed.stdout


def git_apply_index(repo_root: Path, patch_path: Path) -> None:
    completed = subprocess.run(
        ["git", "apply", "--index", "--binary", str(patch_path)],
        cwd=repo_root,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "bounded patch did not apply"
        raise PromoteError("ERR_KEELPLANE_PROMOTE_CONFLICT", f"bounded patch did not apply cleanly onto current main; rebase required: {detail}", path=repo_root)


def verify_status_hash(status: dict[str, Any]) -> None:
    recorded = status.get("status_hash")
    if not isinstance(recorded, str) or not recorded:
        raise PromoteError("ERR_KEELPLANE_PROMOTE_STATUS_INVALID", "status_hash is missing")
    body = {key: value for key, value in status.items() if key != "status_hash"}
    if canonical_hash(body) != recorded:
        raise PromoteError("ERR_KEELPLANE_PROMOTE_STATUS_INVALID", "status_hash does not match status body")


def load_verified_run(run_dir: Path) -> dict[str, Any]:
    journal_path = run_dir / JOURNAL
    status_path = run_dir / STATUS
    if not journal_path.is_file() or journal_path.is_symlink():
        raise PromoteError("ERR_KEELPLANE_PROMOTE_NOT_OWNED", "journal is missing", path=journal_path)
    if not status_path.is_file() or status_path.is_symlink():
        raise PromoteError("ERR_KEELPLANE_PROMOTE_NOT_OWNED", "status is missing", path=status_path)
    journal = read_json(journal_path)
    status = read_json(status_path)
    if journal.get("schema_version") != LOOP_SCHEMA_VERSION:
        raise PromoteError("ERR_KEELPLANE_PROMOTE_NOT_OWNED", "journal was not produced by keelplane_loop", path=journal_path)
    try:
        verify_journal_chain(journal)
    except Exception as exc:  # noqa: BLE001 - convert shared spine validation to stage code.
        raise PromoteError("ERR_KEELPLANE_PROMOTE_NOT_OWNED", f"journal evidence chain is invalid: {exc}", path=journal_path) from exc
    verify_status_hash(status)
    if status.get("terminal_state") != "verified-complete":
        raise PromoteError("ERR_KEELPLANE_PROMOTE_NOT_VERIFIED", "run is not verified-complete", path=status_path)
    if status.get("evidence_chain_head") != journal.get("chain_head"):
        raise PromoteError("ERR_KEELPLANE_PROMOTE_STATUS_INVALID", "status evidence head does not match journal")
    run_base = journal.get("run_base")
    last_checkpoint = journal.get("last_checkpoint")
    if not isinstance(run_base, str) or not run_base:
        raise PromoteError("ERR_KEELPLANE_PROMOTE_RUN_BASE_MISSING", "journal run_base is missing", path=journal_path)
    if not isinstance(last_checkpoint, str) or not last_checkpoint:
        raise PromoteError("ERR_KEELPLANE_PROMOTE_CHECKPOINT_MISSING", "journal last_checkpoint is missing", path=journal_path)
    target_values = journal.get("target_files")
    if not isinstance(target_values, list) or not target_values:
        raise PromoteError("ERR_KEELPLANE_PROMOTE_TARGETS_MISSING", "journal target_files is missing", path=journal_path)
    target_files = sorted({safe_target_path(value) for value in target_values if isinstance(value, str)})
    if len(target_files) != len(target_values):
        raise PromoteError("ERR_KEELPLANE_PROMOTE_TARGETS_MISSING", "journal target_files must be non-empty strings", path=journal_path)
    return {
        "journal": journal,
        "status": status,
        "run_base": run_base,
        "last_checkpoint": last_checkpoint,
        "target_files": target_files,
        "owned_by_sentinel": (run_dir / LOOP_SENTINEL).is_file(),
    }


def changed_paths(repo_root: Path, base: str, head: str) -> list[str]:
    output = git(["diff", "--name-only", base, head], repo_root)
    return sorted(path for path in output.splitlines() if path)


def bounded_patch(repo_root: Path, base: str, head: str, target_files: list[str]) -> str:
    completed = subprocess.run(
        ["git", "diff", "--binary", base, head, "--", *target_files],
        cwd=repo_root,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "git diff failed"
        raise PromoteError("ERR_KEELPLANE_PROMOTE_GIT", detail, path=repo_root)
    return completed.stdout


def checkpoint_file_hashes(repo_root: Path, checkpoint: str, target_files: list[str]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in target_files:
        content = git_optional_bytes(["show", f"{checkpoint}:{path}"], repo_root)
        records.append(
            {
                "path": path,
                "exists_at_checkpoint": content is not None,
                "sha256": sha256_bytes(content) if content is not None else None,
            }
        )
    return records


def run_id_from_dir(run_dir: Path) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", run_dir.name).strip(".-_")
    return slug or "run"


def branch_name(run_id: str) -> str:
    return f"keelplane-loop/{run_id}"


def ensure_clean_worktree(repo_root: Path) -> None:
    if git(["status", "--porcelain", "--untracked-files=no"], repo_root):
        raise PromoteError("ERR_KEELPLANE_PROMOTE_WORKTREE_DIRTY", "repo worktree must be clean before creating a promotion branch", path=repo_root)


def create_local_branch(repo_root: Path, *, branch: str, base_ref: str, patch_path: Path, expected_paths: list[str], run_id: str) -> dict[str, Any]:
    if branch in {"main", "master"} or branch.startswith("main/") or branch.startswith("master/"):
        raise PromoteError("ERR_KEELPLANE_PROMOTE_BRANCH_UNSAFE", "promotion branch must not be main or master")
    ensure_clean_worktree(repo_root)
    main_commit = git(["rev-parse", "--verify", f"refs/heads/{base_ref}"], repo_root)
    git(["checkout", base_ref], repo_root)
    git(["checkout", "-B", branch, main_commit], repo_root)
    git_apply_index(repo_root, patch_path)
    staged_paths = sorted(path for path in git(["diff", "--cached", "--name-only"], repo_root).splitlines() if path)
    if staged_paths != expected_paths:
        raise PromoteError("ERR_KEELPLANE_PROMOTE_SCOPE", f"staged branch diff does not match bounded target paths: {staged_paths}")
    git(["commit", "-m", f"Promote Keelplane run {run_id}"], repo_root)
    branch_commit = git(["rev-parse", "HEAD"], repo_root)
    branch_paths = sorted(path for path in git(["diff", "--name-only", main_commit, branch_commit], repo_root).splitlines() if path)
    if branch_paths != expected_paths:
        raise PromoteError("ERR_KEELPLANE_PROMOTE_SCOPE", f"branch diff does not match bounded target paths: {branch_paths}")
    return {"base_ref": base_ref, "base_commit": main_commit, "branch": branch, "branch_commit": branch_commit, "branch_diff_paths": branch_paths}


def write_promotion(run_dir: Path, record: dict[str, Any]) -> dict[str, Any]:
    body = {key: value for key, value in record.items() if key != "promotion_hash"}
    promotion = {**body, "promotion_hash": canonical_hash(body)}
    write_json_atomic(run_dir / PROMOTION, promotion, root=run_dir)
    return promotion


def promote_run(
    run_dir: Path,
    *,
    repo_root: Path,
    approve_branch_push: bool = False,
    main_ref: str = DEFAULT_MAIN_REF,
) -> dict[str, Any]:
    run = load_verified_run(run_dir)
    all_changed = changed_paths(repo_root, run["run_base"], run["last_checkpoint"])
    target_files = run["target_files"]
    extra = sorted(set(all_changed) - set(target_files))
    if extra:
        raise PromoteError("ERR_KEELPLANE_PROMOTE_SCOPE", f"checkpoint touched undeclared files: {extra}", path=run_dir)
    target_changed = sorted(path for path in all_changed if path in set(target_files))
    if not target_changed:
        raise PromoteError("ERR_KEELPLANE_PROMOTE_EMPTY", "bounded target diff is empty", path=run_dir)
    patch_text = bounded_patch(repo_root, run["run_base"], run["last_checkpoint"], target_files)
    patch_path = run_dir / PATCH_FILE
    write_text_atomic(patch_path, patch_text, root=run_dir)

    run_id = run_id_from_dir(run_dir)
    branch = branch_name(run_id)
    base_record = {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "run_id": run_id,
        "decision": "promotion_patch_prepared",
        "declared_target_files": checkpoint_file_hashes(repo_root, run["last_checkpoint"], target_files),
        "changed_target_files": target_changed,
        "run_base": run["run_base"],
        "last_checkpoint": run["last_checkpoint"],
        "evidence_chain_head": run["status"]["evidence_chain_head"],
        "status_hash": run["status"]["status_hash"],
        "provenance_policy": {
            "promotion_json_is_correctness_claim": False,
            "evidence_links_are_provenance_only": True,
        },
        "source_hashes": {
            "journal": canonical_hash(run["journal"]),
            "status": canonical_hash(run["status"]),
            "bounded_patch_sha256": sha256_bytes(patch_text.encode("utf-8")),
        },
        "owned_by_sentinel": run["owned_by_sentinel"],
        "branch": branch,
        "branch_push_approved": approve_branch_push,
        "created_at": now_utc(),
    }
    write_promotion(run_dir, base_record)
    branch_record = create_local_branch(repo_root, branch=branch, base_ref=main_ref, patch_path=patch_path, expected_paths=target_changed, run_id=run_id)
    promotion = write_promotion(
        run_dir,
        {
            **base_record,
            "decision": "local_branch_ready",
            "branch_record": branch_record,
            "next_step": "review local branch or rerun with --i-approve-branch-push to push and open a draft PR",
        },
    )
    if approve_branch_push:
        push_record = push_and_open_pr(repo_root, branch=branch, base_ref=main_ref, run_id=run_id)
        promotion = write_promotion(run_dir, {**promotion, "decision": "draft_pr_opened", "push_record": push_record})
    return promotion


def push_and_open_pr(repo_root: Path, *, branch: str, base_ref: str, run_id: str) -> dict[str, Any]:
    if branch in {"main", "master"}:
        raise PromoteError("ERR_KEELPLANE_PROMOTE_BRANCH_UNSAFE", "refusing to push main or master")
    git(["push", "-u", "origin", branch], repo_root)
    completed = subprocess.run(
        [
            "gh",
            "pr",
            "create",
            "--draft",
            "--base",
            base_ref,
            "--head",
            branch,
            "--title",
            f"Keelplane loop promotion: {run_id}",
            "--body",
            f"Promotes Keelplane verified run `{run_id}`. Evidence provenance is recorded in `{PROMOTION}`.",
        ],
        cwd=repo_root,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "gh pr create failed"
        raise PromoteError("ERR_KEELPLANE_PROMOTE_PR_FAILED", detail, path=repo_root)
    return {"pushed_branch": branch, "draft_pr_url": completed.stdout.strip()}


def git_fixture(repo: Path, args: list[str]) -> str:
    try:
        return git_text(args, repo).strip()
    except Exception as exc:  # noqa: BLE001 - fixture failures should report the fixture repo.
        raise PromoteError("ERR_KEELPLANE_PROMOTE_FIXTURE_FAILED", str(exc), path=repo) from exc


def fixture_write(repo: Path, rel_path: str, text: str) -> None:
    path = repo / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def fixture_commit(repo: Path, message: str) -> str:
    git_fixture(repo, ["add", "."])
    git_fixture(repo, ["commit", "-m", message])
    return git_fixture(repo, ["rev-parse", "HEAD"])


def seed_fixture_repo(repo: Path, kind: str) -> tuple[Path, str, str]:
    repo.mkdir(parents=True)
    git_fixture(repo, ["init", "-b", "main"])
    git_fixture(repo, ["config", "user.email", "keelplane@example.invalid"])
    git_fixture(repo, ["config", "user.name", "Keelplane Promote"])
    fixture_write(repo, "src/app.txt", "base\n")
    fixture_write(repo, "docs/note.txt", "note\n")
    base = fixture_commit(repo, "seed main")
    git_fixture(repo, ["checkout", "-b", "checkpoint"])
    fixture_write(repo, "src/app.txt", "target\n")
    if kind == "scope-violation":
        fixture_write(repo, "docs/note.txt", "stray\n")
    checkpoint = fixture_commit(repo, "checkpoint")
    git_fixture(repo, ["checkout", "main"])
    if kind == "conflict":
        fixture_write(repo, "src/app.txt", "main advanced\n")
        fixture_commit(repo, "advance main")
    run_dir = repo / LOOP_OUT_DIRNAME / "fixture-run"
    run_dir.mkdir(parents=True)
    write_fixture_run(run_dir, kind=kind, base=base, checkpoint=checkpoint)
    return run_dir, base, checkpoint


def write_fixture_run(run_dir: Path, *, kind: str, base: str, checkpoint: str) -> None:
    previous = "0" * 64
    phase_body = {
        "fixture_id": kind,
        "phase_id": "fixture",
        "previous_evidence_hash": previous,
        "checkpoint_commit": checkpoint,
        "recorded_at": "2026-06-20T00:00:00Z",
    }
    phase = {**phase_body, "phase_evidence_hash": canonical_hash(phase_body)}
    terminal_state = "blocked" if kind == "not-verified-complete" else "verified-complete"
    journal = {
        "schema_version": LOOP_SCHEMA_VERSION,
        "fixture_id": kind,
        "mode": "fixture-promote",
        "run_base": base,
        "seed_commit": base,
        "last_checkpoint": checkpoint,
        "target_files": ["src/app.txt"],
        "chain_head": phase["phase_evidence_hash"],
        "phases": [phase],
    }
    status_body = {
        "schema_version": LOOP_SCHEMA_VERSION,
        "tool": "keelplane_loop.py",
        "fixture_id": kind,
        "terminal_state": terminal_state,
        "terminal_explanation": "fixture status",
        "verified_phase_count": 1,
        "evidence_chain_head": journal["chain_head"],
        "invalidators": [] if terminal_state == "verified-complete" else [{"code": "fixture", "message": "not complete"}],
        "checked_at": "2026-06-20T00:00:00Z",
    }
    status = {**status_body, "status_hash": canonical_hash(status_body)}
    journal["terminal_state"] = terminal_state
    journal["evidence_chain_head"] = status["evidence_chain_head"]
    journal["status_hash"] = status["status_hash"]
    write_json_atomic(run_dir / LOOP_SENTINEL, {"tool": "keelplane_loop.py", "schema_version": LOOP_SCHEMA_VERSION}, root=run_dir)
    write_json_atomic(run_dir / JOURNAL, journal, root=run_dir)
    write_json_atomic(run_dir / STATUS, status, root=run_dir)


def assert_clean_promotion(repo: Path, run_dir: Path, promotion: dict[str, Any]) -> None:
    if promotion.get("decision") != "local_branch_ready":
        raise PromoteError("ERR_KEELPLANE_PROMOTE_FIXTURE_FAILED", f"expected local_branch_ready, got {promotion.get('decision')}")
    if not (run_dir / PROMOTION).is_file():
        raise PromoteError("ERR_KEELPLANE_PROMOTE_FIXTURE_FAILED", "promotion.json was not written", path=run_dir)
    recorded = read_json(run_dir / PROMOTION)
    promotion_hash = recorded.get("promotion_hash")
    if canonical_hash({key: value for key, value in recorded.items() if key != "promotion_hash"}) != promotion_hash:
        raise PromoteError("ERR_KEELPLANE_PROMOTE_FIXTURE_FAILED", "promotion hash mismatch", path=run_dir / PROMOTION)
    branch = str(recorded["branch"])
    diff_names = git_fixture(repo, ["diff", "--name-only", "main", branch]).splitlines()
    if diff_names != ["src/app.txt"]:
        raise PromoteError("ERR_KEELPLANE_PROMOTE_FIXTURE_FAILED", f"unexpected branch diff paths: {diff_names}")
    diff_text = git_fixture(repo, ["diff", "main", branch, "--", "src/app.txt"])
    if "+target" not in diff_text or "-base" not in diff_text:
        raise PromoteError("ERR_KEELPLANE_PROMOTE_FIXTURE_FAILED", "branch diff does not contain target change")


def run_fixture(fixture: dict[str, Any], suite_dir: Path) -> dict[str, Any]:
    fixture_id = str(fixture["id"])
    kind = str(fixture["kind"])
    repo = suite_dir / fixture_id / "repo"
    try:
        run_dir, _base, _checkpoint = seed_fixture_repo(repo, kind)
        promotion = promote_run(run_dir, repo_root=repo)
        if kind == "clean":
            assert_clean_promotion(repo, run_dir, promotion)
        expected_decision = fixture.get("expected_decision")
        if expected_decision is not None and promotion.get("decision") != expected_decision:
            raise PromoteError("ERR_KEELPLANE_PROMOTE_FIXTURE_FAILED", f"expected {expected_decision}, got {promotion.get('decision')}")
        return {"id": fixture_id, "status": "pass", "decision": promotion.get("decision")}
    except PromoteError as exc:
        expected_error = fixture.get("expected_error")
        if expected_error == exc.code:
            return {"id": fixture_id, "status": "pass", "error": exc.code}
        return {"id": fixture_id, "status": "fail", "error": exc.to_record()}


def read_manifest(path: Path) -> dict[str, Any]:
    data = read_json(path)
    if data.get("schema_version") != "keelplane-promote-fixture-v1":
        raise PromoteError("ERR_KEELPLANE_PROMOTE_MANIFEST_INVALID", "unsupported manifest schema_version", path=path)
    fixtures = data.get("fixtures")
    if not isinstance(fixtures, list) or not fixtures:
        raise PromoteError("ERR_KEELPLANE_PROMOTE_MANIFEST_INVALID", "manifest fixtures must be a non-empty list", path=path)
    return data


def run_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_manifest(manifest_path)
    out_dir = resolve_out(out_dir)
    prepare_out_dir(out_dir, str(manifest.get("suite_id", out_dir.name)))
    records = [run_fixture(fixture, out_dir) for fixture in manifest["fixtures"]]
    passed = sum(1 for record in records if record["status"] == "pass")
    total = len(records)
    summary = {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "suite_id": str(manifest.get("suite_id", "keelplane-promote")),
        "passed": passed,
        "total": total,
        "failed": total - passed,
        "decision": "keep" if passed == total else "kill",
        "fixtures": records,
        "source_hashes": {"manifest": canonical_hash(manifest)},
    }
    write_json_atomic(out_dir / "summary.json", summary, root=out_dir)
    return summary


def self_test() -> dict[str, Any]:
    out_dir = OUT_ROOT / "self-test"
    summary = run_manifest(ROOT / "fixtures" / "keelplane-promote" / "manifest.json", out_dir)
    if summary["decision"] != "keep":
        raise PromoteError("ERR_KEELPLANE_PROMOTE_SELF_TEST_FAILED", "fixture suite did not keep", path=out_dir / "summary.json")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Keelplane output promotion stage")
    parser.add_argument("command", nargs="?", choices=["promote"])
    parser.add_argument("--run")
    parser.add_argument("--repo", default=str(ROOT))
    parser.add_argument("--main-ref", default=DEFAULT_MAIN_REF)
    parser.add_argument("--manifest")
    parser.add_argument("--out")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--i-approve-branch-push", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "promote":
            if not args.run:
                raise PromoteError("ERR_KEELPLANE_PROMOTE_ARGS", "promote requires --run")
            repo_root = resolve_repo(args.repo)
            run_dir = resolve_run_dir(args.run, repo_root=repo_root)
            promotion = promote_run(
                run_dir,
                repo_root=repo_root,
                approve_branch_push=args.i_approve_branch_push,
                main_ref=args.main_ref,
            )
            print(json.dumps({key: promotion[key] for key in ["decision", "branch", "promotion_hash"]}, sort_keys=True))
            return 0
        if args.self_test:
            summary = self_test()
            print(f"keelplane_promote self-test: pass ({summary['passed']}/{summary['total']})")
            return 0
        if args.manifest:
            if not args.out:
                raise PromoteError("ERR_KEELPLANE_PROMOTE_ARGS", "--manifest requires --out")
            summary = run_manifest(Path(args.manifest), Path(args.out))
            print(json.dumps({key: summary[key] for key in ["decision", "passed", "total", "failed"]}, sort_keys=True))
            return 0 if summary["decision"] == "keep" else 1
        raise PromoteError("ERR_KEELPLANE_PROMOTE_ARGS", "expected promote, --self-test, or --manifest")
    except PromoteError as exc:
        print(json.dumps({"error": exc.to_record()}, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
