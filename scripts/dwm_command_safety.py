#!/usr/bin/env python3
"""Shared command safety checks for DWM planning artifacts."""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


GATED_RISK_CODES = {
    "database",
    "delete",
    "dependency",
    "deploy",
    "external-message",
    "history-rewrite",
    "network",
    "secret",
    "secrets",
    "write",
}

PYTHON_BINARIES = {"python", "python3"}

SAFE_SCRIPT_PATHS = {
    "scripts/dwm.py",
    "scripts/dwm_brand_boundary_audit.py",
    "scripts/dwm_control_deck_score.py",
    "scripts/dwm_control_deck_score_history.py",
    "scripts/dwm_dogfood_acquire.py",
    "scripts/dwm_metric_ladder.py",
    "scripts/dwm_benchmark_readiness.py",
    "scripts/dwm_wave_operator.py",
    "scripts/dwm_evidence_oracle.py",
    "scripts/dwm_large_workflow_dogfood.py",
    "scripts/dwm_large_workflow_next.py",
    "scripts/dwm_roadmap_reconciliation.py",
    "scripts/dwm_workflow_narrative.py",
    "scripts/dwm_workflow_activation.py",
    "scripts/dwm_workflow_queue.py",
}

SCRIPT_RISK_CODES = {
    "scripts/dwm_runner.py": ["write"],
    "scripts/execute_packet.py": ["write"],
}

NETWORK_MARKERS = ("http://", "https://", "ssh://", "git@", "api.")
SECRET_MARKERS = ("secret", "token", "credential", "password", "apikey", "api_key")
DELETE_MARKERS = ("rm", "rmdir", "unlink", "delete", "--delete", "shutil.rmtree")
DEPLOY_MARKERS = ("deploy", "publish", "release-upload")
HISTORY_MARKERS = ("reset", "rebase", "force-push", "--force")
DEPENDENCY_MARKERS = ("pip", "npm", "pnpm", "yarn", "brew", "uv", "poetry", "gem")


@dataclass(frozen=True)
class CommandSafety:
    command: str
    supported: bool
    declared_risk_codes: list[str]
    inferred_risk_codes: list[str]
    effective_risk_codes: list[str]
    gated_risk_codes: list[str]
    blocked_by: list[dict[str, Any]]

    def to_record(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "supported": self.supported,
            "declared_risk_codes": self.declared_risk_codes,
            "inferred_risk_codes": self.inferred_risk_codes,
            "effective_risk_codes": self.effective_risk_codes,
            "gated_risk_codes": self.gated_risk_codes,
            "blocked_by": self.blocked_by,
        }


def normalize_risk_codes(value: Any) -> tuple[list[str], list[dict[str, Any]]]:
    if not isinstance(value, list) or not value:
        return [], [{"code": "ERR_DWM_COMMAND_RISK_CODES_INVALID", "message": "risk_codes must be a non-empty list of strings"}]
    invalid = [item for item in value if not isinstance(item, str) or not item.strip()]
    if invalid:
        return [], [{"code": "ERR_DWM_COMMAND_RISK_CODES_INVALID", "message": "risk_codes must be a non-empty list of strings"}]
    return sorted(dict.fromkeys(item.strip() for item in value)), []


def parse_command(command: str) -> tuple[list[str], list[dict[str, Any]]]:
    if not isinstance(command, str) or not command.strip():
        return [], [{"code": "ERR_DWM_COMMAND_MISSING", "message": "command is required"}]
    try:
        parts = shlex.split(command)
    except ValueError as exc:
        return [], [{"code": "ERR_DWM_COMMAND_PARSE_FAILED", "message": str(exc)}]
    if not parts:
        return [], [{"code": "ERR_DWM_COMMAND_MISSING", "message": "command is required"}]
    return parts, []


def normalize_script_path(value: str) -> str:
    path = Path(value)
    return path.as_posix()


def infer_text_risks(parts: list[str]) -> list[str]:
    risks: set[str] = set()
    lowered = [part.lower() for part in parts]
    joined = " ".join(lowered)
    if any(marker in joined for marker in NETWORK_MARKERS):
        risks.add("network")
    if any(marker in joined for marker in SECRET_MARKERS):
        risks.add("secrets")
    if any(part in DELETE_MARKERS for part in lowered):
        risks.add("delete")
    if any(marker in joined for marker in DEPLOY_MARKERS):
        risks.add("deploy")
    if any(marker in joined for marker in HISTORY_MARKERS):
        risks.add("history-rewrite")
    if any(part in DEPENDENCY_MARKERS for part in lowered):
        risks.add("dependency")
    return sorted(risks)


