#!/usr/bin/env python3
"""V75 large-workflow next-action selector."""

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


TOOL = "dwm_large_workflow_next.py"
SCHEMA_VERSION = "1.0"
NEXT_VERSION = "75.0.0"
NEXT_ROOT = ROOT / "out" / "large-workflow-next"
DEFAULT_CONTROL = ROOT / "out" / "large-workflow-dogfood" / "v74-canonical" / "dogfood-control.json"
SENTINEL = ".dwm_large_workflow_next-owned.json"

FORBIDDEN_CLAIM_TERMS = ["external benchmark superiority", "guaranteed best quality", "always autonomous", "no human gate needed"]


class LargeWorkflowNextError(ValueError):
    """Structured V75 next-action selection failure."""

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
        raise LargeWorkflowNextError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise LargeWorkflowNextError(code, "path contains a symlink", path=current)


def resolve_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_LARGE_WORKFLOW_NEXT_PATH_UNSAFE", message="next output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = NEXT_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise LargeWorkflowNextError("ERR_LARGE_WORKFLOW_NEXT_PATH_UNSAFE", f"next output must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise LargeWorkflowNextError("ERR_LARGE_WORKFLOW_NEXT_PATH_UNSAFE", "next output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_LARGE_WORKFLOW_NEXT_PATH_SYMLINK")
    return resolved


def resolve_control(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_LARGE_WORKFLOW_NEXT_CONTROL_UNSAFE", message="control path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    out_resolved = (ROOT / "out").resolve(strict=False)
    try:
        resolved.relative_to(out_resolved)
    except ValueError as exc:
        raise LargeWorkflowNextError("ERR_LARGE_WORKFLOW_NEXT_CONTROL_UNSAFE", "control path must resolve under out", path=value) from exc
    check_components_not_symlink(candidate, code="ERR_LARGE_WORKFLOW_NEXT_PATH_SYMLINK")
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


def prepare_out_dir(path: Path, next_id: str, *, source: Path | str) -> None:
    if path.exists():
        if path.is_symlink():
            raise LargeWorkflowNextError("ERR_LARGE_WORKFLOW_NEXT_PATH_SYMLINK", "next output is a symlink", path=path)
        if not path.is_dir():
            raise LargeWorkflowNextError("ERR_LARGE_WORKFLOW_NEXT_PATH_UNSAFE", "next output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("next_id") != next_id:
            raise LargeWorkflowNextError("ERR_LARGE_WORKFLOW_NEXT_PATH_UNSAFE", "existing next output is not next-owned", path=path)
        shutil.rmtree(path)
    NEXT_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(
        path / SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "next_version": NEXT_VERSION,
            "next_id": next_id,
            "source_path": str(source),
            "created_at": now_utc(),
        },
        root=path,
    )


def detect_overclaims(value: Any) -> list[str]:
    text_values: list[str] = []
    if isinstance(value, dict):
        for key in ["objective", "summary", "public_claim"]:
            item = value.get(key)
            if isinstance(item, str):
                text_values.append(item.lower())
    combined = " ".join(text_values)
    return [term for term in FORBIDDEN_CLAIM_TERMS if term in combined]


def control_blockers(control: dict[str, Any], *, expected_hash: str | None = None) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    actual_hash = canonical_hash(control)
    if expected_hash is not None and expected_hash != actual_hash:
        blockers.append({"code": "ERR_LARGE_WORKFLOW_NEXT_SOURCE_HASH_MISMATCH", "expected": expected_hash, "actual": actual_hash})
    if control.get("status") != "dogfood-control-recorded":
        blockers.append({"code": "ERR_LARGE_WORKFLOW_NEXT_DOGFOOD_NOT_RECORDED", "message": "dogfood control receipt is not recorded"})
    if control.get("blocked_by"):
        blockers.append({"code": "ERR_LARGE_WORKFLOW_NEXT_DOGFOOD_BLOCKED", "message": "dogfood control receipt contains blockers"})
    embedded = control.get("control")
    if not isinstance(embedded, dict):
        blockers.append({"code": "ERR_LARGE_WORKFLOW_NEXT_CONTROL_MISSING", "message": "embedded large-workflow control is missing"})
    else:
        if embedded.get("status") != "large-workflow-controlled":
            blockers.append({"code": "ERR_LARGE_WORKFLOW_NEXT_CONTROL_NOT_READY", "message": "embedded large-workflow control is not controlled"})
        if embedded.get("total_score") != embedded.get("max_score"):
            blockers.append({"code": "ERR_LARGE_WORKFLOW_NEXT_CONTROL_SCORE_INCOMPLETE", "message": "embedded large-workflow control score is incomplete"})
    source_hashes = control.get("source_hashes")
    if not isinstance(source_hashes, dict) or not {"run_status", "workflow", "control"}.issubset(source_hashes):
        blockers.append({"code": "ERR_LARGE_WORKFLOW_NEXT_SOURCE_HASHES_MISSING", "message": "dogfood control source hashes are incomplete"})
    return blockers


def candidate_blockers(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    if not candidates:
        return [{"code": "ERR_LARGE_WORKFLOW_NEXT_CANDIDATES_MISSING", "message": "no next-workflow candidates provided"}]
    for index, candidate in enumerate(candidates):
        candidate_id = candidate.get("id")
        if not isinstance(candidate_id, str) or not candidate_id.strip():
            blockers.append({"code": "ERR_LARGE_WORKFLOW_NEXT_CANDIDATE_INVALID", "message": "candidate id is required", "index": index})
            continue
        if candidate_id in seen_ids:
            blockers.append({"code": "ERR_LARGE_WORKFLOW_NEXT_CANDIDATE_DUPLICATE", "candidate_id": candidate_id})
        seen_ids.add(candidate_id)
        for field in ["objective", "next_command"]:
            if not isinstance(candidate.get(field), str) or not candidate[field].strip():
                blockers.append({"code": "ERR_LARGE_WORKFLOW_NEXT_CANDIDATE_INVALID", "candidate_id": candidate_id, "field": field})
        if not isinstance(candidate.get("priority"), int):
            blockers.append({"code": "ERR_LARGE_WORKFLOW_NEXT_CANDIDATE_INVALID", "candidate_id": candidate_id, "field": "priority"})
        for field in ["risk_codes", "success_criteria", "evidence_requirements", "claim_limits"]:
            if not isinstance(candidate.get(field), list) or not candidate[field]:
                blockers.append({"code": "ERR_LARGE_WORKFLOW_NEXT_CANDIDATE_INVALID", "candidate_id": candidate_id, "field": field})
        safety = assess_command_safety(str(candidate.get("next_command", "")), candidate.get("risk_codes"))
        for blocker in safety.blocked_by:
            blockers.append({"code": "ERR_LARGE_WORKFLOW_NEXT_COMMAND_UNSAFE", "candidate_id": candidate_id, "command_safety": blocker})
        overclaims = detect_overclaims(candidate)
        if overclaims:
            blockers.append({"code": "ERR_LARGE_WORKFLOW_NEXT_CANDIDATE_OVERCLAIM", "candidate_id": candidate_id, "terms": overclaims})
    return blockers


def sort_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(candidates, key=lambda item: (-int(item["priority"]), str(item["id"])))


def default_candidates() -> list[dict[str, Any]]:
    return [
        {
            "id": "large-workflow-queue-refresh",
            "objective": "Refresh the large-workflow queue from current dogfood control evidence before selecting more public benchmark or README graph work.",
            "priority": 90,
            "risk_codes": ["read-only", "evidence"],
            "next_command": "python scripts/dwm_workflow_queue.py --manifest fixtures/v46/manifest.json --out out/workflow-queues/v46-final",
            "success_criteria": ["queue artifact generated", "source evidence remains local", "no public benchmark claim promoted"],
            "evidence_requirements": ["dogfood-control.json", "large-workflow-control.json", "queue.json", "next-action.md"],
            "claim_limits": ["internal workflow selection only", "no external benchmark superiority"],
        },
        {
            "id": "dogfood-control-refresh",
            "objective": "Refresh canonical dogfood control if source status changes before continuing the long workflow.",
            "priority": 70,
            "risk_codes": ["read-only", "evidence"],
            "next_command": "python scripts/dwm_large_workflow_dogfood.py record --run out/v9/v32-semantic-dogfood --out out/large-workflow-dogfood/v74-canonical",
            "success_criteria": ["dogfood-control-recorded", "large-workflow-controlled", "source hashes updated"],
            "evidence_requirements": ["status.json", "dogfood-control.json", "large-workflow-control.json"],
            "claim_limits": ["local dogfood control evidence only"],
        },
    ]


def make_selection(next_id: str, control: dict[str, Any], candidates: list[dict[str, Any]], *, control_path: str, expected_hash: str | None = None) -> dict[str, Any]:
    blockers = control_blockers(control, expected_hash=expected_hash)
    candidate_issues = candidate_blockers(candidates)
    blockers.extend(candidate_issues)
    ordered_candidates = [] if candidate_issues else sort_candidates(candidates)
    selected = ordered_candidates[0] if ordered_candidates else None
    command_safety = assess_command_safety(selected["next_command"], selected.get("risk_codes")) if selected is not None else None
    gated_by: list[dict[str, Any]] = []
    if command_safety is not None:
        gated_codes = sorted(set(command_safety.gated_risk_codes) & GATED_RISK_CODES)
        if gated_codes:
            gated_by.append(
                {
                    "code": "ERR_LARGE_WORKFLOW_NEXT_HUMAN_GATE_REQUIRED",
                    "risk_codes": gated_codes,
                    "inferred_risk_codes": command_safety.inferred_risk_codes,
                    "safe_default": "stop before command execution and request human approval",
                }
            )
    if blockers:
        status = "next-workflow-blocked"
        decision = "blocked"
        command = None
    elif gated_by:
        status = "next-workflow-gate-required"
        decision = "human_gate_required"
        command = None
    else:
        status = "next-workflow-ready"
        decision = "command_ready"
        command = selected["next_command"] if selected is not None else None
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "next_version": NEXT_VERSION,
        "next_id": next_id,
        "status": status,
        "decision": decision,
        "control_path": control_path,
        "selected_candidate": selected,
        "candidate_count": len(candidates),
        "ordered_candidate_ids": [candidate["id"] for candidate in ordered_candidates],
        "command": command,
        "command_safety": command_safety.to_record() if command_safety is not None else None,
        "gated_by": gated_by,
        "blocked_by": blockers,
        "source_hashes": {
            "control": canonical_hash(control),
            "candidates": canonical_hash(candidates),
            "selected_candidate": canonical_hash(selected) if selected is not None else None,
            "command_safety": canonical_hash(command_safety.to_record()) if command_safety is not None else None,
        },
    }


def render_markdown(selection: dict[str, Any]) -> str:
    selected = selection.get("selected_candidate") or {}
    lines = [
        f"# Large Workflow Next {selection['next_id']}",
        "",
        f"- Status: `{selection['status']}`",
        f"- Decision: `{selection['decision']}`",
        f"- Control: `{selection['control_path']}`",
        f"- Selected candidate: `{selected.get('id', 'none')}`",
        f"- Command: `{selection['command'] or 'none'}`",
        "",
        "## Blockers",
        "",
    ]
    if selection["blocked_by"]:
        for blocker in selection["blocked_by"]:
            lines.append(f"- `{blocker['code']}`: {json.dumps(blocker, sort_keys=True)}")
    else:
        lines.append("- none")
    lines.extend(["", "## Gates", ""])
    if selection["gated_by"]:
        for gate in selection["gated_by"]:
            lines.append(f"- `{gate['code']}`: {json.dumps(gate, sort_keys=True)}")
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def write_selection(out_dir: Path, selection: dict[str, Any]) -> None:
    write_json_atomic(out_dir / "large-workflow-next.json", selection, root=out_dir)
    write_json_atomic(
        out_dir / "status.json",
        {
            "schema_version": SCHEMA_VERSION,
            "tool": TOOL,
            "next_id": selection["next_id"],
            "status": selection["status"],
            "decision": selection["decision"],
            "selected_candidate_id": (selection["selected_candidate"] or {}).get("id"),
            "blocked_by": selection["blocked_by"],
            "gated_by": selection["gated_by"],
            "source_hashes": selection["source_hashes"],
        },
        root=out_dir,
    )
    write_text_atomic(out_dir / "large-workflow-next.md", render_markdown(selection), root=out_dir)


def read_candidates(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return default_candidates()
    data = read_json(path)
    candidates = data.get("candidates") if isinstance(data, dict) else data
    if not isinstance(candidates, list):
        raise LargeWorkflowNextError("ERR_LARGE_WORKFLOW_NEXT_CANDIDATES_INVALID", "candidates must be a list", path=path)
    return [candidate for candidate in candidates if isinstance(candidate, dict)]


def run_select(control_path: Path, out_dir: Path, *, candidates_path: Path | None = None, expected_hash: str | None = None) -> dict[str, Any]:
    control_path = resolve_control(control_path)
    if not control_path.is_file() or control_path.is_symlink():
        raise LargeWorkflowNextError("ERR_LARGE_WORKFLOW_NEXT_CONTROL_MISSING", "control receipt is missing", path=control_path)
    control = read_json(control_path)
    candidates = read_candidates(candidates_path)
    out_dir = resolve_out(out_dir)
    prepare_out_dir(out_dir, out_dir.name, source=control_path)
    selection = make_selection(out_dir.name, control, candidates, control_path=rel(control_path), expected_hash=expected_hash)
    write_selection(out_dir, selection)
    return selection


def run_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    fixtures = manifest.get("fixtures")
    if not isinstance(fixtures, list):
        raise LargeWorkflowNextError("ERR_LARGE_WORKFLOW_NEXT_MANIFEST_INVALID", "manifest fixtures must be a list", path=manifest_path)
    suite_id = str(manifest.get("suite_id", "v75-large-workflow-next"))
    out_dir = resolve_out(out_dir)
    prepare_out_dir(out_dir, out_dir.name, source=manifest_path)
    records = []
    for fixture in fixtures:
        if not isinstance(fixture, dict):
            raise LargeWorkflowNextError("ERR_LARGE_WORKFLOW_NEXT_MANIFEST_INVALID", "fixture must be an object", path=manifest_path)
        fixture_id = str(fixture.get("id", "fixture"))
        control = fixture.get("control")
        candidates = fixture.get("candidates", default_candidates())
        if not isinstance(control, dict):
            raise LargeWorkflowNextError("ERR_LARGE_WORKFLOW_NEXT_MANIFEST_INVALID", "fixture control must be an object", fixture_id=fixture_id)
        if not isinstance(candidates, list) or not all(isinstance(candidate, dict) for candidate in candidates):
            raise LargeWorkflowNextError("ERR_LARGE_WORKFLOW_NEXT_MANIFEST_INVALID", "fixture candidates must be a list of objects", fixture_id=fixture_id)
        fixture_out = out_dir / fixture_id
        prepare_out_dir(fixture_out, fixture_id, source=manifest_path)
        selection = make_selection(
            fixture_id,
            control,
            candidates,
            control_path=str(fixture.get("control_path", "fixture-control")),
            expected_hash=fixture.get("expected_control_hash"),
        )
        write_selection(fixture_out, selection)
        expected_status = fixture.get("expected_status")
        expected_decision = fixture.get("expected_decision")
        status_ok = expected_status in (None, selection["status"])
        decision_ok = expected_decision in (None, selection["decision"])
        status = "pass" if status_ok and decision_ok else "fail"
        records.append(
            {
                "id": fixture_id,
                "required": bool(fixture.get("required", True)),
                "status": status,
                "next_status": selection["status"],
                "decision": selection["decision"],
                "selected_candidate_id": (selection["selected_candidate"] or {}).get("id"),
                "blocked_by": selection["blocked_by"],
                "gated_by": selection["gated_by"],
                "error": None if status == "pass" else f"expected {expected_status}/{expected_decision}, got {selection['status']}/{selection['decision']}",
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
        raise LargeWorkflowNextError("ERR_LARGE_WORKFLOW_NEXT_FIXTURE_FAILED", "required next-action fixture failed", path=manifest_path)
    return summary


def ready_control() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": "dwm_large_workflow_dogfood.py",
        "status": "dogfood-control-recorded",
        "dogfood_id": "fixture-ready",
        "blocked_by": [],
        "control": {"status": "large-workflow-controlled", "total_score": 12, "max_score": 12, "blocked_by": []},
        "source_hashes": {"run_status": "fixture-run", "workflow": "fixture-workflow", "control": "fixture-control"},
    }


def self_test() -> None:
    ready = make_selection("self-test-ready", ready_control(), default_candidates(), control_path="fixture-control")
    if ready["status"] != "next-workflow-ready" or ready["decision"] != "command_ready":
        raise LargeWorkflowNextError("ERR_LARGE_WORKFLOW_NEXT_SELF_TEST_FAILED", "ready control should produce a command")
    blocked_control = ready_control()
    blocked_control["status"] = "dogfood-control-blocked"
    blocked = make_selection("self-test-blocked", blocked_control, default_candidates(), control_path="fixture-control")
    if blocked["status"] != "next-workflow-blocked":
        raise LargeWorkflowNextError("ERR_LARGE_WORKFLOW_NEXT_SELF_TEST_FAILED", "blocked control should block next action")
    gated_candidates = default_candidates()
    gated_candidates[0] = {**gated_candidates[0], "risk_codes": ["write"]}
    gated = make_selection("self-test-gated", ready_control(), gated_candidates, control_path="fixture-control")
    if gated["status"] != "next-workflow-gate-required" or gated["command"] is not None:
        raise LargeWorkflowNextError("ERR_LARGE_WORKFLOW_NEXT_SELF_TEST_FAILED", "write-risk candidate should require a gate")
    undeclared_runner_candidates = default_candidates()
    undeclared_runner_candidates[0] = {
        **undeclared_runner_candidates[0],
        "risk_codes": ["read-only", "evidence"],
        "next_command": "python scripts/dwm_runner.py --manifest fixtures/v13/manifest.json --out out/v13/final",
    }
    undeclared_runner = make_selection("self-test-undeclared-runner-risk", ready_control(), undeclared_runner_candidates, control_path="fixture-control")
    if undeclared_runner["status"] != "next-workflow-gate-required" or undeclared_runner["command"] is not None:
        raise LargeWorkflowNextError("ERR_LARGE_WORKFLOW_NEXT_SELF_TEST_FAILED", "inferred runner write risk should require a gate")
    drifted = make_selection("self-test-drifted", ready_control(), default_candidates(), control_path="fixture-control", expected_hash="wrong")
    if drifted["status"] != "next-workflow-blocked":
        raise LargeWorkflowNextError("ERR_LARGE_WORKFLOW_NEXT_SELF_TEST_FAILED", "hash mismatch should block")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="run V75 next-action selector self-test")
    parser.add_argument("--manifest", type=Path, help="run next-action fixtures from a manifest")
    parser.add_argument("--out", type=Path, help="output directory under out/large-workflow-next")
    subparsers = parser.add_subparsers(dest="command")
    select_parser = subparsers.add_parser("select", help="select the next large-workflow action from a dogfood control receipt")
    select_parser.add_argument("--control", type=Path, default=DEFAULT_CONTROL)
    select_parser.add_argument("--candidates", type=Path)
    select_parser.add_argument("--expected-control-hash")
    select_parser.add_argument("--out", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        if args.self_test:
            self_test()
            print("large workflow next self-test: pass")
            return
        if args.manifest:
            if args.out is None:
                raise LargeWorkflowNextError("ERR_LARGE_WORKFLOW_NEXT_ARGS_INVALID", "--manifest requires --out")
            summary = run_manifest(args.manifest, args.out)
            print(json.dumps(summary, sort_keys=True))
            return
        if args.command == "select":
            selection = run_select(args.control, args.out, candidates_path=args.candidates, expected_hash=args.expected_control_hash)
            print(json.dumps({"status": selection["status"], "decision": selection["decision"], "next_id": selection["next_id"]}, sort_keys=True))
            return
        raise LargeWorkflowNextError("ERR_LARGE_WORKFLOW_NEXT_ARGS_INVALID", "choose --self-test, --manifest, or select")
    except LargeWorkflowNextError as exc:
        print(json.dumps({"status": "error", "error": exc.to_record()}, sort_keys=True), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
