#!/usr/bin/env python3
"""V102/V103 live-proof recorder and deterministic evidence contract tests."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
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
    compile_plan,
    read_json,
    write_json_atomic,
    write_text_atomic,
)


TOOL = "dwm_live_proof.py"
SCHEMA_VERSION = "102.0.0"
COMPARISON_SCHEMA_VERSION = "103.0.0"
LIVE_PROOF_ROOT = ROOT / "out" / "live-proofs"
V102_OUT_ROOT = ROOT / "out" / "v102"
V103_OUT_ROOT = ROOT / "out" / "v103"
V1_OUT_ROOT = ROOT / "out" / "v1"
SENTINEL = ".dwm_live_proof-owned.json"
PUBLIC_MANIFEST = ROOT / "fixtures" / "v102" / "manifest.json"
PUBLIC_COMPARISON_MANIFEST = ROOT / "fixtures" / "v103" / "manifest.json"
CLAIM_POLICY = "live n=1 only; no direct-agent superiority claim"
COMPARISON_CLAIM_POLICY = "comparison on n=1; no direct-agent superiority claim"
HONEST_CONCLUSION = (
    "Both arms reached a green check on this task. Only the dwm-controlled arm "
    "recorded an independent legitimacy verdict and hash-bound evidence. This "
    "records evidence richness, not pass-rate, speed, or cost superiority."
)


class LiveProofError(ValueError):
    """Structured V102 failure."""

    def __init__(
        self, code: str, message: str, *, path: Path | str | None = None
    ) -> None:
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


def reject_traversal(path: Path, *, code: str) -> None:
    if any(part == ".." for part in path.parts):
        raise LiveProofError(code, "path must not contain parent traversal", path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise LiveProofError(code, "path contains a symlink", path=current)


def resolve_repo_input(value: str | Path, *, code: str) -> Path:
    raw = Path(value)
    reject_traversal(raw, code=code)
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(ROOT.resolve(strict=False))
    except ValueError as exc:
        raise LiveProofError(
            code, "input must resolve inside this repository", path=value
        ) from exc
    check_components_not_symlink(candidate, code="ERR_LIVE_PROOF_PATH_SYMLINK")
    if not resolved.exists() or resolved.is_symlink():
        raise LiveProofError(code, "input is missing or unsafe", path=value)
    return resolved


def resolve_manifest_out(value: str | Path) -> Path:
    return resolve_versioned_manifest_out(value, V102_OUT_ROOT)


def resolve_comparison_manifest_out(value: str | Path) -> Path:
    return resolve_versioned_manifest_out(value, V103_OUT_ROOT)


def resolve_versioned_manifest_out(value: str | Path, version_root: Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_LIVE_PROOF_OUT_UNSAFE")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root = version_root.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise LiveProofError(
            "ERR_LIVE_PROOF_OUT_UNSAFE",
            f"manifest output must resolve under {root}",
            path=value,
        ) from exc
    if resolved == root:
        raise LiveProofError(
            "ERR_LIVE_PROOF_OUT_UNSAFE",
            "manifest output must name a directory",
            path=value,
        )
    check_components_not_symlink(candidate, code="ERR_LIVE_PROOF_PATH_SYMLINK")
    return resolved


def resolve_live_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_LIVE_PROOF_OUT_UNSAFE")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root = LIVE_PROOF_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise LiveProofError(
            "ERR_LIVE_PROOF_OUT_UNSAFE",
            f"live output must resolve under {root}",
            path=value,
        ) from exc
    if resolved == root:
        raise LiveProofError(
            "ERR_LIVE_PROOF_OUT_UNSAFE", "live output must name a directory", path=value
        )
    check_components_not_symlink(candidate, code="ERR_LIVE_PROOF_PATH_SYMLINK")
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


def prepare_owned_dir(
    path: Path, proof_id: str, *, source: Path | str, root: Path
) -> None:
    if path.exists():
        if path.is_symlink():
            raise LiveProofError(
                "ERR_LIVE_PROOF_PATH_SYMLINK", "output is a symlink", path=path
            )
        if not path.is_dir():
            raise LiveProofError(
                "ERR_LIVE_PROOF_OUT_UNSAFE",
                "output exists and is not a directory",
                path=path,
            )
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("proof_id") != proof_id:
            raise LiveProofError(
                "ERR_LIVE_PROOF_OUT_UNSAFE",
                "existing output is not V102-owned",
                path=path,
            )
        shutil.rmtree(path)
    root.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(
        path / SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "proof_id": proof_id,
            "source_path": str(source),
            "created_at": now_utc(),
        },
        root=path,
    )


def safe_copy_seed(seed: Path, workspace: Path) -> None:
    for path in [seed, *seed.rglob("*")]:
        if path.is_symlink():
            raise LiveProofError(
                "ERR_LIVE_PROOF_PATH_SYMLINK",
                "seed must not contain symlinks",
                path=path,
            )
    shutil.copytree(seed, workspace)


def run_process(
    argv: list[str],
    cwd: Path,
    *,
    input_text: str | None = None,
    timeout_seconds: int = 120,
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    env.setdefault("PYTEST_ADDOPTS", "-p no:cacheprovider")
    return subprocess.run(
        argv,
        cwd=cwd,
        env=env,
        input=input_text,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout_seconds,
    )


def git_text(args: list[str], cwd: Path) -> str:
    result = run_process(["git", *args], cwd, timeout_seconds=30)
    if result.returncode != 0:
        raise LiveProofError(
            "ERR_LIVE_PROOF_GIT_FAILED",
            result.stderr.strip() or result.stdout.strip(),
            path=cwd,
        )
    return result.stdout.strip()


def repo_tracked_state() -> dict[str, str]:
    return {
        "diff": git_text(["diff", "--name-only"], ROOT),
        "staged": git_text(["diff", "--cached", "--name-only"], ROOT),
    }


def init_seed_repo(workspace: Path) -> dict[str, str]:
    run_process(["git", "init"], workspace, timeout_seconds=30)
    run_process(
        ["git", "config", "user.email", "live-proof@example.invalid"],
        workspace,
        timeout_seconds=30,
    )
    run_process(
        ["git", "config", "user.name", "DWM Live Proof"], workspace, timeout_seconds=30
    )
    run_process(["git", "add", "."], workspace, timeout_seconds=30)
    commit = run_process(["git", "commit", "-m", "seed"], workspace, timeout_seconds=30)
    if commit.returncode != 0:
        raise LiveProofError(
            "ERR_LIVE_PROOF_GIT_FAILED",
            commit.stderr.strip() or commit.stdout.strip(),
            path=workspace,
        )
    return {
        "head": git_text(["rev-parse", "HEAD"], workspace),
        "status": git_text(["status", "--short"], workspace),
    }


def touched_files(workspace: Path) -> list[str]:
    output = git_text(["status", "--short"], workspace)
    files = []
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # Porcelain short format is "XY path"; split on the status code rather
        # than a fixed slice, since the leading column may be stripped.
        parts = stripped.split(maxsplit=1)
        if len(parts) == 2:
            files.append(parts[1])
    return sorted(files)


def is_test_file(rel_path: str) -> bool:
    name = rel_path.rsplit("/", 1)[-1]
    return (name.startswith("test_") and name.endswith(".py")) or name.endswith(
        "_test.py"
    )


def independent_review(
    seed: Path, workspace: Path, *, verification_passed: bool
) -> dict[str, Any]:
    """Independent legitimacy check: confirm the green came from a real source fix.

    This refutes a passing verification when the change is illegitimate, e.g. the
    seeded test was edited/removed to force a pass, or no source file changed. It
    is intentionally not a copy of verification_passed; it can disagree with it.
    """
    reasons: list[str] = []
    test_files_unchanged = True
    source_changed = False
    for path in sorted(item for item in seed.rglob("*") if item.is_file()):
        rel_path = path.relative_to(seed).as_posix()
        target = workspace / rel_path
        current = (
            target.read_text() if target.is_file() and not target.is_symlink() else None
        )
        changed = current != path.read_text()
        if is_test_file(rel_path):
            if changed:
                test_files_unchanged = False
                reasons.append(f"test file changed: {rel_path}")
        elif rel_path.endswith(".py") and changed:
            source_changed = True
    if not source_changed:
        reasons.append("no source .py file changed")
    approved = verification_passed and test_files_unchanged and source_changed
    if not verification_passed:
        reasons.append("verification did not pass")
    return {
        "decision": "approved" if approved else "request-changes",
        "evidence_path": "review.json",
        "checks": {
            "verification_passed": verification_passed,
            "test_files_unchanged": test_files_unchanged,
            "source_changed": source_changed,
        },
        "reasons": reasons,
    }


def codex_auth_failed(result: subprocess.CompletedProcess[str]) -> bool:
    text = f"{result.stdout}\n{result.stderr}".lower()
    needles = ["not authenticated", "authentication", "auth", "login", "sign in"]
    return result.returncode != 0 and any(needle in text for needle in needles)


def command_hash(command: list[str]) -> str:
    return canonical_hash(
        {"argv": command, "backend": "codex-cli", "mode": "installed-codex"}
    )


def tree_hash(root: Path) -> str:
    files = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        files.append(
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": canonical_hash({"content": path.read_text()}),
            }
        )
    return canonical_hash({"files": files})


def base_bundle(
    proof_id: str,
    *,
    seed_path: str = "fixtures/live-proof/seed",
    objective: str = "Make the seeded pytest check pass.",
) -> dict[str, Any]:
    return {
        "proof_id": proof_id,
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "task": {
            "id": "live-proof-1",
            "seed_path": seed_path,
            "objective": objective,
            "verification_command": "python -m pytest -q",
        },
        "backend": "codex-cli",
        "mode": "installed-codex",
        "model_provider": "codex-cli-default",
        "worktree": {
            "path": f"out/live-proofs/{proof_id}/workspace",
            "isolated": True,
            "pre_state": {},
            "post_state": {},
        },
        "prompt_hash": "0" * 64,
        "packet_hash": "1" * 64,
        "adapter_hash": "2" * 64,
        "commands": [],
        "files_touched": [],
        "transcript_path": "transcript.md",
        "verification": {
            "command": "python -m pytest -q",
            "returncode": 0,
            "passed": True,
            "before": "red",
            "after": "green",
            "output_path": "verification-after.txt",
        },
        "review": {
            "decision": "approved",
            "evidence_path": "review.json",
            "checks": {
                "verification_passed": True,
                "test_files_unchanged": True,
                "source_changed": True,
            },
            "reasons": [],
        },
        "elapsed_seconds": 1.0,
        "interruptions": 0,
        "repo_tracked_diff_unchanged": True,
        "dogfood_comparison": {
            "mode": "dwm-controlled",
            "status": "run",
            "metrics": {
                "elapsed_seconds": 1.0,
                "interruptions": 0,
                "verification_passed": True,
            },
        },
        "decision": "live-proof-pass",
        "blocked_by": [],
        "claim_policy": CLAIM_POLICY,
        "source_hashes": {
            "seed": "3" * 64,
            "plan": "4" * 64,
            "packet": "1" * 64,
            "prompt": "0" * 64,
        },
    }


def base_comparison(comparison_id: str) -> dict[str, Any]:
    return {
        "comparison_id": comparison_id,
        "schema_version": COMPARISON_SCHEMA_VERSION,
        "tool": TOOL,
        "task": {
            "id": "live-proof-1",
            "seed_path": "fixtures/live-proof/seed",
            "verification_command": "python -m pytest -q",
        },
        "arms": [
            {
                "mode": "direct-codex",
                "worktree": {
                    "path": f"out/live-proofs/{comparison_id}/direct-workspace",
                    "isolated": True,
                    "pre_state": {},
                    "post_state": {"status": " M live_math.py"},
                },
                "verification": {
                    "before": "red",
                    "after": "green",
                    "returncode": 0,
                    "passed": True,
                },
                "files_touched": ["live_math.py"],
                "transcript_path": "direct-transcript.md",
                "elapsed_seconds": 1.0,
                "has_independent_review": False,
                "has_hash_bound_bundle": False,
                "legitimacy_verdict": None,
                "blocked_by": [],
            },
            {
                "mode": "dwm-controlled",
                "proof_ref": "dwm/live-proof.json",
                "decision": "live-proof-pass",
                "verification": {
                    "before": "red",
                    "after": "green",
                    "returncode": 0,
                    "passed": True,
                },
                "files_touched": ["live_math.py"],
                "transcript_path": "dwm/transcript.md",
                "elapsed_seconds": 1.0,
                "has_independent_review": True,
                "has_hash_bound_bundle": True,
                "legitimacy_verdict": {
                    "decision": "approved",
                    "checks": {
                        "verification_passed": True,
                        "test_files_unchanged": True,
                        "source_changed": True,
                    },
                },
                "blocked_by": [],
            },
        ],
        "differentiators": {
            "independent_legitimacy_review": "dwm-controlled only",
            "hash_bound_evidence_bundle": "dwm-controlled only",
        },
        "honest_conclusion": HONEST_CONCLUSION,
        "claim_policy": COMPARISON_CLAIM_POLICY,
        "repo_tracked_diff_unchanged": True,
        "source_hashes": {"seed": "3" * 64, "plan": "4" * 64},
    }


def validate_bundle(bundle: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required = [
        "proof_id",
        "schema_version",
        "tool",
        "task",
        "backend",
        "mode",
        "model_provider",
        "worktree",
        "prompt_hash",
        "packet_hash",
        "adapter_hash",
        "commands",
        "files_touched",
        "transcript_path",
        "verification",
        "review",
        "elapsed_seconds",
        "interruptions",
        "repo_tracked_diff_unchanged",
        "dogfood_comparison",
        "decision",
        "claim_policy",
        "source_hashes",
    ]
    for key in required:
        if key not in bundle:
            errors.append(f"missing:{key}")
    if errors:
        return errors
    if bundle["schema_version"] != SCHEMA_VERSION:
        errors.append("schema_version")
    if bundle["tool"] != TOOL:
        errors.append("tool")
    if bundle["backend"] != "codex-cli" or bundle["mode"] != "installed-codex":
        errors.append("backend")
    if bundle["decision"] not in {"live-proof-pass", "blocked", "failed"}:
        errors.append("decision")
    if bundle["claim_policy"] != CLAIM_POLICY:
        errors.append("claim_policy")
    if bundle["repo_tracked_diff_unchanged"] is not True:
        errors.append("repo_tracked_diff_unchanged")
    for key in [
        "task",
        "worktree",
        "verification",
        "review",
        "dogfood_comparison",
        "source_hashes",
    ]:
        if not isinstance(bundle.get(key), dict):
            errors.append(f"{key}:object")
    if not isinstance(bundle.get("commands"), list):
        errors.append("commands:list")
    if not isinstance(bundle.get("files_touched"), list):
        errors.append("files_touched:list")
    if not isinstance(bundle.get("elapsed_seconds"), (int, float)):
        errors.append("elapsed_seconds:number")
    if not isinstance(bundle.get("interruptions"), int):
        errors.append("interruptions:int")

    verification = (
        bundle.get("verification")
        if isinstance(bundle.get("verification"), dict)
        else {}
    )
    dogfood = (
        bundle.get("dogfood_comparison")
        if isinstance(bundle.get("dogfood_comparison"), dict)
        else {}
    )
    metrics = dogfood.get("metrics") if isinstance(dogfood.get("metrics"), dict) else {}
    review = bundle.get("review") if isinstance(bundle.get("review"), dict) else {}
    review_decision = review.get("decision")
    if review_decision not in {"approved", "request-changes", "blocked"}:
        errors.append("review.decision")
    if dogfood.get("mode") != "dwm-controlled":
        errors.append("dogfood_comparison.mode")
    if bundle["decision"] == "live-proof-pass":
        if (
            verification.get("passed") is not True
            or verification.get("before") != "red"
            or verification.get("after") != "green"
        ):
            errors.append("verification.red_green")
        if (
            dogfood.get("status") != "run"
            or metrics.get("verification_passed") is not True
        ):
            errors.append("dogfood_comparison.run_metric")
        # A pass requires an independent review verdict, not just a green check.
        if review_decision != "approved":
            errors.append("review.approved")
    elif bundle["decision"] == "blocked":
        blocked_by = bundle.get("blocked_by")
        if not isinstance(blocked_by, list) or not blocked_by:
            errors.append("blocked_by")
        if verification.get("passed") is True:
            errors.append("blocked_passed")
    elif bundle["decision"] == "failed":
        # Failure is legitimate when verification failed OR an independent review
        # refused the change (e.g. the test was gamed to force a green).
        if verification.get("passed") is True and review_decision != "request-changes":
            errors.append("failed_verification")
    return errors


def validate_comparison(record: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required = [
        "comparison_id",
        "schema_version",
        "tool",
        "task",
        "arms",
        "differentiators",
        "honest_conclusion",
        "claim_policy",
        "repo_tracked_diff_unchanged",
        "source_hashes",
    ]
    for key in required:
        if key not in record:
            errors.append(f"missing:{key}")
    if errors:
        return errors
    if record["schema_version"] != COMPARISON_SCHEMA_VERSION:
        errors.append("schema_version")
    if record["tool"] != TOOL:
        errors.append("tool")
    if record["claim_policy"] != COMPARISON_CLAIM_POLICY:
        errors.append("claim_policy")
    if record["repo_tracked_diff_unchanged"] is not True:
        errors.append("repo_tracked_diff_unchanged")
    for key in ["task", "differentiators", "source_hashes"]:
        if not isinstance(record.get(key), dict):
            errors.append(f"{key}:object")
    arms = record.get("arms")
    if not isinstance(arms, list) or len(arms) != 2:
        errors.append("arms")
        return errors
    by_mode = {
        arm.get("mode"): arm
        for arm in arms
        if isinstance(arm, dict) and isinstance(arm.get("mode"), str)
    }
    direct = by_mode.get("direct-codex")
    controlled = by_mode.get("dwm-controlled")
    if direct is None:
        errors.append("direct-codex")
    if controlled is None:
        errors.append("dwm-controlled")
    conclusion = str(record.get("honest_conclusion") or "")
    required_terms = [
        "evidence richness",
        "not pass-rate, speed, or cost superiority",
        "independent legitimacy verdict",
        "hash-bound evidence",
    ]
    for term in required_terms:
        if term not in conclusion:
            errors.append(f"honest_conclusion:{term}")
    differentiators = record.get("differentiators") if isinstance(record.get("differentiators"), dict) else {}
    if differentiators.get("independent_legitimacy_review") != "dwm-controlled only":
        errors.append("differentiators.independent_legitimacy_review")
    if differentiators.get("hash_bound_evidence_bundle") != "dwm-controlled only":
        errors.append("differentiators.hash_bound_evidence_bundle")
    if direct is not None:
        if direct.get("has_independent_review") is not False:
            errors.append("direct.has_independent_review")
        if direct.get("has_hash_bound_bundle") is not False:
            errors.append("direct.has_hash_bound_bundle")
        if direct.get("legitimacy_verdict") is not None:
            errors.append("direct.legitimacy_verdict")
        if not isinstance(direct.get("verification"), dict):
            errors.append("direct.verification")
        elif direct["verification"].get("before") not in {"red", "green", "not-run"}:
            errors.append("direct.verification.before")
        if not isinstance(direct.get("files_touched"), list):
            errors.append("direct.files_touched")
        if not isinstance(direct.get("elapsed_seconds"), (int, float)):
            errors.append("direct.elapsed_seconds")
    if controlled is not None:
        if controlled.get("has_independent_review") is not True:
            errors.append("dwm.has_independent_review")
        if controlled.get("has_hash_bound_bundle") is not True:
            errors.append("dwm.has_hash_bound_bundle")
        verdict = controlled.get("legitimacy_verdict")
        if not isinstance(verdict, dict) or verdict.get("decision") not in {"approved", "request-changes", "blocked"}:
            errors.append("dwm.legitimacy_verdict")
        if not isinstance(controlled.get("verification"), dict):
            errors.append("dwm.verification")
        if not isinstance(controlled.get("files_touched"), list):
            errors.append("dwm.files_touched")
        if not isinstance(controlled.get("elapsed_seconds"), (int, float)):
            errors.append("dwm.elapsed_seconds")
    return errors


def render_markdown(bundle: dict[str, Any], errors: list[str] | None = None) -> str:
    lines = [
        "# V102 Live Proof",
        "",
        f"- Proof: `{bundle.get('proof_id', '')}`",
        f"- Decision: `{bundle.get('decision', '')}`",
        f"- Backend: `{bundle.get('backend', '')}/{bundle.get('mode', '')}`",
        f"- Verification passed: `{bundle.get('verification', {}).get('passed') if isinstance(bundle.get('verification'), dict) else None}`",
        f"- Claim policy: {bundle.get('claim_policy', '')}",
    ]
    if bundle.get("blocked_by"):
        lines.append(
            f"- Blocked by: `{', '.join(str(item) for item in bundle['blocked_by'])}`"
        )
    if errors:
        lines.extend(["", "## Schema Errors", *[f"- `{error}`" for error in errors]])
    lines.extend(
        [
            "",
            "This bundle proves only the recorded V102 state. It makes no direct-agent superiority claim.",
            "",
        ]
    )
    return "\n".join(lines)


def render_comparison_markdown(record: dict[str, Any], errors: list[str] | None = None) -> str:
    lines = [
        "# V103 Live Proof Comparison",
        "",
        f"- Comparison: `{record.get('comparison_id', '')}`",
        f"- Claim policy: {record.get('claim_policy', '')}",
        f"- Conclusion: {record.get('honest_conclusion', '')}",
        "",
        "## Arms",
    ]
    for arm in record.get("arms", []):
        if not isinstance(arm, dict):
            continue
        lines.append(
            f"- `{arm.get('mode', '')}`: verification `{(arm.get('verification') or {}).get('after')}`, "
            f"independent_review `{arm.get('has_independent_review')}`, "
            f"hash_bound_bundle `{arm.get('has_hash_bound_bundle')}`"
        )
    if errors:
        lines.extend(["", "## Schema Errors", *[f"- `{error}`" for error in errors]])
    lines.append("")
    return "\n".join(lines)


def write_bundle(out_dir: Path, bundle: dict[str, Any]) -> list[str]:
    errors = validate_bundle(bundle)
    write_json_atomic(out_dir / "live-proof.json", bundle, root=out_dir)
    write_text_atomic(
        out_dir / "live-proof.md", render_markdown(bundle, errors), root=out_dir
    )
    write_text_atomic(
        out_dir / "live-proof.sha256", canonical_hash(bundle) + "\n", root=out_dir
    )
    write_json_atomic(
        out_dir / "status.json",
        {"decision": bundle.get("decision"), "valid": not errors, "errors": errors},
        root=out_dir,
    )
    return errors


def write_comparison(out_dir: Path, record: dict[str, Any]) -> list[str]:
    errors = validate_comparison(record)
    write_json_atomic(out_dir / "comparison.json", record, root=out_dir)
    write_text_atomic(
        out_dir / "comparison.md",
        render_comparison_markdown(record, errors),
        root=out_dir,
    )
    write_text_atomic(
        out_dir / "comparison.sha256", canonical_hash(record) + "\n", root=out_dir
    )
    write_json_atomic(
        out_dir / "status.json",
        {
            "comparison_id": record.get("comparison_id"),
            "decision": "keep" if not errors else "adjust",
            "valid": not errors,
            "errors": errors,
        },
        root=out_dir,
    )
    return errors


def run_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest_path = resolve_repo_input(
        manifest_path, code="ERR_LIVE_PROOF_MANIFEST_INVALID"
    )
    manifest_kind = ""
    if manifest_path == PUBLIC_MANIFEST.resolve(strict=False):
        manifest_kind = "bundle"
        out_dir = resolve_manifest_out(out_dir)
        out_root = V102_OUT_ROOT
    elif manifest_path == PUBLIC_COMPARISON_MANIFEST.resolve(strict=False):
        manifest_kind = "comparison"
        out_dir = resolve_comparison_manifest_out(out_dir)
        out_root = V103_OUT_ROOT
    else:
        raise LiveProofError(
            "ERR_LIVE_PROOF_MANIFEST_INVALID",
            "public manifest execution is limited to fixtures/v102/manifest.json or fixtures/v103/manifest.json",
            path=manifest_path,
        )
    manifest = read_json(manifest_path)
    fixtures = manifest.get("fixtures")
    if not isinstance(fixtures, list):
        raise LiveProofError(
            "ERR_LIVE_PROOF_MANIFEST_INVALID",
            "manifest fixtures must be a list",
            path=manifest_path,
        )
    prepare_owned_dir(out_dir, out_dir.name, source=manifest_path, root=out_root)
    records = []
    for fixture in fixtures:
        fixture_id = str(fixture.get("id", "fixture"))
        fixture_out = out_dir / fixture_id
        prepare_owned_dir(fixture_out, fixture_id, source=manifest_path, root=out_dir)
        if manifest_kind == "comparison":
            artifact = fixture.get("comparison") if isinstance(fixture.get("comparison"), dict) else {}
            errors = write_comparison(fixture_out, artifact)
            decision = "keep" if not errors else "adjust"
        else:
            artifact = fixture.get("bundle") if isinstance(fixture.get("bundle"), dict) else {}
            errors = write_bundle(fixture_out, artifact)
            decision = artifact.get("decision")
        valid = not errors
        expected_valid = bool(fixture.get("expected_valid", True))
        expected_decision = fixture.get("expected_decision")
        fixture_errors = []
        if valid != expected_valid:
            fixture_errors.append(f"expected valid {expected_valid}, got {valid}")
        if (
            expected_decision is not None
            and decision != expected_decision
        ):
            fixture_errors.append(
                f"expected decision {expected_decision}, got {decision}"
            )
        records.append(
            {
                "id": fixture_id,
                "required": bool(fixture.get("required", True)),
                "status": "pass" if not fixture_errors else "fail",
                "valid": valid,
                "decision": decision,
                "error": "; ".join(fixture_errors) if fixture_errors else None,
            }
        )
    failed_required = [
        record
        for record in records
        if record["required"] and record["status"] != "pass"
    ]
    summary = {
        "schema_version": COMPARISON_SCHEMA_VERSION if manifest_kind == "comparison" else SCHEMA_VERSION,
        "tool": TOOL,
        "suite_id": str(manifest.get("suite_id", "v102-live-proof")),
        "fixture_count": len(records),
        "required_fixture_count": sum(1 for record in records if record["required"]),
        "passed": sum(1 for record in records if record["status"] == "pass"),
        "failed": sum(1 for record in records if record["status"] != "pass"),
        "decision": "keep" if not failed_required else "kill",
        "fixtures": records,
        "source_hashes": {"manifest": canonical_hash(manifest)},
    }
    write_json_atomic(out_dir / "summary.json", summary, root=out_dir)
    if failed_required:
        raise LiveProofError(
            "ERR_LIVE_PROOF_FIXTURE_FAILED",
            "required live-proof fixture failed",
            path=manifest_path,
        )
    return summary


def self_test() -> None:
    passed = base_bundle("self-test-pass")
    if validate_bundle(passed):
        raise ValueError("pass bundle should validate")
    blocked = base_bundle("self-test-blocked")
    blocked.update(
        {
            "decision": "blocked",
            "blocked_by": [
                {
                    "code": "ERR_EXEC_BACKEND_AUTH",
                    "message": "Codex CLI authentication failed",
                }
            ],
            "verification": {
                "command": "python -m pytest -q",
                "returncode": None,
                "passed": False,
                "before": "red",
                "after": "not-run",
                "output_path": "verification-before.txt",
            },
            "dogfood_comparison": {
                "mode": "dwm-controlled",
                "status": "blocked",
                "metrics": {
                    "elapsed_seconds": 0.0,
                    "interruptions": 0,
                    "verification_passed": False,
                },
            },
        }
    )
    if validate_bundle(blocked):
        raise ValueError("blocked bundle should validate")
    failed = base_bundle("self-test-failed")
    failed.update(
        {
            "decision": "failed",
            "verification": {
                "command": "python -m pytest -q",
                "returncode": 1,
                "passed": False,
                "before": "red",
                "after": "red",
                "output_path": "verification-after.txt",
            },
            "dogfood_comparison": {
                "mode": "dwm-controlled",
                "status": "run",
                "metrics": {
                    "elapsed_seconds": 1.0,
                    "interruptions": 0,
                    "verification_passed": False,
                },
            },
        }
    )
    if validate_bundle(failed):
        raise ValueError("failed bundle should validate")
    malformed = dict(passed)
    malformed.pop("source_hashes")
    if not validate_bundle(malformed):
        raise ValueError("malformed bundle should fail validation")
    review_bundle = base_bundle("self-test-review-rejected")
    review_bundle["review"] = {
        "decision": "request-changes",
        "evidence_path": "review.json",
    }
    if "review.approved" not in validate_bundle(review_bundle):
        raise ValueError("pass bundle must require approved review")

    review_root = V102_OUT_ROOT / "self-test-review"
    prepare_owned_dir(
        review_root, "self-test-review", source="self-test", root=V102_OUT_ROOT
    )
    seed = review_root / "seed"
    workspace = review_root / "workspace"
    seed.mkdir()
    workspace.mkdir()
    write_text_atomic(
        seed / "math.py", "def add(a, b):\n    return a - b\n", root=review_root
    )
    write_text_atomic(seed / "test_math.py", "from math import add\n", root=review_root)
    shutil.copytree(seed, workspace, dirs_exist_ok=True)
    approved_workspace = review_root / "approved-workspace"
    shutil.copytree(seed, approved_workspace)
    write_text_atomic(
        approved_workspace / "math.py",
        "def add(a, b):\n    return a + b\n",
        root=review_root,
    )
    approved_review = independent_review(
        seed, approved_workspace, verification_passed=True
    )
    if approved_review["decision"] != "approved":
        raise ValueError("source-only verified change should pass independent review")
    write_text_atomic(workspace / "test_math.py", "# changed test\n", root=review_root)
    rejected_review = independent_review(seed, workspace, verification_passed=True)
    if rejected_review["decision"] != "request-changes":
        raise ValueError("test-only verified change should fail independent review")
    comparison = base_comparison("self-test-comparison")
    if validate_comparison(comparison):
        raise ValueError("comparison record should validate")
    comparison["arms"][0]["legitimacy_verdict"] = {"decision": "approved"}
    if "direct.legitimacy_verdict" not in validate_comparison(comparison):
        raise ValueError("direct arm must not borrow the DWM review verdict")


def compile_live_plan(plan_path: Path, proof_id: str) -> tuple[Path, dict[str, Any]]:
    run_dir = V1_OUT_ROOT / f"v102-{proof_id}"
    result = compile_plan(plan_path, run_dir, run_id=f"v102/{proof_id}", mode="compile")
    return run_dir, result


def verification_summary(result: subprocess.CompletedProcess[str], *, before: str, after: str) -> dict[str, Any]:
    return {
        "command": "python -m pytest -q",
        "returncode": result.returncode,
        "passed": result.returncode == 0,
        "before": before,
        "after": after,
        "output_path": "verification-after.txt",
    }


def run_direct_arm(
    *,
    codex: str,
    seed: Path,
    out_dir: Path,
    timeout_seconds: int,
) -> dict[str, Any]:
    workspace = out_dir / "direct-workspace"
    safe_copy_seed(seed, workspace)
    started = time.monotonic()
    pre_state = init_seed_repo(workspace)
    verification_cmd = [sys.executable, "-m", "pytest", "-q"]
    red = run_process(verification_cmd, workspace, timeout_seconds=timeout_seconds)
    write_text_atomic(out_dir / "direct-verification-before.txt", red.stdout + red.stderr, root=out_dir)
    transcript = out_dir / "direct-transcript.md"
    prompt = "Make the failing pytest check pass. Do not explain; edit the workspace."
    command = [
        codex,
        "exec",
        "--skip-git-repo-check",
        "--cd",
        str(workspace),
        "--sandbox",
        "workspace-write",
        "--output-last-message",
        str(transcript),
        "-",
    ]
    result = run_process(command, workspace, input_text=prompt, timeout_seconds=timeout_seconds)
    write_text_atomic(out_dir / "direct-codex-stdout.txt", result.stdout, root=out_dir)
    write_text_atomic(out_dir / "direct-codex-stderr.txt", result.stderr, root=out_dir)
    if not transcript.exists():
        write_text_atomic(transcript, result.stdout, root=out_dir)
    green = run_process(verification_cmd, workspace, timeout_seconds=timeout_seconds)
    write_text_atomic(out_dir / "direct-verification-after.txt", green.stdout + green.stderr, root=out_dir)
    blocked_by: list[dict[str, Any]] = []
    if codex_auth_failed(result):
        blocked_by.append({"code": "ERR_EXEC_BACKEND_AUTH", "message": "Codex CLI authentication failed"})
    elif result.returncode != 0:
        blocked_by.append({"code": "ERR_EXEC_BACKEND_FAILED", "message": f"codex-cli exited {result.returncode}"})
    post_state = {
        "head": git_text(["rev-parse", "HEAD"], workspace),
        "status": git_text(["status", "--short"], workspace),
        "diff_stat": git_text(["diff", "--stat"], workspace),
    }
    return {
        "mode": "direct-codex",
        "worktree": {"path": rel(workspace), "isolated": True, "pre_state": pre_state, "post_state": post_state},
        "verification": {
            "before": "green" if red.returncode == 0 else "red",
            "after": "green" if green.returncode == 0 else "red",
            "returncode": green.returncode,
            "passed": green.returncode == 0,
            "output_path": "direct-verification-after.txt",
        },
        "files_touched": touched_files(workspace),
        "transcript_path": "direct-transcript.md",
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "has_independent_review": False,
        "has_hash_bound_bundle": False,
        "legitimacy_verdict": None,
        "blocked_by": blocked_by,
        "command_hash": command_hash(command),
    }


def run_live(args: argparse.Namespace) -> dict[str, Any]:
    if not args.i_approve_live_codex:
        raise LiveProofError(
            "ERR_LIVE_PROOF_APPROVAL_REQUIRED",
            "live codex execution requires --i-approve-live-codex",
        )
    codex = shutil.which("codex")
    if codex is None:
        raise LiveProofError(
            "ERR_EXEC_BACKEND_UNAVAILABLE", "codex binary is not on PATH"
        )
    timeout_seconds = int(args.timeout_seconds)
    if timeout_seconds < 1 or timeout_seconds > 3600:
        raise LiveProofError(
            "ERR_LIVE_PROOF_TIMEOUT_INVALID",
            "timeout_seconds must be between 1 and 3600",
        )

    seed = resolve_repo_input(args.seed, code="ERR_LIVE_PROOF_SEED_INVALID")
    plan = resolve_repo_input(args.plan, code="ERR_LIVE_PROOF_PLAN_INVALID")
    out_dir = resolve_live_out(args.out)
    proof_id = out_dir.name
    prepare_owned_dir(out_dir, proof_id, source=plan, root=LIVE_PROOF_ROOT)
    workspace = out_dir / "workspace"
    safe_copy_seed(seed, workspace)
    pre_repo_state = repo_tracked_state()
    started = time.monotonic()
    pre_state = init_seed_repo(workspace)

    verification_cmd = [sys.executable, "-m", "pytest", "-q"]
    red = run_process(verification_cmd, workspace, timeout_seconds=timeout_seconds)
    write_text_atomic(
        out_dir / "verification-before.txt", red.stdout + red.stderr, root=out_dir
    )
    dirty_before_exec = git_text(["status", "--short"], workspace)
    if dirty_before_exec.strip():
        bundle = base_bundle(proof_id, seed_path=rel(seed))
        bundle.update(
            {
                "decision": "blocked",
                "blocked_by": [
                    {
                        "code": "ERR_EXEC_DIRTY_WORKTREE",
                        "message": "seed workspace became dirty before Codex execution",
                    }
                ],
                "worktree": {
                    "path": rel(workspace),
                    "isolated": True,
                    "pre_state": pre_state,
                    "post_state": {"status": dirty_before_exec},
                },
                "verification": {
                    "command": "python -m pytest -q",
                    "returncode": red.returncode,
                    "passed": False,
                    "before": "red",
                    "after": "not-run",
                    "output_path": "verification-before.txt",
                },
                "dogfood_comparison": {
                    "mode": "dwm-controlled",
                    "status": "blocked",
                    "metrics": {
                        "elapsed_seconds": 0.0,
                        "interruptions": 0,
                        "verification_passed": False,
                    },
                },
            }
        )
        write_bundle(out_dir, bundle)
        return bundle
    if red.returncode == 0:
        bundle = base_bundle(proof_id, seed_path=rel(seed))
        bundle.update(
            {
                "decision": "blocked",
                "blocked_by": [
                    {
                        "code": "ERR_LIVE_PROOF_RED_CHECK_NOT_RED",
                        "message": "seed verification passed before Codex ran",
                    }
                ],
                "worktree": {
                    "path": rel(workspace),
                    "isolated": True,
                    "pre_state": pre_state,
                    "post_state": {
                        "status": git_text(["status", "--short"], workspace)
                    },
                },
                "verification": {
                    "command": "python -m pytest -q",
                    "returncode": red.returncode,
                    "passed": False,
                    "before": "green",
                    "after": "not-run",
                    "output_path": "verification-before.txt",
                },
                "dogfood_comparison": {
                    "mode": "dwm-controlled",
                    "status": "blocked",
                    "metrics": {
                        "elapsed_seconds": 0.0,
                        "interruptions": 0,
                        "verification_passed": False,
                    },
                },
            }
        )
        write_bundle(out_dir, bundle)
        return bundle

    run_dir, compiled = compile_live_plan(plan, proof_id)
    packet_status = compiled["status"]["packet_statuses"][0]["status"]
    if packet_status != "ready":
        raise LiveProofError(
            "ERR_LIVE_PROOF_PACKET_NOT_READY",
            f"compiled packet status is {packet_status}",
            path=run_dir,
        )
    prompt = (run_dir / "packets" / "001-first-slice.prompt.md").read_text()
    transcript = out_dir / "transcript.md"
    command = [
        codex,
        "exec",
        "--skip-git-repo-check",
        "--cd",
        str(workspace),
        "--sandbox",
        "workspace-write",
        "--output-last-message",
        str(transcript),
        "-",
    ]
    result = run_process(
        command, workspace, input_text=prompt, timeout_seconds=timeout_seconds
    )
    write_text_atomic(out_dir / "codex-stdout.txt", result.stdout, root=out_dir)
    write_text_atomic(out_dir / "codex-stderr.txt", result.stderr, root=out_dir)
    if not transcript.exists():
        write_text_atomic(transcript, result.stdout, root=out_dir)

    green = run_process(verification_cmd, workspace, timeout_seconds=timeout_seconds)
    write_text_atomic(
        out_dir / "verification-after.txt", green.stdout + green.stderr, root=out_dir
    )
    post_state = {
        "head": git_text(["rev-parse", "HEAD"], workspace),
        "status": git_text(["status", "--short"], workspace),
        "diff_stat": git_text(["diff", "--stat"], workspace),
    }
    post_repo_state = repo_tracked_state()
    verification_passed = result.returncode == 0 and green.returncode == 0
    review = independent_review(
        seed, workspace, verification_passed=verification_passed
    )
    write_json_atomic(out_dir / "review.json", review, root=out_dir)
    blocked_by: list[dict[str, Any]] = []
    decision = "live-proof-pass" if verification_passed else "failed"
    if codex_auth_failed(result):
        decision = "blocked"
        blocked_by.append(
            {
                "code": "ERR_EXEC_BACKEND_AUTH",
                "message": "Codex CLI authentication failed",
            }
        )
    elif result.returncode != 0:
        blocked_by.append(
            {
                "code": "ERR_EXEC_BACKEND_FAILED",
                "message": f"codex-cli exited {result.returncode}",
            }
        )
    elif green.returncode != 0:
        blocked_by.append(
            {
                "code": "ERR_EXEC_VERIFY_FAILED",
                "message": "verification failed after Codex execution",
            }
        )
    elif review["decision"] != "approved":
        decision = "failed"
        blocked_by.append(
            {
                "code": "ERR_LIVE_PROOF_REVIEW_REJECTED",
                "message": "independent review did not approve the recorded change",
            }
        )

    elapsed = round(time.monotonic() - started, 3)
    bundle = {
        "proof_id": proof_id,
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "task": {
            "id": "live-proof-1",
            "seed_path": rel(seed),
            "objective": compiled["packet"]["objective"],
            "verification_command": "python -m pytest -q",
        },
        "backend": "codex-cli",
        "mode": "installed-codex",
        "model_provider": "codex-cli-default",
        "worktree": {
            "path": rel(workspace),
            "isolated": True,
            "pre_state": pre_state,
            "post_state": post_state,
        },
        "prompt_hash": compiled["packet"]["prompt_hash"],
        "packet_hash": compiled["packet_hash"],
        "adapter_hash": command_hash(command),
        "commands": [
            {"argv": command, "cwd": rel(workspace), "timeout_seconds": timeout_seconds}
        ],
        "files_touched": touched_files(workspace),
        "transcript_path": "transcript.md",
        "verification": {
            "command": "python -m pytest -q",
            "returncode": green.returncode,
            "passed": green.returncode == 0,
            "before": "red",
            "after": "green" if green.returncode == 0 else "red",
            "output_path": "verification-after.txt",
        },
        "review": review,
        "elapsed_seconds": elapsed,
        "interruptions": 0,
        "repo_tracked_diff_unchanged": pre_repo_state == post_repo_state,
        "dogfood_comparison": {
            "mode": "dwm-controlled",
            "status": "run" if decision != "blocked" else "blocked",
            "metrics": {
                "elapsed_seconds": elapsed,
                "interruptions": 0,
                "verification_passed": verification_passed,
            },
        },
        "decision": decision,
        "blocked_by": blocked_by,
        "claim_policy": CLAIM_POLICY,
        "source_hashes": {
            "seed": tree_hash(seed),
            "plan": canonical_hash(read_json(plan)),
            "packet": compiled["packet_hash"],
            "prompt": compiled["packet"]["prompt_hash"],
            "adapter": command_hash(command),
        },
    }
    write_bundle(out_dir, bundle)
    return bundle


def controlled_arm_from_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    verification = bundle.get("verification") if isinstance(bundle.get("verification"), dict) else {}
    review = bundle.get("review") if isinstance(bundle.get("review"), dict) else {}
    return {
        "mode": "dwm-controlled",
        "proof_ref": "dwm/live-proof.json",
        "decision": bundle.get("decision"),
        "verification": {
            "before": verification.get("before"),
            "after": verification.get("after"),
            "returncode": verification.get("returncode"),
            "passed": verification.get("passed"),
            "output_path": "dwm/verification-after.txt",
        },
        "files_touched": bundle.get("files_touched", []),
        "transcript_path": "dwm/transcript.md",
        "elapsed_seconds": bundle.get("elapsed_seconds"),
        "has_independent_review": True,
        "has_hash_bound_bundle": True,
        "legitimacy_verdict": {
            "decision": review.get("decision"),
            "checks": review.get("checks", {}),
            "reasons": review.get("reasons", []),
        },
        "blocked_by": bundle.get("blocked_by", []),
    }


def run_comparison(args: argparse.Namespace) -> dict[str, Any]:
    if not args.i_approve_live_codex:
        raise LiveProofError(
            "ERR_LIVE_PROOF_APPROVAL_REQUIRED",
            "live comparison requires --i-approve-live-codex",
        )
    codex = shutil.which("codex")
    if codex is None:
        raise LiveProofError("ERR_EXEC_BACKEND_UNAVAILABLE", "codex binary is not on PATH")
    timeout_seconds = int(args.timeout_seconds)
    if timeout_seconds < 1 or timeout_seconds > 3600:
        raise LiveProofError(
            "ERR_LIVE_PROOF_TIMEOUT_INVALID",
            "timeout_seconds must be between 1 and 3600",
        )
    seed = resolve_repo_input(args.seed, code="ERR_LIVE_PROOF_SEED_INVALID")
    plan = resolve_repo_input(args.plan, code="ERR_LIVE_PROOF_PLAN_INVALID")
    out_dir = resolve_live_out(args.out)
    comparison_id = out_dir.name
    prepare_owned_dir(out_dir, comparison_id, source=plan, root=LIVE_PROOF_ROOT)
    pre_repo_state = repo_tracked_state()
    direct = run_direct_arm(codex=codex, seed=seed, out_dir=out_dir, timeout_seconds=timeout_seconds)
    live_args = argparse.Namespace(
        seed=seed,
        plan=plan,
        out=out_dir / "dwm",
        timeout_seconds=timeout_seconds,
        i_approve_live_codex=True,
    )
    controlled_bundle = run_live(live_args)
    post_repo_state = repo_tracked_state()
    comparison = {
        "comparison_id": comparison_id,
        "schema_version": COMPARISON_SCHEMA_VERSION,
        "tool": TOOL,
        "task": {
            "id": "live-proof-1",
            "seed_path": rel(seed),
            "verification_command": "python -m pytest -q",
        },
        "arms": [direct, controlled_arm_from_bundle(controlled_bundle)],
        "differentiators": {
            "independent_legitimacy_review": "dwm-controlled only",
            "hash_bound_evidence_bundle": "dwm-controlled only",
        },
        "honest_conclusion": HONEST_CONCLUSION,
        "claim_policy": COMPARISON_CLAIM_POLICY,
        "repo_tracked_diff_unchanged": pre_repo_state == post_repo_state,
        "source_hashes": {
            "seed": tree_hash(seed),
            "plan": canonical_hash(read_json(plan)),
            "direct_adapter": direct.get("command_hash"),
            "dwm_bundle": canonical_hash(controlled_bundle),
        },
    }
    write_comparison(out_dir, comparison)
    return comparison


def inspect_proof(path: Path) -> dict[str, Any]:
    proof_dir = path.resolve(strict=False)
    comparison_path = proof_dir / "comparison.json" if proof_dir.is_dir() else proof_dir
    if comparison_path.is_file() and not comparison_path.is_symlink():
        comparison = read_json(comparison_path)
        errors = validate_comparison(comparison)
        return {
            "comparison_id": comparison.get("comparison_id"),
            "decision": "keep" if not errors else "adjust",
            "valid": not errors,
            "errors": errors,
            "arm_modes": [
                arm.get("mode")
                for arm in comparison.get("arms", [])
                if isinstance(arm, dict)
            ],
        }
    bundle_path = proof_dir / "live-proof.json" if proof_dir.is_dir() else proof_dir
    if not bundle_path.is_file() or bundle_path.is_symlink():
        raise LiveProofError(
            "ERR_LIVE_PROOF_INPUT_MISSING", "live-proof.json is missing", path=path
        )
    bundle = read_json(bundle_path)
    errors = validate_bundle(bundle)
    summary = {
        "proof_id": bundle.get("proof_id"),
        "decision": bundle.get("decision"),
        "valid": not errors,
        "errors": errors,
        "verification_passed": bundle.get("verification", {}).get("passed")
        if isinstance(bundle.get("verification"), dict)
        else None,
        "dogfood_status": bundle.get("dogfood_comparison", {}).get("status")
        if isinstance(bundle.get("dogfood_comparison"), dict)
        else None,
    }
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--out", type=Path)
    subparsers = parser.add_subparsers(dest="command")

    run = subparsers.add_parser("run")
    run.add_argument("--seed", type=Path, required=True)
    run.add_argument("--plan", type=Path, required=True)
    run.add_argument("--out", type=Path, required=True)
    run.add_argument("--timeout-seconds", type=int, default=120)
    run.add_argument("--i-approve-live-codex", action="store_true")

    compare = subparsers.add_parser("compare")
    compare.add_argument("--seed", type=Path, required=True)
    compare.add_argument("--plan", type=Path, required=True)
    compare.add_argument("--out", type=Path, required=True)
    compare.add_argument("--timeout-seconds", type=int, default=120)
    compare.add_argument("--i-approve-live-codex", action="store_true")

    inspect = subparsers.add_parser("inspect")
    inspect.add_argument("--proof", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        if args.self_test:
            self_test()
            print("live proof self-test: pass")
            return
        if args.manifest:
            if args.out is None:
                raise LiveProofError(
                    "ERR_LIVE_PROOF_OUT_REQUIRED", "--out is required with --manifest"
                )
            print(json.dumps(run_manifest(args.manifest, args.out), sort_keys=True))
            return
        if args.command == "run":
            bundle = run_live(args)
            print(
                json.dumps(
                    {"proof_id": bundle["proof_id"], "decision": bundle["decision"]},
                    sort_keys=True,
                )
            )
            return
        if args.command == "compare":
            comparison = run_comparison(args)
            errors = validate_comparison(comparison)
            print(
                json.dumps(
                    {
                        "comparison_id": comparison["comparison_id"],
                        "decision": "keep" if not errors else "adjust",
                        "valid": not errors,
                    },
                    sort_keys=True,
                )
            )
            return
        if args.command == "inspect":
            print(json.dumps(inspect_proof(args.proof), sort_keys=True))
            return
        raise LiveProofError(
            "ERR_LIVE_PROOF_COMMAND_REQUIRED",
            "use --self-test, --manifest, run, or inspect",
        )
    except (LiveProofError, subprocess.TimeoutExpired) as exc:
        if isinstance(exc, subprocess.TimeoutExpired):
            error = {"code": "ERR_LIVE_PROOF_TIMEOUT", "message": str(exc)}
        else:
            error = exc.to_record()
        print(json.dumps({"error": error}, sort_keys=True), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