def assess_command_safety(command: str, declared_risk_codes: Any) -> CommandSafety:
    declared, blockers = normalize_risk_codes(declared_risk_codes)
    parts, parse_blockers = parse_command(command)
    blockers.extend(parse_blockers)
    inferred: set[str] = set()
    supported = False

    if parts:
        executable = Path(parts[0]).name
        script_path = normalize_script_path(parts[1]) if len(parts) > 1 else ""
        if executable not in PYTHON_BINARIES or not script_path.startswith("scripts/") or not script_path.endswith(".py"):
            blockers.append(
                {
                    "code": "ERR_DWM_COMMAND_UNSUPPORTED",
                    "message": "command must use a supported python scripts/*.py entrypoint",
                    "command": command,
                }
            )
        elif script_path in SAFE_SCRIPT_PATHS:
            supported = True
        elif script_path in SCRIPT_RISK_CODES:
            supported = True
            inferred.update(SCRIPT_RISK_CODES[script_path])
        else:
            blockers.append(
                {
                    "code": "ERR_DWM_COMMAND_SCRIPT_NOT_ALLOWLISTED",
                    "message": "script is not allowlisted for automatic command planning",
                    "script": script_path,
                }
            )
        inferred.update(infer_text_risks(parts))

    inferred_sorted = sorted(inferred)
    effective = sorted(set(declared) | inferred)
    gated = sorted(set(effective) & GATED_RISK_CODES)
    return CommandSafety(
        command=command,
        supported=supported,
        declared_risk_codes=declared,
        inferred_risk_codes=inferred_sorted,
        effective_risk_codes=effective,
        gated_risk_codes=gated,
        blocked_by=blockers,
    )


def read_json(path: Path) -> Any:
    with path.open() as handle:
        return json.load(handle)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def fixture_status(fixture: dict[str, Any]) -> dict[str, Any]:
    fixture_id = str(fixture.get("id", "fixture"))
    safety = assess_command_safety(str(fixture.get("command", "")), fixture.get("risk_codes"))
    expected_supported = fixture.get("expected_supported")
    expected_gated = fixture.get("expected_gated_risk_codes")
    expected_blocked_codes = fixture.get("expected_blocked_codes")
    errors: list[str] = []
    if expected_supported is not None and bool(expected_supported) != safety.supported:
        errors.append(f"expected supported={expected_supported}, got {safety.supported}")
    if expected_gated is not None and list(expected_gated) != safety.gated_risk_codes:
        errors.append(f"expected gated {expected_gated}, got {safety.gated_risk_codes}")
    if expected_blocked_codes is not None:
        actual_codes = [str(blocker.get("code")) for blocker in safety.blocked_by]
        if list(expected_blocked_codes) != actual_codes:
            errors.append(f"expected blockers {expected_blocked_codes}, got {actual_codes}")
    return {
        "id": fixture_id,
        "required": bool(fixture.get("required", True)),
        "status": "pass" if not errors else "fail",
        "command_safety": safety.to_record(),
        "error": "; ".join(errors) if errors else None,
    }


def run_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    fixtures = manifest.get("fixtures")
    if not isinstance(fixtures, list):
        raise ValueError("manifest fixtures must be a list")
    records = [fixture_status(fixture) for fixture in fixtures if isinstance(fixture, dict)]
    failed_required = [record for record in records if record["required"] and record["status"] != "pass"]
    summary = {
        "schema_version": "1.0",
        "tool": "dwm_command_safety.py",
        "suite_id": str(manifest.get("suite_id", "v89-command-safety")),
        "fixture_count": len(records),
        "required_fixture_count": sum(1 for record in records if record["required"]),
        "required_passed": sum(1 for record in records if record["required"] and record["status"] == "pass"),
        "passed": sum(1 for record in records if record["status"] == "pass"),
        "failed": sum(1 for record in records if record["status"] != "pass"),
        "decision": "keep" if not failed_required else "kill",
        "fixtures": records,
    }
    write_json(out_dir / "summary.json", summary)
    if failed_required:
        raise ValueError("required command-safety fixture failed")
    return summary


def self_test() -> None:
    safe = assess_command_safety("python scripts/dwm_workflow_queue.py --manifest fixtures/v46/manifest.json --out out/workflow-queues/v46-final", ["read-only", "evidence"])
    if not safe.supported or safe.gated_risk_codes:
        raise ValueError("safe evidence command should be supported and ungated")
    runner = assess_command_safety("python scripts/dwm_runner.py --manifest fixtures/v13/manifest.json --out out/v13/final", ["read-only", "evidence"])
    if runner.gated_risk_codes != ["write"]:
        raise ValueError("runner command should infer write risk")
    shell = assess_command_safety("bash scripts/unknown.sh", ["read-only"])
    if not shell.blocked_by or shell.blocked_by[0]["code"] != "ERR_DWM_COMMAND_UNSUPPORTED":
        raise ValueError("unsupported shell command should be blocked")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--out", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        if args.self_test:
            self_test()
            print("command safety self-test: pass")
            return
        if args.manifest:
            if args.out is None:
                raise ValueError("--manifest requires --out")
            summary = run_manifest(args.manifest, args.out)
            print(json.dumps(summary, sort_keys=True))
            return
        raise ValueError("choose --self-test or --manifest")
    except ValueError as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, sort_keys=True), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
