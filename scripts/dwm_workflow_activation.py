#!/usr/bin/env python3
"""V85 next workflow activation gate for DWM."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from compile_workflow import canonical_hash, read_json, write_json_atomic, write_text_atomic  # noqa: E402


TOOL = "dwm_workflow_activation.py"
ACTIVATION_VERSION = "90.0.0"
ACTIVATION_ROOT = ROOT / "out" / "workflow-activations"
DEFAULT_AUDIT = ROOT / "out" / "installed-surface-audits" / "v84-canonical" / "installed-surface-audit.json"
DEFAULT_RECEIPT = ROOT / "out" / "runner-receipt-dry-runs" / "v83-canonical" / "runner-receipt.json"
DEFAULT_STATUS = ROOT / "out" / "v9" / "v32-semantic-dogfood" / "status.json"
DEFAULT_BRAND_AUDIT = ROOT / "out" / "brand-boundary-audits" / "v87-canonical" / "brand-boundary-audit.json"
DEFAULT_ROADMAP_RECONCILIATION = ROOT / "out" / "roadmap-reconciliations" / "v88-canonical" / "roadmap-reconciliation.json"
DEFAULT_COMMAND_SAFETY = ROOT / "out" / "command-safety" / "v89-final" / "summary.json"
SENTINEL = ".dwm_workflow_activation-owned.json"
READY_INSTALL_DECISIONS = {"installed_copy_synced", "repo_backed_active_surface"}
READY_BRAND_DECISIONS = {"brand_boundary_ready"}


class WorkflowActivationError(ValueError):
    """Structured V85 workflow activation failure."""

    def __init__(self, code: str, message: str, *, path: Path | str | None = None, fixture_id: str | None = None) -> None:
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
        raise WorkflowActivationError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise WorkflowActivationError(code, "path contains a symlink", path=current)


def resolve_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_WORKFLOW_ACTIVATION_PATH_UNSAFE", message="activation output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = ACTIVATION_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise WorkflowActivationError("ERR_WORKFLOW_ACTIVATION_PATH_UNSAFE", f"activation output must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise WorkflowActivationError("ERR_WORKFLOW_ACTIVATION_PATH_UNSAFE", "activation output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_WORKFLOW_ACTIVATION_PATH_SYMLINK")
    return resolved


def resolve_out_input(value: str | Path, *, code: str) -> Path:
    raw = Path(value)
    reject_traversal(raw, code=code, message="activation input path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to((ROOT / "out").resolve(strict=False))
    except ValueError as exc:
        raise WorkflowActivationError(code, "activation input must resolve under out", path=value) from exc
    check_components_not_symlink(candidate, code="ERR_WORKFLOW_ACTIVATION_PATH_SYMLINK")
    if not resolved.is_file() or resolved.is_symlink():
        raise WorkflowActivationError(code, "activation input is missing or unsafe", path=value)
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


def prepare_out_dir(path: Path, activation_id: str, *, source: Path | str) -> None:
    if path.exists():
        if path.is_symlink():
            raise WorkflowActivationError("ERR_WORKFLOW_ACTIVATION_PATH_SYMLINK", "activation output is a symlink", path=path)
        if not path.is_dir():
            raise WorkflowActivationError("ERR_WORKFLOW_ACTIVATION_PATH_UNSAFE", "activation output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("activation_id") != activation_id:
            raise WorkflowActivationError("ERR_WORKFLOW_ACTIVATION_PATH_UNSAFE", "existing activation output is not activation-owned", path=path)
        shutil.rmtree(path)
    ACTIVATION_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(
        path / SENTINEL,
        {
            "tool": TOOL,
            "activation_version": ACTIVATION_VERSION,
            "activation_id": activation_id,
            "source_path": str(source),
            "created_at": now_utc(),
        },
        root=path,
    )


def collect_blockers(
    audit: dict[str, Any],
    receipt: dict[str, Any],
    run_status: dict[str, Any],
    *,
    brand_audit: dict[str, Any] | None = None,
    roadmap_reconciliation: dict[str, Any] | None = None,
    command_safety: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    audit_decision = audit.get("decision")
    if audit_decision not in READY_INSTALL_DECISIONS:
        blockers.append({"code": "ERR_WORKFLOW_ACTIVATION_INSTALL_NOT_READY", "message": "installed surface audit is not ready", "decision": audit_decision})
    if audit.get("blocked_by"):
        blockers.append({"code": "ERR_WORKFLOW_ACTIVATION_INSTALL_BLOCKED", "message": "installed surface audit contains blockers"})

    if receipt.get("status") != "receipt-dry-run":
        blockers.append({"code": "ERR_WORKFLOW_ACTIVATION_RECEIPT_NOT_DRY_RUN", "message": "runner receipt dry-run is not ready", "status": receipt.get("status")})
    if receipt.get("executed") is not False:
        blockers.append({"code": "ERR_WORKFLOW_ACTIVATION_RECEIPT_EXECUTED", "message": "activation requires a non-executing dry-run receipt"})
    if receipt.get("blocked_by"):
        blockers.append({"code": "ERR_WORKFLOW_ACTIVATION_RECEIPT_BLOCKED", "message": "runner receipt contains blockers"})

    if run_status.get("status") != "workflow-complete":
        blockers.append({"code": "ERR_WORKFLOW_ACTIVATION_RUN_INCOMPLETE", "message": "current workflow run is not complete", "status": run_status.get("status")})
    if "human_gate" not in set(run_status.get("human_approved_phase_ids", [])):
        blockers.append({"code": "ERR_WORKFLOW_ACTIVATION_RUN_GATE_MISSING", "message": "current workflow run lacks the recorded human gate"})
    if brand_audit is not None:
        if brand_audit.get("decision") not in READY_BRAND_DECISIONS:
            blockers.append({"code": "ERR_WORKFLOW_ACTIVATION_BRAND_BOUNDARY_NOT_READY", "message": "brand boundary audit is not clean", "decision": brand_audit.get("decision")})
        if brand_audit.get("blocked_by"):
            blockers.append({"code": "ERR_WORKFLOW_ACTIVATION_BRAND_BOUNDARY_BLOCKED", "message": "brand boundary audit contains blockers"})
    if roadmap_reconciliation is not None:
        if roadmap_reconciliation.get("decision") != "roadmap_reconciled":
            blockers.append({"code": "ERR_WORKFLOW_ACTIVATION_ROADMAP_NOT_RECONCILED", "message": "roadmap reconciliation is not ready", "decision": roadmap_reconciliation.get("decision")})
        if roadmap_reconciliation.get("blocked_by"):
            blockers.append({"code": "ERR_WORKFLOW_ACTIVATION_ROADMAP_BLOCKED", "message": "roadmap reconciliation contains blockers"})
        latest_version = (roadmap_reconciliation.get("policy") or {}).get("latest_version")
        if latest_version != "V117":
            blockers.append({"code": "ERR_WORKFLOW_ACTIVATION_ROADMAP_VERSION_STALE", "message": "roadmap reconciliation latest version is stale", "latest_version": latest_version})
    if command_safety is not None:
        if command_safety.get("decision") != "keep":
            blockers.append({"code": "ERR_WORKFLOW_ACTIVATION_COMMAND_SAFETY_NOT_READY", "message": "command safety gate did not keep", "decision": command_safety.get("decision")})
        if command_safety.get("failed") not in (0, None):
            blockers.append({"code": "ERR_WORKFLOW_ACTIVATION_COMMAND_SAFETY_FAILED", "message": "command safety fixtures failed", "failed": command_safety.get("failed")})
        required_passed = command_safety.get("required_passed")
        required_count = command_safety.get("required_fixture_count")
        if required_count is not None and required_passed != required_count:
            blockers.append({"code": "ERR_WORKFLOW_ACTIVATION_COMMAND_SAFETY_INCOMPLETE", "message": "command safety required fixture coverage is incomplete", "required_passed": required_passed, "required_fixture_count": required_count})
    return blockers


def make_activation(
    activation_id: str,
    audit: dict[str, Any],
    receipt: dict[str, Any],
    run_status: dict[str, Any],
    *,
    brand_audit: dict[str, Any] | None = None,
    roadmap_reconciliation: dict[str, Any] | None = None,
    command_safety: dict[str, Any] | None = None,
    source_paths: dict[str, str] | None = None,
) -> dict[str, Any]:
    blockers = collect_blockers(
        audit,
        receipt,
        run_status,
        brand_audit=brand_audit,
        roadmap_reconciliation=roadmap_reconciliation,
        command_safety=command_safety,
    )
    decision = "ready_for_next_workflow_design" if not blockers else "blocked"
    evidence_inputs = {
        "install_decision": audit.get("decision"),
        "receipt_status": receipt.get("status"),
        "receipt_executed": receipt.get("executed"),
        "run_status": run_status.get("status"),
    }
    if brand_audit is not None:
        evidence_inputs["brand_boundary_decision"] = brand_audit.get("decision")
    if roadmap_reconciliation is not None:
        evidence_inputs["roadmap_decision"] = roadmap_reconciliation.get("decision")
        evidence_inputs["roadmap_latest_version"] = (roadmap_reconciliation.get("policy") or {}).get("latest_version")
    if command_safety is not None:
        evidence_inputs["command_safety_decision"] = command_safety.get("decision")
        evidence_inputs["command_safety_required_passed"] = command_safety.get("required_passed")
    return {
        "schema_version": ACTIVATION_VERSION,
        "tool": TOOL,
        "activation_id": activation_id,
        "decision": decision,
        "blocked_by": blockers,
        "next_safe_action": "design_next_workflow" if decision == "ready_for_next_workflow_design" else "preserve_artifacts_and_fix_blockers",
        "execution_policy": {
            "executes_commands": False,
            "creates_worktrees": False,
            "uses_network": False,
            "requires_human_gate_for_live_execution": True,
        },
        "inputs": evidence_inputs,
        "source_paths": source_paths or {},
        "source_hashes": {
            "audit": canonical_hash(audit),
            "receipt": canonical_hash(receipt),
            "run_status": canonical_hash(run_status),
            "brand_audit": canonical_hash(brand_audit) if brand_audit is not None else None,
            "roadmap_reconciliation": canonical_hash(roadmap_reconciliation) if roadmap_reconciliation is not None else None,
            "command_safety": canonical_hash(command_safety) if command_safety is not None else None,
        },
    }


def render_markdown(activation: dict[str, Any]) -> str:
    lines = [
        f"# Workflow Activation {activation['activation_id']}",
        "",
        f"- Decision: `{activation['decision']}`",
        f"- Next safe action: `{activation['next_safe_action']}`",
        f"- Executes commands: `{activation['execution_policy']['executes_commands']}`",
        f"- Requires human gate for live execution: `{activation['execution_policy']['requires_human_gate_for_live_execution']}`",
        "",
        "## Inputs",
        "",
    ]
    for key, value in activation["inputs"].items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Blockers", ""])
    if activation["blocked_by"]:
        for blocker in activation["blocked_by"]:
            lines.append(f"- `{blocker['code']}`: {blocker.get('message', '')}")
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def write_activation(out_dir: Path, activation: dict[str, Any]) -> None:
    write_json_atomic(out_dir / "workflow-activation.json", activation, root=out_dir)
    write_json_atomic(out_dir / "status.json", activation, root=out_dir)
    write_text_atomic(out_dir / "workflow-activation.md", render_markdown(activation), root=out_dir)


def run_activation(
    audit_path: Path,
    receipt_path: Path,
    status_path: Path,
    out_dir: Path,
    *,
    brand_audit_path: Path | None = None,
    roadmap_reconciliation_path: Path | None = None,
    command_safety_path: Path | None = None,
) -> dict[str, Any]:
    audit_path = resolve_out_input(audit_path, code="ERR_WORKFLOW_ACTIVATION_AUDIT_UNSAFE")
    receipt_path = resolve_out_input(receipt_path, code="ERR_WORKFLOW_ACTIVATION_RECEIPT_UNSAFE")
    status_path = resolve_out_input(status_path, code="ERR_WORKFLOW_ACTIVATION_STATUS_UNSAFE")
    brand_audit_resolved = resolve_out_input(brand_audit_path, code="ERR_WORKFLOW_ACTIVATION_BRAND_AUDIT_UNSAFE") if brand_audit_path is not None else None
    roadmap_resolved = resolve_out_input(roadmap_reconciliation_path, code="ERR_WORKFLOW_ACTIVATION_ROADMAP_UNSAFE") if roadmap_reconciliation_path is not None else None
    command_safety_resolved = resolve_out_input(command_safety_path, code="ERR_WORKFLOW_ACTIVATION_COMMAND_SAFETY_UNSAFE") if command_safety_path is not None else None
    out_dir = resolve_out(out_dir)
    prepare_out_dir(out_dir, out_dir.name, source=audit_path)
    audit = read_json(audit_path)
    receipt = read_json(receipt_path)
    run_status = read_json(status_path)
    brand_audit = read_json(brand_audit_resolved) if brand_audit_resolved is not None else None
    roadmap_reconciliation = read_json(roadmap_resolved) if roadmap_resolved is not None else None
    command_safety = read_json(command_safety_resolved) if command_safety_resolved is not None else None
    source_paths = {"audit": rel(audit_path), "receipt": rel(receipt_path), "run_status": rel(status_path)}
    if brand_audit_resolved is not None:
        source_paths["brand_audit"] = rel(brand_audit_resolved)
    if roadmap_resolved is not None:
        source_paths["roadmap_reconciliation"] = rel(roadmap_resolved)
    if command_safety_resolved is not None:
        source_paths["command_safety"] = rel(command_safety_resolved)
    activation = make_activation(
        out_dir.name,
        audit,
        receipt,
        run_status,
        brand_audit=brand_audit,
        roadmap_reconciliation=roadmap_reconciliation,
        command_safety=command_safety,
        source_paths=source_paths,
    )
    write_activation(out_dir, activation)
    return activation


def run_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    fixtures = manifest.get("fixtures")
    if not isinstance(fixtures, list):
        raise WorkflowActivationError("ERR_WORKFLOW_ACTIVATION_MANIFEST_INVALID", "manifest fixtures must be a list", path=manifest_path)
    suite_id = str(manifest.get("suite_id", "v85-workflow-activation"))
    out_dir = resolve_out(out_dir)
    prepare_out_dir(out_dir, out_dir.name, source=manifest_path)
    records = []
    for fixture in fixtures:
        if not isinstance(fixture, dict):
            raise WorkflowActivationError("ERR_WORKFLOW_ACTIVATION_MANIFEST_INVALID", "fixture must be an object", path=manifest_path)
        fixture_id = str(fixture.get("id", "fixture"))
        fixture_out = out_dir / fixture_id
        prepare_out_dir(fixture_out, fixture_id, source=manifest_path)
        activation = make_activation(
            fixture_id,
            fixture.get("audit") if isinstance(fixture.get("audit"), dict) else {},
            fixture.get("receipt") if isinstance(fixture.get("receipt"), dict) else {},
            fixture.get("run_status") if isinstance(fixture.get("run_status"), dict) else {},
            brand_audit=fixture.get("brand_audit") if isinstance(fixture.get("brand_audit"), dict) else None,
            roadmap_reconciliation=fixture.get("roadmap_reconciliation") if isinstance(fixture.get("roadmap_reconciliation"), dict) else None,
            command_safety=fixture.get("command_safety") if isinstance(fixture.get("command_safety"), dict) else None,
        )
        write_activation(fixture_out, activation)
        expected_decision = fixture.get("expected_decision")
        status = "pass" if expected_decision in (None, activation["decision"]) else "fail"
        records.append({"id": fixture_id, "required": bool(fixture.get("required", True)), "status": status, "decision": activation["decision"], "error": None if status == "pass" else f"expected {expected_decision}, got {activation['decision']}"})
    failed_required = [record for record in records if record["required"] and record["status"] != "pass"]
    summary = {
        "schema_version": ACTIVATION_VERSION,
        "tool": TOOL,
        "suite_id": suite_id,
        "fixture_count": len(records),
        "required_fixture_count": sum(1 for record in records if record["required"]),
        "required_passed": sum(1 for record in records if record["required"] and record["status"] == "pass"),
        "passed": sum(1 for record in records if record["status"] == "pass"),
        "failed": sum(1 for record in records if record["status"] != "pass"),
        "decision": "keep" if not failed_required else "kill",
        "fixtures": records,
        "source_hashes": {"manifest": canonical_hash(manifest)},
    }
    write_json_atomic(out_dir / "summary.json", summary, root=out_dir)
    if failed_required:
        raise WorkflowActivationError("ERR_WORKFLOW_ACTIVATION_FIXTURE_FAILED", "required workflow activation fixture failed", path=manifest_path)
    return summary


def ready_audit() -> dict[str, Any]:
    return {"decision": "installed_copy_synced", "blocked_by": []}


def ready_receipt() -> dict[str, Any]:
    return {"status": "receipt-dry-run", "executed": False, "blocked_by": []}


def ready_run_status() -> dict[str, Any]:
    return {"status": "workflow-complete", "human_approved_phase_ids": ["human_gate"]}


def ready_brand_audit() -> dict[str, Any]:
    return {"decision": "brand_boundary_ready", "blocked_by": []}


def ready_roadmap_reconciliation() -> dict[str, Any]:
    return {"decision": "roadmap_reconciled", "blocked_by": [], "policy": {"latest_version": "V117"}}


def ready_command_safety() -> dict[str, Any]:
    return {"decision": "keep", "failed": 0, "required_passed": 4, "required_fixture_count": 4}


def self_test() -> None:
    activation = make_activation("self-test", ready_audit(), ready_receipt(), ready_run_status())
    if activation["decision"] != "ready_for_next_workflow_design":
        raise WorkflowActivationError("ERR_WORKFLOW_ACTIVATION_SELF_TEST_FAILED", "ready inputs should allow next workflow design")
    activation_v2 = make_activation("self-test-v2", ready_audit(), ready_receipt(), ready_run_status(), brand_audit=ready_brand_audit(), roadmap_reconciliation=ready_roadmap_reconciliation(), command_safety=ready_command_safety())
    if activation_v2["decision"] != "ready_for_next_workflow_design":
        raise WorkflowActivationError("ERR_WORKFLOW_ACTIVATION_SELF_TEST_FAILED", "ready v2 inputs should allow next workflow design")
    blocked = make_activation("self-test-blocked", {"decision": "blocked", "blocked_by": [{"code": "stale"}]}, ready_receipt(), ready_run_status())
    if blocked["decision"] != "blocked":
        raise WorkflowActivationError("ERR_WORKFLOW_ACTIVATION_SELF_TEST_FAILED", "blocked install audit should block activation")
    stale_roadmap = make_activation("self-test-stale-roadmap", ready_audit(), ready_receipt(), ready_run_status(), brand_audit=ready_brand_audit(), roadmap_reconciliation={"decision": "roadmap_reconciled", "blocked_by": [], "policy": {"latest_version": "V93"}}, command_safety=ready_command_safety())
    if stale_roadmap["decision"] != "blocked":
        raise WorkflowActivationError("ERR_WORKFLOW_ACTIVATION_SELF_TEST_FAILED", "stale roadmap version should block v2 activation")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--out", type=Path)
    subparsers = parser.add_subparsers(dest="command")
    activate_parser = subparsers.add_parser("activate")
    activate_parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    activate_parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    activate_parser.add_argument("--status", type=Path, default=DEFAULT_STATUS)
    activate_parser.add_argument("--brand-audit", type=Path)
    activate_parser.add_argument("--roadmap-reconciliation", type=Path)
    activate_parser.add_argument("--command-safety", type=Path)
    activate_parser.add_argument("--out", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        if args.self_test:
            self_test()
            print("workflow activation self-test: pass")
            return
        if args.manifest:
            if args.out is None:
                raise WorkflowActivationError("ERR_WORKFLOW_ACTIVATION_ARGS_INVALID", "--manifest requires --out")
            print(json.dumps(run_manifest(args.manifest, args.out), sort_keys=True))
            return
        if args.command == "activate":
            activation = run_activation(
                args.audit,
                args.receipt,
                args.status,
                args.out,
                brand_audit_path=args.brand_audit,
                roadmap_reconciliation_path=args.roadmap_reconciliation,
                command_safety_path=args.command_safety,
            )
            print(json.dumps({"activation_id": activation["activation_id"], "decision": activation["decision"], "blocked_by": activation["blocked_by"]}, sort_keys=True))
            return
        raise WorkflowActivationError("ERR_WORKFLOW_ACTIVATION_ARGS_INVALID", "choose --self-test, --manifest, or activate")
    except WorkflowActivationError as exc:
        print(json.dumps({"status": "error", "error": exc.to_record()}, sort_keys=True), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
