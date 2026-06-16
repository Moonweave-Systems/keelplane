#!/usr/bin/env python3
"""DWM product CLI for read-only status, doctor, and command discovery."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT_ROOT = ROOT / "out"
DEFAULT_RUN = OUT_ROOT / "v9" / "v32-semantic-dogfood"

RELEASE_COMMANDS = [
    "python scripts/quick_validate_skill.py .",
    "python scripts/quick_validate_skill.py --self-test",
    "python scripts/check_contract.py",
    "python scripts/check_contract.py --self-test",
    "python scripts/evaluate_plan.py --self-test",
    "python scripts/evaluate_plan.py --manifest fixtures/v0.5/manifest.json --out out/v0.5",
    "python scripts/compile_workflow.py --self-test",
    "python scripts/compile_workflow.py --manifest fixtures/v1/manifest.json --out out/v1/final",
    "python scripts/execute_packet.py --self-test",
    "python scripts/execute_packet.py --manifest fixtures/v2/manifest.json --out out/v2/final",
    "python scripts/execute_packet.py --manifest fixtures/v2.5/manifest.json --out out/v2.5/final",
    "python scripts/dwm_runner.py --self-test",
    "python scripts/dwm_runner.py --manifest fixtures/v13/manifest.json --out out/v13/final",
    "python scripts/dwm_runner.py session --self-test",
    "python scripts/dwm_runner.py --manifest fixtures/v14/manifest.json --out out/v13/v14-final",
    "python scripts/dwm_runner.py review --self-test",
    "python scripts/dwm_runner.py --manifest fixtures/v15/manifest.json --out out/v13/v15-final",
    "python scripts/dwm_runner.py fanout --self-test",
    "python scripts/dwm_runner.py --manifest fixtures/v16/manifest.json --out out/v13/v16-final",
    "python scripts/dwm_hud.py --self-test",
    "python scripts/dwm_hud.py --manifest fixtures/v17/manifest.json --out out/hud/v17-final",
    "python scripts/dwm_install.py --self-test",
    "python scripts/dwm_install.py --manifest fixtures/v18/manifest.json --out out/install/v18-final",
    "python scripts/dwm_adapters.py --self-test",
    "python scripts/dwm_adapters.py --manifest fixtures/v19/manifest.json --out out/adapters/v19-final",
    "python scripts/dwm_release.py --self-test",
    "python scripts/dwm_release.py --manifest fixtures/v20/manifest.json --out out/release/v20-final",
    "python scripts/run_workflow.py --self-test",
    "python scripts/run_workflow.py --manifest fixtures/v3/manifest.json --out out/v3/final",
    "python scripts/orchestrate_workflow.py --self-test",
    "python scripts/dispatch_worker.py --self-test",
    "python scripts/run_worker_result.py --self-test",
    "python scripts/review_worker_result.py --self-test",
    "python scripts/ingest_worker_review.py --self-test",
    "python scripts/dispatch_frontier.py --self-test",
    "python scripts/run_frontier_result.py --self-test",
    "python scripts/review_frontier_result.py --self-test",
    "python scripts/ingest_frontier_review.py --self-test",
    "python scripts/resolve_human_gate.py --self-test",
    "python scripts/dwm.py --self-test",
    "python scripts/check_whitespace.py .",
    "python scripts/check_release_text.py .",
    "python scripts/check_release_text.py --self-test",
]

DOGFOOD_COMMANDS = [
    "python scripts/review_frontier_result.py --result out/v7/v32-semantic-dogfood --out out/v7.5/v32-semantic-dogfood",
    "python scripts/review_frontier_result.py --resume out/v7.5/v32-semantic-dogfood",
    "python scripts/ingest_frontier_review.py --review out/v7.5/v32-semantic-dogfood --out out/v8/v32-semantic-dogfood",
    "python scripts/ingest_frontier_review.py --resume out/v8/v32-semantic-dogfood",
    "python scripts/resolve_human_gate.py --frontier out/v8/v32-semantic-dogfood --approval fixtures/v9/approvals/dogfood-human-approval.json --out out/v9/v32-semantic-dogfood",
    "python scripts/resolve_human_gate.py --resume out/v9/v32-semantic-dogfood",
]

PRODUCT_COMMANDS = [
    "python scripts/dwm.py status --run out/v9/v32-semantic-dogfood --json",
    "python scripts/dwm.py next --run out/v9/v32-semantic-dogfood --json",
    "python scripts/dwm.py doctor --json",
    "python scripts/dwm.py commands --kind product --json",
]

BASE_REQUIRED_PATHS = [
    "SKILL.md",
    "README.md",
    "docs/automation-roadmap.md",
    "docs/v10-product-packaging-spec.md",
    "docs/v10-product-packaging.workflow.plan.json",
    "docs/v10-decision.md",
    "docs/v11-operator-guidance-spec.md",
    "docs/v11-operator-guidance.workflow.plan.json",
    "docs/v11-decision.md",
    "docs/v13-decision.md",
    "docs/v14-decision.md",
    "docs/v15-decision.md",
    "docs/v16-decision.md",
    "docs/v17-decision.md",
    "docs/v18-decision.md",
    "docs/v19-decision.md",
    "docs/v20-decision.md",
    "docs/v20-compatibility-matrix.md",
    "docs/v20-migration-rollback.md",
    "packaging/dwm-adapters.json",
    "packaging/dwm-package.json",
    "scripts/dwm.py",
    "scripts/dwm_runner.py",
    "scripts/dwm_hud.py",
    "scripts/dwm_install.py",
    "scripts/dwm_adapters.py",
    "scripts/dwm_release.py",
]


class DwmError(ValueError):
    """Structured product CLI error."""

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


def canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_hash(data: Any) -> str:
    return hashlib.sha256(canonical_json(data).encode("utf-8")).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def rel(path: Path) -> str:
    resolved = path.resolve(strict=False)
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return str(resolved)


def reject_traversal(path: Path, code: str, message: str) -> None:
    if any(part == ".." for part in path.parts):
        raise DwmError(code, message, path=path)


def check_components_not_symlink(path: Path) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise DwmError("ERR_DWM_PATH_SYMLINK", "run path contains a symlink", path=current)


def resolve_out_run(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, "ERR_DWM_OUTSIDE_OUT", "run path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    out_resolved = OUT_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(out_resolved)
    except ValueError as exc:
        raise DwmError("ERR_DWM_OUTSIDE_OUT", "run path must resolve under repo-local out/", path=value) from exc
    if resolved == out_resolved:
        raise DwmError("ERR_DWM_OUTSIDE_OUT", "run path must name a versioned run directory", path=value)
    check_components_not_symlink(candidate)
    return resolved


def read_json_obj(path: Path, *, label: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise DwmError("ERR_DWM_ARTIFACT_MISSING", f"{label} is missing or symlinked", path=path)
    try:
        data = json.loads(path.read_text())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DwmError("ERR_DWM_ARTIFACT_MALFORMED", f"{label} is malformed: {exc}", path=path) from exc
    if not isinstance(data, dict):
        raise DwmError("ERR_DWM_ARTIFACT_MALFORMED", f"{label} root must be an object", path=path)
    return data


def read_text_file(path: Path, *, label: str) -> str:
    if not path.is_file() or path.is_symlink():
        raise DwmError("ERR_DWM_ARTIFACT_MISSING", f"{label} is missing or symlinked", path=path)
    try:
        return path.read_text()
    except UnicodeDecodeError as exc:
        raise DwmError("ERR_DWM_ARTIFACT_MALFORMED", f"{label} is not UTF-8 text", path=path) from exc


def detect_version(run_dir: Path) -> str:
    parent = run_dir.parent.name
    if re.fullmatch(r"v[0-9]+(?:\.[0-9]+)?", parent):
        return parent
    raise DwmError("ERR_DWM_UNKNOWN_RUN_LAYOUT", "run path must be under out/v<number>/", path=run_dir)


def status_summary(run_dir: Path) -> dict[str, Any]:
    run_dir = resolve_out_run(run_dir)
    status = read_json_obj(run_dir / "status.json", label="status.json")
    run = read_json_obj(run_dir / "run.json", label="run.json") if (run_dir / "run.json").exists() else {}
    return {
        "schema_version": "1.0",
        "tool": "dwm.py",
        "run_path": rel(run_dir),
        "version": detect_version(run_dir),
        "run_id": status.get("run_id", run_dir.name),
        "status": status.get("status"),
        "resume_state": status.get("resume_state"),
        "state_path": status.get("state_path"),
        "completed_phase_ids": status.get("completed_phase_ids", []),
        "reviewed_phase_ids": status.get("reviewed_phase_ids", []),
        "human_approved_phase_ids": status.get("human_approved_phase_ids", []),
        "ready_phase_ids": status.get("ready_phase_ids", []),
        "selected_phase_ids": status.get("selected_phase_ids", []),
        "invalidators": status.get("invalidators", []),
        "snapshots": status.get("snapshots", {}),
        "source_paths": {
            "run": rel(run_dir / "run.json") if (run_dir / "run.json").exists() else None,
            "status": rel(run_dir / "status.json"),
            "state": rel(run_dir / str(status.get("state_path"))) if isinstance(status.get("state_path"), str) else None,
            "resume": rel(run_dir / "resume.md") if (run_dir / "resume.md").exists() else None,
        },
        "run_created_at": run.get("created_at"),
    }


def require_hash_match(hashes: dict[str, Any], key: str, actual: str, path: Path) -> None:
    expected = hashes.get(key)
    if not isinstance(expected, str):
        raise DwmError("ERR_DWM_HASH_LEDGER_MALFORMED", f"hashes.json is missing {key}", path=path)
    if expected != actual:
        raise DwmError("ERR_DWM_HASH_LEDGER_STALE", f"hashes.json {key} does not match current artifact", path=path)


def validate_packet_hash_maps(run_dir: Path, hashes: dict[str, Any]) -> int:
    verified = 0
    packet_hashes = hashes.get("packet_hashes")
    prompt_hashes = hashes.get("prompt_hashes")
    if packet_hashes is None and prompt_hashes is None:
        return verified
    if not isinstance(packet_hashes, dict) or not isinstance(prompt_hashes, dict):
        raise DwmError("ERR_DWM_HASH_LEDGER_MALFORMED", "packet or prompt hash map is malformed", path=run_dir / "hashes.json")

    packet_dir = run_dir / "packets"
    packet_files = sorted(packet_dir.glob("*.packet.json"))
    packets_by_id: dict[str, tuple[Path, dict[str, Any]]] = {}
    for packet_path in packet_files:
        packet = read_json_obj(packet_path, label=rel(packet_path))
        packet_id = packet.get("packet_id")
        if isinstance(packet_id, str):
            packets_by_id[packet_id] = (packet_path, packet)

    for packet_id, expected_hash in packet_hashes.items():
        if not isinstance(packet_id, str) or not isinstance(expected_hash, str):
            raise DwmError("ERR_DWM_HASH_LEDGER_MALFORMED", "packet hash map contains a malformed entry", path=run_dir / "hashes.json")
        packet_path, packet = packets_by_id.get(packet_id, (None, None))  # type: ignore[assignment]
        if packet_path is None or packet is None:
            raise DwmError("ERR_DWM_ARTIFACT_MISSING", f"packet {packet_id} is missing", path=packet_dir)
        if canonical_hash(packet) != expected_hash:
            raise DwmError("ERR_DWM_HASH_LEDGER_STALE", f"packet hash for {packet_id} does not match current artifact", path=packet_path)
        verified += 1
        prompt_path = packet_path.with_name(packet_path.name.replace(".packet.json", ".prompt.md"))
        expected_prompt_hash = prompt_hashes.get(packet_id)
        if not isinstance(expected_prompt_hash, str):
            raise DwmError("ERR_DWM_HASH_LEDGER_MALFORMED", f"prompt hash for {packet_id} is missing", path=run_dir / "hashes.json")
        if sha256_text(read_text_file(prompt_path, label=rel(prompt_path))) != expected_prompt_hash:
            raise DwmError("ERR_DWM_HASH_LEDGER_STALE", f"prompt hash for {packet_id} does not match current artifact", path=prompt_path)
        verified += 1
    return verified


def validate_hash_ledger(run_dir: Path, status: dict[str, Any], hashes: dict[str, Any]) -> int:
    snapshots = status.get("snapshots")
    if snapshots != hashes:
        raise DwmError("ERR_DWM_HASH_LEDGER_STALE", "status snapshots do not match hashes.json", path=run_dir / "status.json")

    verified = 0
    json_hash_files = {
        "result_hash": "result.json",
        "review_hash": "review.json",
        "run_hash": "run.json",
        "state_hash": "state.json",
        "journal_hash": "journal/0000.json",
    }
    text_hash_files = {
        "stdout_hash": "stdout.txt",
        "stderr_hash": "stderr.txt",
        "review_markdown_hash": "review.md",
        "approval_markdown_hash": "human-approval.md",
    }

    for key, relative in json_hash_files.items():
        if key in hashes:
            path = run_dir / relative
            require_hash_match(hashes, key, canonical_hash(read_json_obj(path, label=relative)), path)
            verified += 1
    for key, relative in text_hash_files.items():
        if key in hashes:
            path = run_dir / relative
            require_hash_match(hashes, key, sha256_text(read_text_file(path, label=relative)), path)
            verified += 1
    for key in sorted(hashes):
        if key.startswith("output:"):
            output_name = key.removeprefix("output:")
            if "/" in output_name or output_name in {"", ".", ".."}:
                raise DwmError("ERR_DWM_HASH_LEDGER_MALFORMED", f"output hash key is malformed: {key}", path=run_dir / "hashes.json")
            path = run_dir / "work" / output_name
            require_hash_match(hashes, key, sha256_text(read_text_file(path, label=rel(path))), path)
            verified += 1

    verified += validate_packet_hash_maps(run_dir, hashes)
    if verified == 0:
        raise DwmError("ERR_DWM_HASH_LEDGER_MALFORMED", "hashes.json has no locally verifiable entries", path=run_dir / "hashes.json")
    return verified


def check_path(path_text: str) -> dict[str, Any]:
    path = ROOT / path_text
    if path_text.startswith("out/"):
        if not path.exists() or path.is_symlink() or not path.is_dir():
            return {
                "id": f"path:{path_text}",
                "ok": False,
                "path": path_text,
                "message": "missing, symlinked, or not a directory",
            }
        try:
            status = read_json_obj(path / "status.json", label=f"{path_text}/status.json")
            hashes = read_json_obj(path / "hashes.json", label=f"{path_text}/hashes.json")
            verified = validate_hash_ledger(path, status, hashes)
        except DwmError as exc:
            return {
                "id": f"path:{path_text}",
                "ok": False,
                "path": path_text,
                "message": exc.message,
            }
        return {
            "id": f"path:{path_text}",
            "ok": True,
            "path": path_text,
            "message": f"status.json and hashes.json verified ({verified} artifact hashes)",
        }
    ok = path.exists() and not path.is_symlink()
    return {
        "id": f"path:{path_text}",
        "ok": ok,
        "path": path_text,
        "message": "present" if ok else "missing or symlinked",
    }


def run_trust_summary(run_dir: Path) -> dict[str, Any]:
    run_dir = resolve_out_run(run_dir)
    checks: list[dict[str, Any]] = []
    try:
        status = read_json_obj(run_dir / "status.json", label="status.json")
        checks.append({"id": "status-json", "ok": True, "path": rel(run_dir / "status.json"), "message": "present"})
    except DwmError as exc:
        checks.append({"id": "status-json", "ok": False, "path": rel(run_dir / "status.json"), "message": exc.message})
        return {"trusted": False, "checks": checks, "verified_artifact_hashes": 0}

    hashes_path = run_dir / "hashes.json"
    if hashes_path.exists():
        try:
            hashes = read_json_obj(hashes_path, label="hashes.json")
            verified = validate_hash_ledger(run_dir, status, hashes)
            checks.append(
                {
                    "id": "hash-ledger",
                    "ok": True,
                    "path": rel(hashes_path),
                    "message": f"verified {verified} artifact hashes",
                }
            )
            return {"trusted": True, "checks": checks, "verified_artifact_hashes": verified}
        except DwmError as exc:
            checks.append({"id": "hash-ledger", "ok": False, "path": rel(hashes_path), "message": exc.message})
            return {"trusted": False, "checks": checks, "verified_artifact_hashes": 0}

    checks.append({"id": "hash-ledger", "ok": False, "path": rel(hashes_path), "message": "missing hashes.json"})
    return {"trusted": False, "checks": checks, "verified_artifact_hashes": 0}


def recommended_action(summary: dict[str, Any], trust: dict[str, Any]) -> dict[str, Any]:
    invalidators = summary.get("invalidators", [])
    selected = summary.get("selected_phase_ids", [])
    status = summary.get("status")
    resume_state = summary.get("resume_state")
    run_path = str(summary.get("run_path", ""))
    if not trust.get("trusted"):
        return {
            "action": "repair-required",
            "summary": "Run artifacts are not trusted; inspect invalidators and regenerate from the prior trusted stage.",
            "requires_user_approval": True,
            "safe_default": "stop before executing or ingesting this run",
            "commands": [],
            "blocked_by": ["untrusted-artifacts"],
        }
    if invalidators or status == "invalid" or resume_state == "invalidated":
        return {
            "action": "repair-required",
            "summary": "The run is invalidated; do not advance it until the stale or malformed artifact is repaired.",
            "requires_user_approval": True,
            "safe_default": "stop and inspect status invalidators",
            "commands": [],
            "blocked_by": [str(item.get("code", "invalidator")) for item in invalidators if isinstance(item, dict)] or ["invalid-run"],
        }
    if status == "workflow-complete":
        return {
            "action": "complete",
            "summary": "The workflow is complete; no next workflow action is required for this run.",
            "requires_user_approval": False,
            "safe_default": "archive evidence or start a new workflow",
            "commands": [f"python scripts/dwm.py doctor --run {run_path} --json"],
            "blocked_by": [],
        }
    if isinstance(selected, list) and "human_gate" in selected:
        return {
            "action": "human-approval-required",
            "summary": "The next selected phase is a human gate; collect a tracked approval artifact before advancing.",
            "requires_user_approval": True,
            "safe_default": "stop before approval or execution",
            "commands": [],
            "blocked_by": ["human_gate"],
        }
    if isinstance(selected, list) and selected:
        return {
            "action": "next-phase-ready",
            "summary": "The run has selected phases ready for the next controlled dispatch step.",
            "requires_user_approval": False,
            "safe_default": "dispatch only through the matching deterministic adapter",
            "commands": [f"python scripts/dwm.py status --run {run_path} --json"],
            "blocked_by": ["adapter-selection-required"],
        }
    return {
        "action": "inspect",
        "summary": "No selected next phase is recorded; inspect status and resume artifacts before deciding.",
        "requires_user_approval": False,
        "safe_default": "inspect before advancing",
        "commands": [f"python scripts/dwm.py status --run {run_path} --json"],
        "blocked_by": [],
    }


def next_summary(run_dir: Path) -> dict[str, Any]:
    summary = status_summary(run_dir)
    trust = run_trust_summary(run_dir)
    action = recommended_action(summary, trust)
    return {
        "schema_version": "1.0",
        "tool": "dwm.py",
        "run_path": summary["run_path"],
        "version": summary["version"],
        "run_id": summary["run_id"],
        "status": summary["status"],
        "resume_state": summary["resume_state"],
        "trusted": trust["trusted"],
        "trust_checks": trust["checks"],
        "verified_artifact_hashes": trust["verified_artifact_hashes"],
        "selected_phase_ids": summary["selected_phase_ids"],
        "human_approved_phase_ids": summary["human_approved_phase_ids"],
        "invalidators": summary["invalidators"],
        "recommendation": action,
    }


def advertised_command_paths() -> list[str]:
    paths: set[str] = set(BASE_REQUIRED_PATHS)
    for command in [*RELEASE_COMMANDS, *DOGFOOD_COMMANDS, *PRODUCT_COMMANDS]:
        for token in shlex.split(command):
            if token.startswith("scripts/") and token.endswith(".py"):
                paths.add(token)
            elif token.startswith("fixtures/") and token.endswith(".json"):
                paths.add(token)
    for command in DOGFOOD_COMMANDS:
        for token in shlex.split(command):
            if token.startswith("out/"):
                paths.add(token)
    return sorted(paths)


def doctor_summary(run_dir: Path = DEFAULT_RUN) -> dict[str, Any]:
    checks = [check_path(path) for path in advertised_command_paths()]
    final_status: dict[str, Any] | None = None
    try:
        final_status = status_summary(run_dir)
        checks.append(
            {
                "id": "dogfood:workflow-complete",
                "ok": final_status.get("status") == "workflow-complete",
                "path": rel(resolve_out_run(run_dir) / "status.json"),
                "message": str(final_status.get("status")),
            }
        )
        checks.append(
            {
                "id": "dogfood:human-gate-approved",
                "ok": final_status.get("human_approved_phase_ids") == ["human_gate"],
                "path": rel(resolve_out_run(run_dir) / "status.json"),
                "message": ",".join(str(item) for item in final_status.get("human_approved_phase_ids", [])),
            }
        )
    except DwmError as exc:
        checks.append({"id": "dogfood:status-readable", "ok": False, "path": rel(resolve_out_run(run_dir)), "message": exc.message})
    ok = all(bool(check.get("ok")) for check in checks)
    return {
        "schema_version": "1.0",
        "tool": "dwm.py",
        "ok": ok,
        "checks": checks,
        "final_status": final_status,
        "release_commands": RELEASE_COMMANDS,
        "dogfood_commands": DOGFOOD_COMMANDS,
        "product_commands": PRODUCT_COMMANDS,
    }


def command_summary(kind: str) -> dict[str, Any]:
    commands: dict[str, list[str]] = {}
    if kind in {"all", "release"}:
        commands["release"] = RELEASE_COMMANDS
    if kind in {"all", "dogfood"}:
        commands["dogfood"] = DOGFOOD_COMMANDS
    if kind in {"all", "product"}:
        commands["product"] = PRODUCT_COMMANDS
    return {"schema_version": "1.0", "tool": "dwm.py", "commands": commands}


def print_text_status(summary: dict[str, Any]) -> None:
    print(f"DWM run: {summary['run_path']}")
    print(f"Version: {summary['version']}")
    print(f"Status: {summary['status']}")
    print(f"Resume: {summary['resume_state']}")
    print(f"Completed: {', '.join(str(item) for item in summary['completed_phase_ids']) or 'none'}")
    print(f"Selected: {', '.join(str(item) for item in summary['selected_phase_ids']) or 'none'}")
    print(f"Human approved: {', '.join(str(item) for item in summary['human_approved_phase_ids']) or 'none'}")
    if summary["invalidators"]:
        print("Invalidators:")
        for item in summary["invalidators"]:
            print(f"- {item.get('code')}: {item.get('message')}")


def print_text_doctor(summary: dict[str, Any]) -> None:
    print(f"DWM doctor: {'ok' if summary['ok'] else 'failed'}")
    for check in summary["checks"]:
        marker = "ok" if check["ok"] else "fail"
        print(f"- {marker}: {check['id']} ({check['message']})")


def print_text_commands(summary: dict[str, Any]) -> None:
    for group, commands in summary["commands"].items():
        print(f"{group}:")
        for command in commands:
            print(f"  {command}")


def print_text_next(summary: dict[str, Any]) -> None:
    recommendation = summary["recommendation"]
    print(f"DWM next: {recommendation['action']}")
    print(f"Run: {summary['run_path']}")
    print(f"Trusted: {'yes' if summary['trusted'] else 'no'}")
    print(f"Status: {summary['status']}")
    print(f"Summary: {recommendation['summary']}")
    if recommendation["commands"]:
        print("Commands:")
        for command in recommendation["commands"]:
            print(f"  {command}")
    if recommendation["blocked_by"]:
        print(f"Blocked by: {', '.join(str(item) for item in recommendation['blocked_by'])}")


def self_test() -> None:
    summary = status_summary(DEFAULT_RUN)
    if summary["status"] != "workflow-complete":
        raise DwmError("ERR_DWM_SELF_TEST_FAILED", "canonical dogfood run should be workflow-complete", path=DEFAULT_RUN)
    if summary["human_approved_phase_ids"] != ["human_gate"]:
        raise DwmError("ERR_DWM_SELF_TEST_FAILED", "canonical dogfood run should record human_gate approval", path=DEFAULT_RUN)
    doctor = doctor_summary(DEFAULT_RUN)
    if not doctor["ok"]:
        raise DwmError("ERR_DWM_SELF_TEST_FAILED", "doctor should pass for the canonical repo state", path=DEFAULT_RUN)
    if "python scripts/dwm.py --self-test" not in doctor["release_commands"]:
        raise DwmError("ERR_DWM_SELF_TEST_FAILED", "release commands should include DWM self-test")
    checked_paths = {str(check["path"]) for check in doctor["checks"] if str(check.get("id", "")).startswith("path:")}
    missing_advertised = [path for path in advertised_command_paths() if path not in checked_paths]
    if missing_advertised:
        raise DwmError("ERR_DWM_SELF_TEST_FAILED", "doctor should check every advertised command path", path=missing_advertised[0])
    out_checks = [check for check in doctor["checks"] if str(check.get("id", "")).startswith("path:out/")]
    if not out_checks or not all("verified" in str(check.get("message", "")) for check in out_checks):
        raise DwmError("ERR_DWM_SELF_TEST_FAILED", "doctor should verify dogfood hash ledgers", path=DEFAULT_RUN)
    next_step = next_summary(DEFAULT_RUN)
    if next_step["recommendation"]["action"] != "complete" or not next_step["trusted"]:
        raise DwmError("ERR_DWM_SELF_TEST_FAILED", "canonical dogfood next action should be trusted complete", path=DEFAULT_RUN)
    product_commands = command_summary("product")["commands"].get("product", [])
    if "python scripts/dwm.py next --run out/v9/v32-semantic-dogfood --json" not in product_commands:
        raise DwmError("ERR_DWM_SELF_TEST_FAILED", "product commands should include DWM next")
    inspect_action = recommended_action(
        {"run_path": "out/v5/example", "status": "executed", "resume_state": "resumable", "selected_phase_ids": [], "invalidators": []},
        {"trusted": True},
    )
    if inspect_action["commands"] != ["python scripts/dwm.py status --run out/v5/example --json"]:
        raise DwmError("ERR_DWM_SELF_TEST_FAILED", "inspect recommendation should stay bound to the inspected run")
    ready_action = recommended_action(
        {"run_path": "out/v6/example", "status": "frontier-ready", "resume_state": "resumable", "selected_phase_ids": ["release_decision"], "invalidators": []},
        {"trusted": True},
    )
    if ready_action["commands"] != ["python scripts/dwm.py status --run out/v6/example --json"] or "adapter-selection-required" not in ready_action["blocked_by"]:
        raise DwmError("ERR_DWM_SELF_TEST_FAILED", "ready recommendation should avoid canonical dogfood commands")
    canonical_status = read_json_obj(DEFAULT_RUN / "status.json", label="canonical status.json")
    canonical_hashes = read_json_obj(DEFAULT_RUN / "hashes.json", label="canonical hashes.json")
    tampered_hashes = dict(canonical_hashes)
    tampered_hashes["state_hash"] = "0" * 64
    try:
        validate_hash_ledger(DEFAULT_RUN, canonical_status, tampered_hashes)
    except DwmError as exc:
        if exc.code != "ERR_DWM_HASH_LEDGER_STALE":
            raise
    else:
        raise DwmError("ERR_DWM_SELF_TEST_FAILED", "tampered hash ledger should be rejected", path=DEFAULT_RUN / "hashes.json")
    try:
        status_summary(ROOT / "README.md")
    except DwmError as exc:
        if exc.code != "ERR_DWM_OUTSIDE_OUT":
            raise
    else:
        raise DwmError("ERR_DWM_SELF_TEST_FAILED", "outside-out status path should be rejected")
    try:
        detect_version(OUT_ROOT / "tmp" / "run")
    except DwmError as exc:
        if exc.code != "ERR_DWM_UNKNOWN_RUN_LAYOUT":
            raise
    else:
        raise DwmError("ERR_DWM_SELF_TEST_FAILED", "unknown run layout should be rejected")
    try:
        read_json_obj(ROOT / "README.md", label="malformed json fixture")
    except DwmError as exc:
        if exc.code != "ERR_DWM_ARTIFACT_MALFORMED":
            raise
    else:
        raise DwmError("ERR_DWM_SELF_TEST_FAILED", "malformed JSON should be rejected", path=ROOT / "README.md")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="run CLI self-tests")
    subparsers = parser.add_subparsers(dest="command")

    status = subparsers.add_parser("status", help="summarize one DWM run directory")
    status.add_argument("--run", default=str(DEFAULT_RUN), help="run directory under out/")
    status.add_argument("--json", action="store_true", help="emit stable JSON")

    doctor = subparsers.add_parser("doctor", help="check the repo-local DWM product surface")
    doctor.add_argument("--run", default=str(DEFAULT_RUN), help="canonical final run directory under out/")
    doctor.add_argument("--json", action="store_true", help="emit stable JSON")

    next_parser = subparsers.add_parser("next", help="recommend the next safe operator action for one run")
    next_parser.add_argument("--run", default=str(DEFAULT_RUN), help="run directory under out/")
    next_parser.add_argument("--json", action="store_true", help="emit stable JSON")

    commands = subparsers.add_parser("commands", help="print release or dogfood commands")
    commands.add_argument("--kind", choices=["all", "release", "dogfood", "product"], default="all")
    commands.add_argument("--json", action="store_true", help="emit stable JSON")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if args.self_test:
            self_test()
            print("dwm self-test: pass")
            return 0
        if args.command == "status":
            summary = status_summary(Path(args.run))
            if args.json:
                print(canonical_json(summary))
            else:
                print_text_status(summary)
            return 0 if summary.get("status") not in {None, "invalid"} else 1
        if args.command == "doctor":
            summary = doctor_summary(Path(args.run))
            if args.json:
                print(canonical_json(summary))
            else:
                print_text_doctor(summary)
            return 0 if summary["ok"] else 1
        if args.command == "next":
            summary = next_summary(Path(args.run))
            if args.json:
                print(canonical_json(summary))
            else:
                print_text_next(summary)
            return 0 if summary["trusted"] and summary["recommendation"]["action"] != "repair-required" else 1
        if args.command == "commands":
            summary = command_summary(args.kind)
            if args.json:
                print(canonical_json(summary))
            else:
                print_text_commands(summary)
            return 0
        raise DwmError("ERR_DWM_ARGUMENTS", "expected --self-test, status, doctor, or commands")
    except DwmError as exc:
        print(canonical_json(exc.to_record()), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
