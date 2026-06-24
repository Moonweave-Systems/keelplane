#!/usr/bin/env python3
"""V76 bridge from large-workflow next selection to queue packet."""

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
from dwm_command_safety import GATED_RISK_CODES, assess_command_safety  # noqa: E402
from dwm_workflow_queue import build_queue, resolve_queue_out  # noqa: E402


TOOL = "dwm_large_workflow_queue_bridge.py"
SCHEMA_VERSION = "1.0"
BRIDGE_VERSION = "76.0.0"
BRIDGE_ROOT = ROOT / "out" / "large-workflow-queue-bridge"
DEFAULT_SELECTION = ROOT / "out" / "large-workflow-next" / "v75-canonical" / "large-workflow-next.json"
DEFAULT_QUEUE_OUT = ROOT / "out" / "workflow-queues" / "v76-canonical"
SENTINEL = ".dwm_large_workflow_queue_bridge-owned.json"


class LargeWorkflowQueueBridgeError(ValueError):
    """Structured V76 queue bridge failure."""

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
        raise LargeWorkflowQueueBridgeError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise LargeWorkflowQueueBridgeError(code, "path contains a symlink", path=current)


def resolve_bridge_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_LARGE_WORKFLOW_QUEUE_BRIDGE_PATH_UNSAFE", message="bridge output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = BRIDGE_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise LargeWorkflowQueueBridgeError("ERR_LARGE_WORKFLOW_QUEUE_BRIDGE_PATH_UNSAFE", f"bridge output must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise LargeWorkflowQueueBridgeError("ERR_LARGE_WORKFLOW_QUEUE_BRIDGE_PATH_UNSAFE", "bridge output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_LARGE_WORKFLOW_QUEUE_BRIDGE_PATH_SYMLINK")
    return resolved


def resolve_selection(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_LARGE_WORKFLOW_QUEUE_BRIDGE_SELECTION_UNSAFE", message="selection path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    out_resolved = (ROOT / "out").resolve(strict=False)
    try:
        resolved.relative_to(out_resolved)
    except ValueError as exc:
        raise LargeWorkflowQueueBridgeError("ERR_LARGE_WORKFLOW_QUEUE_BRIDGE_SELECTION_UNSAFE", "selection must resolve under out", path=value) from exc
    check_components_not_symlink(candidate, code="ERR_LARGE_WORKFLOW_QUEUE_BRIDGE_PATH_SYMLINK")
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


def prepare_bridge_out(path: Path, bridge_id: str, *, source: Path | str) -> None:
    if path.exists():
        if path.is_symlink():
            raise LargeWorkflowQueueBridgeError("ERR_LARGE_WORKFLOW_QUEUE_BRIDGE_PATH_SYMLINK", "bridge output is a symlink", path=path)
        if not path.is_dir():
            raise LargeWorkflowQueueBridgeError("ERR_LARGE_WORKFLOW_QUEUE_BRIDGE_PATH_UNSAFE", "bridge output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("bridge_id") != bridge_id:
            raise LargeWorkflowQueueBridgeError("ERR_LARGE_WORKFLOW_QUEUE_BRIDGE_PATH_UNSAFE", "existing bridge output is not bridge-owned", path=path)
        shutil.rmtree(path)
    BRIDGE_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(
        path / SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "bridge_version": BRIDGE_VERSION,
            "bridge_id": bridge_id,
            "source_path": str(source),
            "created_at": now_utc(),
        },
        root=path,
    )


def selection_blockers(selection: dict[str, Any], *, expected_hash: str | None = None) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    actual_hash = canonical_hash(selection)
    if expected_hash is not None and expected_hash != actual_hash:
        blockers.append({"code": "ERR_LARGE_WORKFLOW_QUEUE_BRIDGE_SOURCE_HASH_MISMATCH", "expected": expected_hash, "actual": actual_hash})
    if selection.get("status") != "next-workflow-ready":
        blockers.append({"code": "ERR_LARGE_WORKFLOW_QUEUE_BRIDGE_NEXT_NOT_READY", "message": "next selection is not ready"})
    if selection.get("decision") != "command_ready":
        blockers.append({"code": "ERR_LARGE_WORKFLOW_QUEUE_BRIDGE_DECISION_NOT_READY", "message": "next selection decision is not command_ready"})
    if selection.get("blocked_by"):
        blockers.append({"code": "ERR_LARGE_WORKFLOW_QUEUE_BRIDGE_NEXT_BLOCKED", "message": "next selection contains blockers"})
    if selection.get("gated_by"):
        blockers.append({"code": "ERR_LARGE_WORKFLOW_QUEUE_BRIDGE_NEXT_GATED", "message": "next selection requires a human gate"})
    command = selection.get("command")
    if not isinstance(command, str) or not command.strip():
        blockers.append({"code": "ERR_LARGE_WORKFLOW_QUEUE_BRIDGE_COMMAND_MISSING", "message": "next selection command is missing"})
    candidate = selection.get("selected_candidate")
    if not isinstance(candidate, dict):
        blockers.append({"code": "ERR_LARGE_WORKFLOW_QUEUE_BRIDGE_CANDIDATE_MISSING", "message": "selected candidate is missing"})
    else:
        risk_codes = candidate.get("risk_codes")
        if not isinstance(risk_codes, list) or not all(isinstance(code, str) for code in risk_codes):
            blockers.append({"code": "ERR_LARGE_WORKFLOW_QUEUE_BRIDGE_CANDIDATE_INVALID", "message": "candidate risk_codes are invalid"})
        else:
            safety = assess_command_safety(str(command or candidate.get("next_command", "")), risk_codes)
            for safety_blocker in safety.blocked_by:
                blockers.append({"code": "ERR_LARGE_WORKFLOW_QUEUE_BRIDGE_COMMAND_UNSAFE", "command_safety": safety_blocker})
            gated = sorted(set(safety.gated_risk_codes) & GATED_RISK_CODES)
            if gated:
                blockers.append(
                    {
                        "code": "ERR_LARGE_WORKFLOW_QUEUE_BRIDGE_RISK_GATE_REQUIRED",
                        "risk_codes": gated,
                        "inferred_risk_codes": safety.inferred_risk_codes,
                    }
                )
    return blockers


def evidence_paths(selection_path: Path, selection: dict[str, Any]) -> list[str]:
    paths = [rel(selection_path)]
    control_path = selection.get("control_path")
    if isinstance(control_path, str) and control_path:
        paths.append(control_path)
        control_json = ROOT / control_path
        control_parent = control_json.parent
        for name in ["large-workflow-control.json", "status.json"]:
            candidate = control_parent / name
            if candidate.exists() and not candidate.is_symlink():
                paths.append(rel(candidate))
    status_path = selection_path.with_name("status.json")
    if status_path.exists() and not status_path.is_symlink():
        paths.append(rel(status_path))
    return sorted(dict.fromkeys(paths))


def packet_from_selection(selection_path: Path, selection: dict[str, Any]) -> dict[str, Any]:
    candidate = selection["selected_candidate"]
    safety = assess_command_safety(str(selection["command"]), candidate.get("risk_codes", []))
    return {
        "id": str(candidate["id"]),
        "title": str(candidate["objective"]),
        "status": "pending",
        "command": str(selection["command"]),
        "risk_codes": safety.effective_risk_codes,
        "evidence_paths": evidence_paths(selection_path, selection),
        "verification_status": "pass",
        "requires_human": False,
        "command_safety": safety.to_record(),
    }


def make_bridge(bridge_id: str, selection_path: Path, selection: dict[str, Any], *, queue_out: Path | None = None, expected_hash: str | None = None) -> dict[str, Any]:
    blockers = selection_blockers(selection, expected_hash=expected_hash)
    packets: list[dict[str, Any]] = []
    queue: dict[str, Any] | None = None
    if not blockers:
        packet = packet_from_selection(selection_path, selection)
        packets = [packet]
        missing = [path for path in packet["evidence_paths"] if not (ROOT / path).exists()]
        if missing:
            blockers.append({"code": "ERR_LARGE_WORKFLOW_QUEUE_BRIDGE_EVIDENCE_MISSING", "paths": missing})
    if not blockers and queue_out is not None:
        queue = build_queue(packets, resolve_queue_out(queue_out), queue_id=Path(queue_out).name, source=selection_path)
        if queue.get("next_action", {}).get("status") != "ready":
            blockers.append({"code": "ERR_LARGE_WORKFLOW_QUEUE_BRIDGE_QUEUE_NOT_READY", "next_action": queue.get("next_action")})
    status = "queue-bridge-ready" if not blockers else "queue-bridge-blocked"
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "bridge_version": BRIDGE_VERSION,
        "bridge_id": bridge_id,
        "status": status,
        "selection_path": rel(selection_path),
        "queue_path": rel(queue_out) if queue_out is not None else None,
        "packets": packets,
        "queue_next_action": queue.get("next_action") if isinstance(queue, dict) else None,
        "blocked_by": blockers,
        "source_hashes": {
            "selection": canonical_hash(selection),
            "packets": canonical_hash(packets),
            "queue": canonical_hash(queue) if queue is not None else None,
        },
    }


def render_markdown(bridge: dict[str, Any]) -> str:
    packet = bridge["packets"][0] if bridge["packets"] else {}
    lines = [
        f"# Large Workflow Queue Bridge {bridge['bridge_id']}",
        "",
        f"- Status: `{bridge['status']}`",
        f"- Selection: `{bridge['selection_path']}`",
        f"- Queue: `{bridge['queue_path'] or 'none'}`",
        f"- Packet: `{packet.get('id', 'none')}`",
        f"- Command: `{packet.get('command', 'none')}`",
        "",
        "## Blockers",
        "",
    ]
    if bridge["blocked_by"]:
        for blocker in bridge["blocked_by"]:
            lines.append(f"- `{blocker['code']}`: {json.dumps(blocker, sort_keys=True)}")
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def write_bridge(out_dir: Path, bridge: dict[str, Any]) -> None:
    write_json_atomic(out_dir / "queue-bridge.json", bridge, root=out_dir)
    write_json_atomic(out_dir / "queue-packets.json", bridge["packets"], root=out_dir)
    write_json_atomic(
        out_dir / "status.json",
        {
            "schema_version": SCHEMA_VERSION,
            "tool": TOOL,
            "bridge_id": bridge["bridge_id"],
            "status": bridge["status"],
            "selection_path": bridge["selection_path"],
            "queue_path": bridge["queue_path"],
            "packet_count": len(bridge["packets"]),
            "blocked_by": bridge["blocked_by"],
            "source_hashes": bridge["source_hashes"],
        },
        root=out_dir,
    )
    write_text_atomic(out_dir / "queue-bridge.md", render_markdown(bridge), root=out_dir)


def bridge_selection(selection_path: Path, bridge_out: Path, *, queue_out: Path | None = None, expected_hash: str | None = None) -> dict[str, Any]:
    selection_path = resolve_selection(selection_path)
    if not selection_path.is_file() or selection_path.is_symlink():
        raise LargeWorkflowQueueBridgeError("ERR_LARGE_WORKFLOW_QUEUE_BRIDGE_SELECTION_MISSING", "selection artifact is missing", path=selection_path)
    selection = read_json(selection_path)
    bridge_out = resolve_bridge_out(bridge_out)
    prepare_bridge_out(bridge_out, bridge_out.name, source=selection_path)
    bridge = make_bridge(bridge_out.name, selection_path, selection, queue_out=queue_out, expected_hash=expected_hash)
    write_bridge(bridge_out, bridge)
    return bridge


def run_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    fixtures = manifest.get("fixtures")
    if not isinstance(fixtures, list):
        raise LargeWorkflowQueueBridgeError("ERR_LARGE_WORKFLOW_QUEUE_BRIDGE_MANIFEST_INVALID", "manifest fixtures must be a list", path=manifest_path)
    suite_id = str(manifest.get("suite_id", "v76-large-workflow-queue-bridge"))
    out_dir = resolve_bridge_out(out_dir)
    prepare_bridge_out(out_dir, out_dir.name, source=manifest_path)
    records = []
    for fixture in fixtures:
        if not isinstance(fixture, dict):
            raise LargeWorkflowQueueBridgeError("ERR_LARGE_WORKFLOW_QUEUE_BRIDGE_MANIFEST_INVALID", "fixture must be an object", path=manifest_path)
        fixture_id = str(fixture.get("id", "fixture"))
        selection = fixture.get("selection")
        if not isinstance(selection, dict):
            raise LargeWorkflowQueueBridgeError("ERR_LARGE_WORKFLOW_QUEUE_BRIDGE_MANIFEST_INVALID", "fixture selection must be an object", fixture_id=fixture_id)
        fixture_out = out_dir / fixture_id
        prepare_bridge_out(fixture_out, fixture_id, source=manifest_path)
        write_json_atomic(fixture_out / "selection.json", selection, root=fixture_out)
        control_receipt = fixture.get("control_receipt")
        if isinstance(control_receipt, dict):
            write_json_atomic(fixture_out / "control.json", control_receipt, root=fixture_out)
            selection = {**selection, "control_path": rel(fixture_out / "control.json")}
        queue_out = ROOT / "out" / "workflow-queues" / f"{out_dir.name}-{fixture_id}" if fixture.get("build_queue", False) else None
        bridge = make_bridge(
            fixture_id,
            fixture_out / "selection.json",
            selection,
            queue_out=queue_out,
            expected_hash=fixture.get("expected_selection_hash"),
        )
        write_bridge(fixture_out, bridge)
        expected_status = fixture.get("expected_status")
        status = "pass" if expected_status in (None, bridge["status"]) else "fail"
        records.append(
            {
                "id": fixture_id,
                "required": bool(fixture.get("required", True)),
                "status": status,
                "bridge_status": bridge["status"],
                "packet_count": len(bridge["packets"]),
                "queue_next_action": bridge["queue_next_action"],
                "blocked_by": bridge["blocked_by"],
                "error": None if status == "pass" else f"expected {expected_status}, got {bridge['status']}",
            }
        )
    failed_required = [record for record in records if record["required"] and record["status"] != "pass"]
    summary = {
        "schema_version": SCHEMA_VERSION,
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
        raise LargeWorkflowQueueBridgeError("ERR_LARGE_WORKFLOW_QUEUE_BRIDGE_FIXTURE_FAILED", "required bridge fixture failed", path=manifest_path)
    return summary


def ready_selection(control_path: str = "out/large-workflow-dogfood/v74-canonical/dogfood-control.json") -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": "dwm_large_workflow_next.py",
        "next_id": "fixture-ready",
        "status": "next-workflow-ready",
        "decision": "command_ready",
        "control_path": control_path,
        "selected_candidate": {
            "id": "large-workflow-queue-refresh",
            "objective": "Refresh the large-workflow queue from current control evidence.",
            "priority": 90,
            "risk_codes": ["read-only", "evidence"],
            "next_command": "python scripts/dwm_workflow_queue.py --manifest fixtures/v46/manifest.json --out out/workflow-queues/v46-final",
            "success_criteria": ["queue artifact generated"],
            "evidence_requirements": ["dogfood-control.json", "large-workflow-next.json"],
            "claim_limits": ["internal workflow selection only"],
        },
        "command": "python scripts/dwm_workflow_queue.py --manifest fixtures/v46/manifest.json --out out/workflow-queues/v46-final",
        "blocked_by": [],
        "gated_by": [],
        "source_hashes": {"selection": "fixture-selection"},
    }


def self_test() -> None:
    evidence_root = BRIDGE_ROOT / "self-test-evidence"
    evidence_root.mkdir(parents=True, exist_ok=True)
    selection_path = evidence_root / "selection.json"
    control_path = evidence_root / "control.json"
    write_json_atomic(control_path, {"status": "dogfood-control-recorded"}, root=evidence_root)
    ready = ready_selection(rel(control_path))
    write_json_atomic(selection_path, ready, root=evidence_root)
    bridge = make_bridge("self-test-ready", selection_path, ready)
    if bridge["status"] != "queue-bridge-ready" or len(bridge["packets"]) != 1:
        raise LargeWorkflowQueueBridgeError("ERR_LARGE_WORKFLOW_QUEUE_BRIDGE_SELF_TEST_FAILED", "ready selection should create one packet")
    blocked = ready_selection()
    blocked["status"] = "next-workflow-blocked"
    blocked_bridge = make_bridge("self-test-blocked", DEFAULT_SELECTION, blocked)
    if blocked_bridge["status"] != "queue-bridge-blocked":
        raise LargeWorkflowQueueBridgeError("ERR_LARGE_WORKFLOW_QUEUE_BRIDGE_SELF_TEST_FAILED", "blocked selection should block bridge")
    gated = ready_selection()
    gated["selected_candidate"] = {**gated["selected_candidate"], "risk_codes": ["write"]}
    gated_bridge = make_bridge("self-test-gated", DEFAULT_SELECTION, gated)
    if gated_bridge["status"] != "queue-bridge-blocked":
        raise LargeWorkflowQueueBridgeError("ERR_LARGE_WORKFLOW_QUEUE_BRIDGE_SELF_TEST_FAILED", "write risk should block bridge")
    undeclared_runner = ready_selection()
    undeclared_runner["command"] = "python scripts/dwm_runner.py --manifest fixtures/v13/manifest.json --out out/v13/final"
    undeclared_runner["selected_candidate"] = {
        **undeclared_runner["selected_candidate"],
        "risk_codes": ["read-only", "evidence"],
        "next_command": undeclared_runner["command"],
    }
    undeclared_bridge = make_bridge("self-test-undeclared-runner-risk", DEFAULT_SELECTION, undeclared_runner)
    if undeclared_bridge["status"] != "queue-bridge-blocked":
        raise LargeWorkflowQueueBridgeError("ERR_LARGE_WORKFLOW_QUEUE_BRIDGE_SELF_TEST_FAILED", "inferred runner write risk should block bridge")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="run V76 bridge self-test")
    parser.add_argument("--manifest", type=Path, help="run bridge fixtures from a manifest")
    parser.add_argument("--out", type=Path, help="output directory under out/large-workflow-queue-bridge")
    subparsers = parser.add_subparsers(dest="command")
    bridge_parser = subparsers.add_parser("bridge", help="bridge a V75 next selection into a V46 queue packet")
    bridge_parser.add_argument("--selection", type=Path, default=DEFAULT_SELECTION)
    bridge_parser.add_argument("--queue-out", type=Path, default=DEFAULT_QUEUE_OUT)
    bridge_parser.add_argument("--expected-selection-hash")
    bridge_parser.add_argument("--out", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        if args.self_test:
            self_test()
            print("large workflow queue bridge self-test: pass")
            return
        if args.manifest:
            if args.out is None:
                raise LargeWorkflowQueueBridgeError("ERR_LARGE_WORKFLOW_QUEUE_BRIDGE_ARGS_INVALID", "--manifest requires --out")
            summary = run_manifest(args.manifest, args.out)
            print(json.dumps(summary, sort_keys=True))
            return
        if args.command == "bridge":
            bridge = bridge_selection(args.selection, args.out, queue_out=args.queue_out, expected_hash=args.expected_selection_hash)
            print(json.dumps({"status": bridge["status"], "bridge_id": bridge["bridge_id"], "packet_count": len(bridge["packets"])}, sort_keys=True))
            return
        raise LargeWorkflowQueueBridgeError("ERR_LARGE_WORKFLOW_QUEUE_BRIDGE_ARGS_INVALID", "choose --self-test, --manifest, or bridge")
    except LargeWorkflowQueueBridgeError as exc:
        print(json.dumps({"status": "error", "error": exc.to_record()}, sort_keys=True), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
