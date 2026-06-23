#!/usr/bin/env python3
"""V77 preflight gate for large-workflow queue packets."""

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


TOOL = "dwm_large_workflow_queue_preflight.py"
SCHEMA_VERSION = "1.0"
PREFLIGHT_VERSION = "77.0.0"
PREFLIGHT_ROOT = ROOT / "out" / "large-workflow-queue-preflight"
DEFAULT_QUEUE = ROOT / "out" / "workflow-queues" / "v76-canonical" / "queue.json"
SENTINEL = ".dwm_large_workflow_queue_preflight-owned.json"


class LargeWorkflowQueuePreflightError(ValueError):
    """Structured V77 queue preflight failure."""

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
        raise LargeWorkflowQueuePreflightError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise LargeWorkflowQueuePreflightError(code, "path contains a symlink", path=current)


def resolve_preflight_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_LARGE_WORKFLOW_QUEUE_PREFLIGHT_PATH_UNSAFE", message="preflight output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = PREFLIGHT_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise LargeWorkflowQueuePreflightError("ERR_LARGE_WORKFLOW_QUEUE_PREFLIGHT_PATH_UNSAFE", f"preflight output must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise LargeWorkflowQueuePreflightError("ERR_LARGE_WORKFLOW_QUEUE_PREFLIGHT_PATH_UNSAFE", "preflight output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_LARGE_WORKFLOW_QUEUE_PREFLIGHT_PATH_SYMLINK")
    return resolved


def resolve_queue(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_LARGE_WORKFLOW_QUEUE_PREFLIGHT_QUEUE_UNSAFE", message="queue path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    out_resolved = (ROOT / "out").resolve(strict=False)
    try:
        resolved.relative_to(out_resolved)
    except ValueError as exc:
        raise LargeWorkflowQueuePreflightError("ERR_LARGE_WORKFLOW_QUEUE_PREFLIGHT_QUEUE_UNSAFE", "queue path must resolve under out", path=value) from exc
    check_components_not_symlink(candidate, code="ERR_LARGE_WORKFLOW_QUEUE_PREFLIGHT_PATH_SYMLINK")
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


def prepare_out_dir(path: Path, preflight_id: str, *, source: Path | str) -> None:
    if path.exists():
        if path.is_symlink():
            raise LargeWorkflowQueuePreflightError("ERR_LARGE_WORKFLOW_QUEUE_PREFLIGHT_PATH_SYMLINK", "preflight output is a symlink", path=path)
        if not path.is_dir():
            raise LargeWorkflowQueuePreflightError("ERR_LARGE_WORKFLOW_QUEUE_PREFLIGHT_PATH_UNSAFE", "preflight output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("preflight_id") != preflight_id:
            raise LargeWorkflowQueuePreflightError("ERR_LARGE_WORKFLOW_QUEUE_PREFLIGHT_PATH_UNSAFE", "existing preflight output is not preflight-owned", path=path)
        shutil.rmtree(path)
    PREFLIGHT_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(
        path / SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "preflight_version": PREFLIGHT_VERSION,
            "preflight_id": preflight_id,
            "source_path": str(source),
            "created_at": now_utc(),
        },
        root=path,
    )


def find_packet(queue: dict[str, Any], packet_id: str | None) -> dict[str, Any] | None:
    packets = queue.get("packets")
    if not isinstance(packets, list):
        return None
    for packet in packets:
        if isinstance(packet, dict) and packet.get("id") == packet_id:
            return packet
    return None


def missing_evidence(packet: dict[str, Any]) -> list[str]:
    evidence_paths = packet.get("evidence_paths")
    if not isinstance(evidence_paths, list) or not evidence_paths:
        return ["<missing evidence_paths>"]
    missing = []
    for value in evidence_paths:
        if not isinstance(value, str) or not value:
            missing.append(str(value))
            continue
        path = ROOT / value
        if not path.exists() or path.is_symlink():
            missing.append(value)
    return missing


def preflight_blockers(queue: dict[str, Any], *, expected_hash: str | None = None) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    blockers: list[dict[str, Any]] = []
    actual_hash = canonical_hash(queue)
    if expected_hash is not None and expected_hash != actual_hash:
        blockers.append({"code": "ERR_LARGE_WORKFLOW_QUEUE_PREFLIGHT_SOURCE_HASH_MISMATCH", "expected": expected_hash, "actual": actual_hash})
    if queue.get("status") != "queue-recorded":
        blockers.append({"code": "ERR_LARGE_WORKFLOW_QUEUE_PREFLIGHT_QUEUE_NOT_RECORDED", "message": "queue status is not queue-recorded"})
    next_action = queue.get("next_action")
    if not isinstance(next_action, dict):
        blockers.append({"code": "ERR_LARGE_WORKFLOW_QUEUE_PREFLIGHT_NEXT_ACTION_MISSING", "message": "queue next_action is missing"})
        return blockers, None
    if next_action.get("status") != "ready":
        blockers.append({"code": "ERR_LARGE_WORKFLOW_QUEUE_PREFLIGHT_NEXT_NOT_READY", "message": "queue next_action is not ready", "next_status": next_action.get("status")})
    if next_action.get("blocked_by"):
        blockers.append({"code": "ERR_LARGE_WORKFLOW_QUEUE_PREFLIGHT_NEXT_BLOCKED", "blocked_by": next_action.get("blocked_by")})
    packet = find_packet(queue, next_action.get("packet_id"))
    if packet is None:
        blockers.append({"code": "ERR_LARGE_WORKFLOW_QUEUE_PREFLIGHT_PACKET_MISSING", "message": "selected packet is missing"})
        return blockers, None
    if packet.get("status") != "ready":
        blockers.append({"code": "ERR_LARGE_WORKFLOW_QUEUE_PREFLIGHT_PACKET_NOT_READY", "packet_status": packet.get("status")})
    if packet.get("verification_status") != "pass":
        blockers.append({"code": "ERR_LARGE_WORKFLOW_QUEUE_PREFLIGHT_VERIFICATION_NOT_PASSING", "verification_status": packet.get("verification_status")})
    if packet.get("requires_human"):
        blockers.append({"code": "ERR_LARGE_WORKFLOW_QUEUE_PREFLIGHT_HUMAN_GATE_REQUIRED", "message": "packet requires human approval"})
    risk_codes = packet.get("risk_codes")
    if not isinstance(risk_codes, list) or not all(isinstance(code, str) for code in risk_codes):
        blockers.append({"code": "ERR_LARGE_WORKFLOW_QUEUE_PREFLIGHT_PACKET_INVALID", "field": "risk_codes"})
    command = next_action.get("command") or packet.get("command")
    if not isinstance(command, str) or not command.strip():
        blockers.append({"code": "ERR_LARGE_WORKFLOW_QUEUE_PREFLIGHT_COMMAND_MISSING", "message": "selected command is missing"})
    else:
        safety = assess_command_safety(command, risk_codes)
        for safety_blocker in safety.blocked_by:
            blockers.append({"code": "ERR_LARGE_WORKFLOW_QUEUE_PREFLIGHT_COMMAND_UNSAFE", "command_safety": safety_blocker})
        gated = sorted(set(safety.gated_risk_codes) & GATED_RISK_CODES)
        if gated:
            blockers.append(
                {
                    "code": "ERR_LARGE_WORKFLOW_QUEUE_PREFLIGHT_RISK_GATE_REQUIRED",
                    "risk_codes": gated,
                    "inferred_risk_codes": safety.inferred_risk_codes,
                }
            )
    missing = missing_evidence(packet)
    if missing:
        blockers.append({"code": "ERR_LARGE_WORKFLOW_QUEUE_PREFLIGHT_EVIDENCE_MISSING", "paths": missing})
    return blockers, packet


def make_preflight(preflight_id: str, queue: dict[str, Any], *, queue_path: str, expected_hash: str | None = None) -> dict[str, Any]:
    blockers, packet = preflight_blockers(queue, expected_hash=expected_hash)
    status = "queue-preflight-ready" if not blockers else "queue-preflight-blocked"
    command = None if blockers or packet is None else queue["next_action"].get("command")
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "preflight_version": PREFLIGHT_VERSION,
        "preflight_id": preflight_id,
        "status": status,
        "queue_path": queue_path,
        "packet_id": packet.get("id") if isinstance(packet, dict) else None,
        "command": command,
        "execution_mode": "manual-or-runner-after-preflight",
        "blocked_by": blockers,
        "source_hashes": {"queue": canonical_hash(queue), "packet": canonical_hash(packet) if packet is not None else None},
    }


def render_markdown(preflight: dict[str, Any]) -> str:
    lines = [
        f"# Large Workflow Queue Preflight {preflight['preflight_id']}",
        "",
        f"- Status: `{preflight['status']}`",
        f"- Queue: `{preflight['queue_path']}`",
        f"- Packet: `{preflight['packet_id'] or 'none'}`",
        f"- Command: `{preflight['command'] or 'none'}`",
        f"- Execution mode: `{preflight['execution_mode']}`",
        "",
        "## Blockers",
        "",
    ]
    if preflight["blocked_by"]:
        for blocker in preflight["blocked_by"]:
            lines.append(f"- `{blocker['code']}`: {json.dumps(blocker, sort_keys=True)}")
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def write_preflight(out_dir: Path, preflight: dict[str, Any]) -> None:
    write_json_atomic(out_dir / "queue-preflight.json", preflight, root=out_dir)
    write_json_atomic(
        out_dir / "status.json",
        {
            "schema_version": SCHEMA_VERSION,
            "tool": TOOL,
            "preflight_id": preflight["preflight_id"],
            "status": preflight["status"],
            "queue_path": preflight["queue_path"],
            "packet_id": preflight["packet_id"],
            "blocked_by": preflight["blocked_by"],
            "source_hashes": preflight["source_hashes"],
        },
        root=out_dir,
    )
    write_text_atomic(out_dir / "queue-preflight.md", render_markdown(preflight), root=out_dir)


def run_preflight(queue_path: Path, out_dir: Path, *, expected_hash: str | None = None) -> dict[str, Any]:
    queue_path = resolve_queue(queue_path)
    if not queue_path.is_file() or queue_path.is_symlink():
        raise LargeWorkflowQueuePreflightError("ERR_LARGE_WORKFLOW_QUEUE_PREFLIGHT_QUEUE_MISSING", "queue artifact is missing", path=queue_path)
    queue = read_json(queue_path)
    out_dir = resolve_preflight_out(out_dir)
    prepare_out_dir(out_dir, out_dir.name, source=queue_path)
    preflight = make_preflight(out_dir.name, queue, queue_path=rel(queue_path), expected_hash=expected_hash)
    write_preflight(out_dir, preflight)
    return preflight


def materialize_fixture_queue(fixture: dict[str, Any], fixture_out: Path) -> dict[str, Any]:
    queue = json.loads(json.dumps(fixture["queue"]))
    for packet in queue.get("packets", []):
        if not isinstance(packet, dict):
            continue
        evidence_paths = []
        for value in packet.get("evidence_paths", []):
            if isinstance(value, str) and value.startswith("__fixture_evidence__/"):
                evidence_path = fixture_out / "evidence" / value.removeprefix("__fixture_evidence__/")
                evidence_path.parent.mkdir(parents=True, exist_ok=True)
                evidence_path.write_text("evidence\n")
                evidence_paths.append(rel(evidence_path))
            else:
                evidence_paths.append(value)
        packet["evidence_paths"] = evidence_paths
    return queue


def run_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    fixtures = manifest.get("fixtures")
    if not isinstance(fixtures, list):
        raise LargeWorkflowQueuePreflightError("ERR_LARGE_WORKFLOW_QUEUE_PREFLIGHT_MANIFEST_INVALID", "manifest fixtures must be a list", path=manifest_path)
    suite_id = str(manifest.get("suite_id", "v77-large-workflow-queue-preflight"))
    out_dir = resolve_preflight_out(out_dir)
    prepare_out_dir(out_dir, out_dir.name, source=manifest_path)
    records = []
    for fixture in fixtures:
        if not isinstance(fixture, dict):
            raise LargeWorkflowQueuePreflightError("ERR_LARGE_WORKFLOW_QUEUE_PREFLIGHT_MANIFEST_INVALID", "fixture must be an object", path=manifest_path)
        fixture_id = str(fixture.get("id", "fixture"))
        if not isinstance(fixture.get("queue"), dict):
            raise LargeWorkflowQueuePreflightError("ERR_LARGE_WORKFLOW_QUEUE_PREFLIGHT_MANIFEST_INVALID", "fixture queue must be an object", fixture_id=fixture_id)
        fixture_out = out_dir / fixture_id
        prepare_out_dir(fixture_out, fixture_id, source=manifest_path)
        queue = materialize_fixture_queue(fixture, fixture_out)
        write_json_atomic(fixture_out / "queue.json", queue, root=fixture_out)
        preflight = make_preflight(
            fixture_id,
            queue,
            queue_path=rel(fixture_out / "queue.json"),
            expected_hash=fixture.get("expected_queue_hash"),
        )
        write_preflight(fixture_out, preflight)
        expected_status = fixture.get("expected_status")
        status = "pass" if expected_status in (None, preflight["status"]) else "fail"
        records.append(
            {
                "id": fixture_id,
                "required": bool(fixture.get("required", True)),
                "status": status,
                "preflight_status": preflight["status"],
                "packet_id": preflight["packet_id"],
                "blocked_by": preflight["blocked_by"],
                "error": None if status == "pass" else f"expected {expected_status}, got {preflight['status']}",
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
        raise LargeWorkflowQueuePreflightError("ERR_LARGE_WORKFLOW_QUEUE_PREFLIGHT_FIXTURE_FAILED", "required preflight fixture failed", path=manifest_path)
    return summary


def ready_queue() -> dict[str, Any]:
    return {
        "status": "queue-recorded",
        "queue_id": "fixture-ready",
        "next_action": {"status": "ready", "packet_id": "ready-packet", "command": "python scripts/dwm.py --self-test", "blocked_by": []},
        "packets": [
            {
                "id": "ready-packet",
                "title": "Ready packet",
                "index": 0,
                "status": "ready",
                "command": "python scripts/dwm.py --self-test",
                "risk_codes": ["read-only"],
                "evidence_paths": ["__fixture_evidence__/ready.txt"],
                "verification_status": "pass",
                "requires_human": False,
                "blocked_by": [],
            }
        ],
        "summary": {"ready": 1, "blocked": 0, "pending": 0, "done": 0, "superseded": 0},
        "source_hashes": {"packets": "fixture-packets"},
    }


def self_test() -> None:
    out_dir = PREFLIGHT_ROOT / "self-test-evidence"
    if out_dir.exists():
        shutil.rmtree(out_dir)
    prepare_out_dir(out_dir, "self-test-evidence", source="self-test")
    queue = materialize_fixture_queue({"queue": ready_queue()}, out_dir)
    ready = make_preflight("self-test-ready", queue, queue_path="fixture-queue")
    if ready["status"] != "queue-preflight-ready" or ready["command"] != "python scripts/dwm.py --self-test":
        raise LargeWorkflowQueuePreflightError("ERR_LARGE_WORKFLOW_QUEUE_PREFLIGHT_SELF_TEST_FAILED", "ready queue should pass preflight")
    gated = ready_queue()
    gated["packets"][0]["risk_codes"] = ["write"]
    gated = materialize_fixture_queue({"queue": gated}, out_dir)
    blocked = make_preflight("self-test-gated", gated, queue_path="fixture-queue")
    if blocked["status"] != "queue-preflight-blocked":
        raise LargeWorkflowQueuePreflightError("ERR_LARGE_WORKFLOW_QUEUE_PREFLIGHT_SELF_TEST_FAILED", "write risk should block preflight")
    undeclared_runner = ready_queue()
    undeclared_runner["next_action"]["command"] = "python scripts/dwm_runner.py --manifest fixtures/v13/manifest.json --out out/v13/final"
    undeclared_runner["packets"][0]["command"] = undeclared_runner["next_action"]["command"]
    undeclared_runner["packets"][0]["risk_codes"] = ["read-only", "evidence"]
    undeclared_runner = materialize_fixture_queue({"queue": undeclared_runner}, out_dir)
    undeclared_blocked = make_preflight("self-test-undeclared-runner-risk", undeclared_runner, queue_path="fixture-queue")
    if undeclared_blocked["status"] != "queue-preflight-blocked":
        raise LargeWorkflowQueuePreflightError("ERR_LARGE_WORKFLOW_QUEUE_PREFLIGHT_SELF_TEST_FAILED", "inferred runner write risk should block preflight")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="run V77 preflight self-test")
    parser.add_argument("--manifest", type=Path, help="run preflight fixtures from a manifest")
    parser.add_argument("--out", type=Path, help="output directory under out/large-workflow-queue-preflight")
    subparsers = parser.add_subparsers(dest="command")
    preflight_parser = subparsers.add_parser("preflight", help="preflight one workflow queue")
    preflight_parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    preflight_parser.add_argument("--expected-queue-hash")
    preflight_parser.add_argument("--out", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        if args.self_test:
            self_test()
            print("large workflow queue preflight self-test: pass")
            return
        if args.manifest:
            if args.out is None:
                raise LargeWorkflowQueuePreflightError("ERR_LARGE_WORKFLOW_QUEUE_PREFLIGHT_ARGS_INVALID", "--manifest requires --out")
            summary = run_manifest(args.manifest, args.out)
            print(json.dumps(summary, sort_keys=True))
            return
        if args.command == "preflight":
            preflight = run_preflight(args.queue, args.out, expected_hash=args.expected_queue_hash)
            print(json.dumps({"status": preflight["status"], "preflight_id": preflight["preflight_id"], "packet_id": preflight["packet_id"]}, sort_keys=True))
            return
        raise LargeWorkflowQueuePreflightError("ERR_LARGE_WORKFLOW_QUEUE_PREFLIGHT_ARGS_INVALID", "choose --self-test, --manifest, or preflight")
    except LargeWorkflowQueuePreflightError as exc:
        print(json.dumps({"status": "error", "error": exc.to_record()}, sort_keys=True), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
