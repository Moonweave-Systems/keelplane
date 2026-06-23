#!/usr/bin/env python3
"""V46 long-run workflow queue."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from compile_workflow import canonical_hash, canonical_json_text, read_json, write_json_atomic  # noqa: E402


TOOL = "dwm_workflow_queue.py"
SCHEMA_VERSION = "1.0"
QUEUE_VERSION = "46.0.0"
QUEUE_ROOT = ROOT / "out" / "workflow-queues"
SENTINEL = ".dwm_workflow_queue-owned.json"
TERMINAL_STATUSES = {"done", "superseded"}
ACTIVE_STATUSES = {"pending", "ready", "blocked", "done", "superseded"}
UNSAFE_RISK_CODES = {
    "write",
    "delete",
    "network",
    "deploy",
    "secret",
    "dependency",
    "database",
    "history-rewrite",
    "external-message",
}


class WorkflowQueueError(ValueError):
    """Structured V46 workflow queue failure."""

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
        raise WorkflowQueueError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise WorkflowQueueError(code, "path contains a symlink", path=current)


def resolve_queue_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_DWM_QUEUE_PATH_UNSAFE", message="queue output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = QUEUE_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise WorkflowQueueError("ERR_DWM_QUEUE_PATH_UNSAFE", f"queue output must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise WorkflowQueueError("ERR_DWM_QUEUE_PATH_UNSAFE", "queue output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_DWM_QUEUE_PATH_SYMLINK")
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


def prepare_out_dir(path: Path, queue_id: str, *, source: Path) -> None:
    if path.exists():
        if path.is_symlink():
            raise WorkflowQueueError("ERR_DWM_QUEUE_PATH_SYMLINK", "queue output is a symlink", path=path)
        if not path.is_dir():
            raise WorkflowQueueError("ERR_DWM_QUEUE_PATH_UNSAFE", "queue output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("queue_id") != queue_id:
            raise WorkflowQueueError("ERR_DWM_QUEUE_PATH_UNSAFE", "existing queue output is not queue-owned", path=path)
        shutil.rmtree(path)
    QUEUE_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(
        path / SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "queue_version": QUEUE_VERSION,
            "queue_id": queue_id,
            "source_path": rel(source),
            "created_at": now_utc(),
        },
        root=path,
    )


def normalize_packet(packet: dict[str, Any], index: int) -> dict[str, Any]:
    packet_id = packet.get("id")
    title = packet.get("title")
    if not isinstance(packet_id, str) or not packet_id:
        raise WorkflowQueueError("ERR_DWM_QUEUE_PACKET_INVALID", "packet id is missing")
    if not isinstance(title, str) or not title:
        raise WorkflowQueueError("ERR_DWM_QUEUE_PACKET_INVALID", "packet title is missing")
    status = packet.get("status", "pending")
    if status not in ACTIVE_STATUSES:
        raise WorkflowQueueError("ERR_DWM_QUEUE_PACKET_INVALID", f"invalid packet status: {status}")
    risk_codes = packet.get("risk_codes", [])
    evidence_paths = packet.get("evidence_paths", [])
    verification_status = packet.get("verification_status", "pass")
    requires_human = packet.get("requires_human", False)
    if not isinstance(risk_codes, list) or not all(isinstance(item, str) for item in risk_codes):
        raise WorkflowQueueError("ERR_DWM_QUEUE_PACKET_INVALID", "risk_codes must be strings")
    if not isinstance(evidence_paths, list) or not all(isinstance(item, str) for item in evidence_paths):
        raise WorkflowQueueError("ERR_DWM_QUEUE_PACKET_INVALID", "evidence_paths must be strings")
    if verification_status not in {"pass", "fail", "missing"}:
        raise WorkflowQueueError("ERR_DWM_QUEUE_PACKET_INVALID", "verification_status must be pass, fail, or missing")
    if not isinstance(requires_human, bool):
        raise WorkflowQueueError("ERR_DWM_QUEUE_PACKET_INVALID", "requires_human must be boolean")
    return {
        "id": packet_id,
        "title": title,
        "index": index,
        "status": status,
        "command": packet.get("command", ""),
        "risk_codes": risk_codes,
        "evidence_paths": evidence_paths,
        "verification_status": verification_status,
        "requires_human": requires_human,
        "blocked_by": [],
    }


def missing_evidence(packet: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for value in packet["evidence_paths"]:
        path = ROOT / value
        if not path.exists() or path.is_symlink():
            missing.append(value)
    return missing


def block_packet(packet: dict[str, Any], code: str, message: str, details: list[str] | None = None) -> dict[str, Any]:
    blocked = dict(packet)
    blocked["status"] = "blocked"
    blocked["blocked_by"] = [{"code": code, "message": message, "details": details or []}]
    return blocked


def evaluate_packets(raw_packets: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    packets = [normalize_packet(packet, index) for index, packet in enumerate(raw_packets)]
    selected: dict[str, Any] | None = None
    output: list[dict[str, Any]] = []
    for packet in packets:
        if packet["status"] in TERMINAL_STATUSES:
            output.append(packet)
            continue
        if selected is not None:
            pending = dict(packet)
            pending["status"] = "pending"
            output.append(pending)
            continue
        unsafe = sorted(set(packet["risk_codes"]) & UNSAFE_RISK_CODES)
        missing = missing_evidence(packet)
        if unsafe:
            blocked = block_packet(packet, "ERR_DWM_QUEUE_UNSAFE_ACTION", "packet requires a risk gate before continuation", unsafe)
            output.append(blocked)
            selected = blocked
        elif packet["requires_human"]:
            blocked = block_packet(packet, "ERR_DWM_QUEUE_HUMAN_GATE_REQUIRED", "packet requires human approval before continuation")
            output.append(blocked)
            selected = blocked
        elif missing:
            blocked = block_packet(packet, "ERR_DWM_QUEUE_EVIDENCE_MISSING", "packet evidence paths are missing", missing)
            output.append(blocked)
            selected = blocked
        elif packet["verification_status"] == "fail":
            blocked = block_packet(packet, "ERR_DWM_QUEUE_VERIFICATION_FAILED", "packet verification failed")
            output.append(blocked)
            selected = blocked
        elif packet["verification_status"] == "missing":
            blocked = block_packet(packet, "ERR_DWM_QUEUE_VERIFICATION_MISSING", "packet verification is missing")
            output.append(blocked)
            selected = blocked
        else:
            ready = dict(packet)
            ready["status"] = "ready"
            output.append(ready)
            selected = ready
    if selected is None:
        next_action = {"status": "complete", "packet_id": None, "reason": "no pending packets remain"}
    elif selected["status"] == "ready":
        next_action = {"status": "ready", "packet_id": selected["id"], "command": selected["command"], "blocked_by": []}
    else:
        next_action = {"status": "blocked", "packet_id": selected["id"], "blocked_by": selected["blocked_by"]}
    return output, next_action


def build_queue(packets: list[dict[str, Any]], out_dir: Path, *, queue_id: str, source: Path) -> dict[str, Any]:
    evaluated, next_action = evaluate_packets(packets)
    prepare_out_dir(out_dir, queue_id, source=source)
    queue = {
        "status": "queue-recorded",
        "queue_id": queue_id,
        "packets": evaluated,
        "next_action": next_action,
        "summary": {
            "ready": sum(1 for packet in evaluated if packet["status"] == "ready"),
            "blocked": sum(1 for packet in evaluated if packet["status"] == "blocked"),
            "pending": sum(1 for packet in evaluated if packet["status"] == "pending"),
            "done": sum(1 for packet in evaluated if packet["status"] == "done"),
            "superseded": sum(1 for packet in evaluated if packet["status"] == "superseded"),
        },
        "source_hashes": {"packets": canonical_hash(packets)},
    }
    write_json_atomic(out_dir / "queue.json", queue, root=out_dir)
    write_json_atomic(out_dir / "status.json", queue, root=out_dir)
    (out_dir / "next-action.md").write_text(render_next_action(queue))
    return queue


def render_next_action(queue: dict[str, Any]) -> str:
    next_action = queue["next_action"]
    lines = ["# DWM Queue Next Action", ""]
    lines.append(f"- queue: `{queue['queue_id']}`")
    lines.append(f"- status: `{next_action['status']}`")
    if next_action.get("packet_id"):
        lines.append(f"- packet: `{next_action['packet_id']}`")
    if next_action.get("command"):
        lines.append(f"- command: `{next_action['command']}`")
    blocked_by = next_action.get("blocked_by") or []
    for item in blocked_by:
        lines.append(f"- blocked: `{item['code']}` {item['message']}")
    lines.append("")
    return "\n".join(lines)


def load_queue(queue_dir: Path) -> dict[str, Any]:
    queue_path = queue_dir / "queue.json"
    status_path = queue_dir / "status.json"
    if not queue_path.is_file() or queue_path.is_symlink() or not status_path.is_file() or status_path.is_symlink():
        raise WorkflowQueueError("ERR_DWM_QUEUE_ARTIFACT_MISSING", "queue artifacts are missing", path=queue_dir)
    queue = read_json(queue_path)
    status = read_json(status_path)
    if queue != status:
        raise WorkflowQueueError("ERR_DWM_QUEUE_STALE_STATUS", "queue status and artifact do not match", path=queue_dir)
    if queue.get("status") != "queue-recorded":
        raise WorkflowQueueError("ERR_DWM_QUEUE_STALE_STATUS", "queue is not recorded", path=queue_dir)
    return queue


def resume_queue(queue_dir: Path) -> dict[str, Any]:
    queue = load_queue(queue_dir)
    packets = [{key: packet[key] for key in ["id", "title", "status", "command", "risk_codes", "evidence_paths", "verification_status", "requires_human"]} for packet in queue["packets"]]
    evaluated, next_action = evaluate_packets(packets)
    if evaluated != queue["packets"] or next_action != queue["next_action"]:
        raise WorkflowQueueError("ERR_DWM_QUEUE_STALE_STATUS", "queue no longer matches evaluated packet state", path=queue_dir)
    return queue


def evidence_file(name: str) -> str:
    path = QUEUE_ROOT / "fixture-evidence" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("evidence\n")
    return rel(path)


def fixture_packets(kind: str, suite_id: str) -> list[dict[str, Any]]:
    evidence = evidence_file(f"{suite_id}-{kind}.txt")
    base = {
        "id": f"{kind}-packet",
        "title": f"{kind} packet",
        "command": f"python scripts/dwm.py next --run out/{kind}",
        "evidence_paths": [evidence],
        "verification_status": "pass",
        "risk_codes": [],
        "requires_human": False,
    }
    if kind == "ready":
        return [base, {**base, "id": "second-packet", "title": "second packet"}]
    if kind == "missing-evidence":
        return [{**base, "evidence_paths": ["out/workflow-queues/missing-evidence.txt"]}]
    if kind == "unsafe-action":
        return [{**base, "risk_codes": ["network"]}]
    if kind == "verification-failed":
        return [{**base, "verification_status": "fail"}]
    if kind == "human-gate":
        return [{**base, "requires_human": True}]
    if kind == "complete":
        return [{**base, "status": "done"}]
    raise WorkflowQueueError("ERR_DWM_QUEUE_FIXTURE_FAILED", f"unknown fixture kind: {kind}")


def blocked_fixture_status(kind: str, fixture: dict[str, Any], suite_id: str) -> dict[str, Any]:
    try:
        if kind == "stale-queue":
            queue_dir = QUEUE_ROOT / f"{suite_id}-stale"
            build_queue(fixture_packets("ready", suite_id), queue_dir, queue_id=queue_dir.name, source=Path("fixture"))
            status = read_json(queue_dir / "status.json")
            status["next_action"]["status"] = "blocked"
            write_json_atomic(queue_dir / "status.json", status, root=queue_dir)
            resume_queue(queue_dir)
        else:
            queue = build_queue(fixture_packets(kind, suite_id), QUEUE_ROOT / f"{suite_id}-{kind}", queue_id=f"{suite_id}-{kind}", source=Path("fixture"))
            if queue["next_action"]["status"] != "blocked":
                raise WorkflowQueueError("ERR_DWM_QUEUE_FIXTURE_FAILED", f"{kind} did not block")
            observed = queue["next_action"]["blocked_by"][0]["code"]
            if fixture.get("expected_error") != observed:
                raise WorkflowQueueError("ERR_DWM_QUEUE_FIXTURE_FAILED", f"expected error {fixture.get('expected_error')}, got {observed}")
            return {"status": "blocked", "error": queue["next_action"]["blocked_by"][0]}
    except WorkflowQueueError as exc:
        if fixture.get("expected_error") != exc.code:
            raise
        return {"status": "blocked", "error": exc.to_record()}
    raise WorkflowQueueError("ERR_DWM_QUEUE_FIXTURE_FAILED", f"{kind} unexpectedly passed")


def run_fixture(fixture: dict[str, Any], suite_dir: Path) -> dict[str, Any]:
    fixture_id = fixture["id"]
    try:
        kind = fixture["kind"]
        if kind in {"ready", "complete"}:
            status = build_queue(fixture_packets(kind, suite_dir.name), suite_dir / fixture_id, queue_id=fixture_id, source=Path("fixture"))
        elif kind in {"missing-evidence", "unsafe-action", "verification-failed", "human-gate", "stale-queue"}:
            status = blocked_fixture_status(kind, fixture, suite_dir.name)
        else:
            raise WorkflowQueueError("ERR_DWM_QUEUE_FIXTURE_FAILED", f"unknown fixture kind: {kind}")
        expected_status = fixture.get("expected_status")
        observed_status = status.get("next_action", {}).get("status", status.get("status"))
        if expected_status is not None and observed_status != expected_status:
            raise WorkflowQueueError("ERR_DWM_QUEUE_FIXTURE_FAILED", f"expected status {expected_status}, got {observed_status}")
        return {"id": fixture_id, "status": "pass", "observed_status": observed_status, "required": fixture.get("required", True)}
    except WorkflowQueueError as exc:
        record = exc.to_record()
        record["fixture_id"] = fixture_id
        return {"id": fixture_id, "status": "fail", "required": fixture.get("required", True), "error": record}


def evaluate_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    suite_id = Path(out_dir).name
    suite_dir = resolve_queue_out(out_dir)
    if suite_dir.exists():
        sentinel = read_sentinel(suite_dir)
        if sentinel is None or sentinel.get("queue_id") != suite_id:
            raise WorkflowQueueError("ERR_DWM_QUEUE_PATH_UNSAFE", "existing queue suite is not queue-owned", path=suite_dir)
        shutil.rmtree(suite_dir)
    prepare_out_dir(suite_dir, suite_id, source=manifest_path)
    fixtures = manifest["fixtures"]
    required_ids = set(manifest["required_fixture_ids"])
    results = [run_fixture(fixture, suite_dir) for fixture in fixtures]
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
        "source_hashes": {"manifest": canonical_hash(manifest)},
    }
    write_json_atomic(suite_dir / "summary.json", summary, root=suite_dir)
    if summary["decision"] != "keep":
        raise WorkflowQueueError("ERR_DWM_QUEUE_FIXTURE_FAILED", "manifest decision is kill", path=manifest_path)
    return summary


def self_test() -> None:
    QUEUE_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dwm-workflow-queue-self-test-", dir=QUEUE_ROOT) as tmp:
        summary = evaluate_manifest(ROOT / "fixtures" / "v46" / "manifest.json", Path(tmp) / "workflow-queue-self-test")
    if summary["decision"] != "keep":
        raise WorkflowQueueError("ERR_DWM_QUEUE_FIXTURE_FAILED", "workflow queue self-test manifest did not keep")
    print("dwm_workflow_queue self-test: pass")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", choices=["create", "resume"])
    parser.add_argument("--manifest")
    parser.add_argument("--out")
    parser.add_argument("--packets")
    parser.add_argument("--queue")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
        elif args.manifest:
            if not args.out:
                raise WorkflowQueueError("ERR_DWM_QUEUE_PATH_UNSAFE", "--manifest requires --out")
            summary = evaluate_manifest(Path(args.manifest), Path(args.out))
            print(canonical_json_text({key: summary[key] for key in ["suite_id", "fixture_count", "required_fixture_count", "required_passed", "passed", "failed", "skipped", "decision"]}))
        elif args.command == "create":
            if not args.out or not args.packets:
                raise WorkflowQueueError("ERR_DWM_QUEUE_PATH_UNSAFE", "create requires --packets and --out")
            packets = read_json(Path(args.packets))
            if not isinstance(packets, list):
                raise WorkflowQueueError("ERR_DWM_QUEUE_PACKET_INVALID", "packets file must contain a list", path=args.packets)
            status = build_queue(packets, resolve_queue_out(args.out), queue_id=Path(args.out).name, source=Path(args.packets))
            print(canonical_json_text(status))
        elif args.command == "resume":
            if not args.queue:
                raise WorkflowQueueError("ERR_DWM_QUEUE_PATH_UNSAFE", "resume requires --queue")
            status = resume_queue(Path(args.queue))
            print(canonical_json_text(status))
        else:
            parser.error("expected --self-test, --manifest, create, or resume")
    except WorkflowQueueError as exc:
        print(canonical_json_text(exc.to_record()), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
