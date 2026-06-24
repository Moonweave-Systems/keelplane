#!/usr/bin/env python3
"""V93 workflow narrative and Depone Control Deck renderer."""

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


TOOL = "dwm_workflow_narrative.py"
NARRATIVE_VERSION = "93.0.0"
NARRATIVE_ROOT = ROOT / "out" / "workflow-narratives"
SENTINEL = ".dwm_workflow_narrative-owned.json"
DEFAULT_ROADMAP = ROOT / "out" / "roadmap-reconciliations" / "v88-canonical" / "roadmap-reconciliation.json"
DEFAULT_COMMAND_SAFETY = ROOT / "out" / "command-safety" / "v89-final" / "summary.json"
DEFAULT_ACTIVATION = ROOT / "out" / "workflow-activations" / "v90-canonical" / "workflow-activation.json"
DEFAULT_ORACLE = ROOT / "out" / "evidence-oracles" / "v92-canonical" / "evidence-oracle.json"


class WorkflowNarrativeError(ValueError):
    """Structured V93 workflow narrative failure."""

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
        raise WorkflowNarrativeError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise WorkflowNarrativeError(code, "path contains a symlink", path=current)


def resolve_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_WORKFLOW_NARRATIVE_PATH_UNSAFE", message="narrative output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = NARRATIVE_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise WorkflowNarrativeError("ERR_WORKFLOW_NARRATIVE_PATH_UNSAFE", f"narrative output must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise WorkflowNarrativeError("ERR_WORKFLOW_NARRATIVE_PATH_UNSAFE", "narrative output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_WORKFLOW_NARRATIVE_PATH_SYMLINK")
    return resolved


def resolve_input(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_WORKFLOW_NARRATIVE_INPUT_UNSAFE", message="narrative input path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(ROOT.resolve(strict=False))
    except ValueError as exc:
        raise WorkflowNarrativeError("ERR_WORKFLOW_NARRATIVE_INPUT_UNSAFE", "narrative input must resolve inside this repository", path=value) from exc
    check_components_not_symlink(candidate, code="ERR_WORKFLOW_NARRATIVE_PATH_SYMLINK")
    if not resolved.is_file() or resolved.is_symlink():
        raise WorkflowNarrativeError("ERR_WORKFLOW_NARRATIVE_INPUT_MISSING", "narrative input is missing or unsafe", path=value)
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


def prepare_out_dir(path: Path, narrative_id: str, *, source: Path | str) -> None:
    if path.exists():
        if path.is_symlink():
            raise WorkflowNarrativeError("ERR_WORKFLOW_NARRATIVE_PATH_SYMLINK", "narrative output is a symlink", path=path)
        if not path.is_dir():
            raise WorkflowNarrativeError("ERR_WORKFLOW_NARRATIVE_PATH_UNSAFE", "narrative output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("narrative_id") != narrative_id:
            raise WorkflowNarrativeError("ERR_WORKFLOW_NARRATIVE_PATH_UNSAFE", "existing narrative output is not narrative-owned", path=path)
        shutil.rmtree(path)
    NARRATIVE_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(
        path / SENTINEL,
        {
            "tool": TOOL,
            "narrative_version": NARRATIVE_VERSION,
            "narrative_id": narrative_id,
            "source_path": str(source),
            "created_at": now_utc(),
        },
        root=path,
    )


def stage(stage_id: str, label: str, status: str, line: str, evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": stage_id,
        "label": label,
        "status": status,
        "line": line,
        "evidence": evidence,
    }


def add_blocker(blockers: list[dict[str, Any]], code: str, message: str, *, surface: str, actual: Any = None, expected: Any = None) -> None:
    record: dict[str, Any] = {"code": code, "message": message, "surface": surface}
    if actual is not None:
        record["actual"] = actual
    if expected is not None:
        record["expected"] = expected
    blockers.append(record)


def required_passed(summary: dict[str, Any]) -> bool:
    return summary.get("required_fixture_count") is None or summary.get("required_passed") == summary.get("required_fixture_count")


def make_narrative(
    narrative_id: str,
    roadmap: dict[str, Any],
    command_safety: dict[str, Any],
    activation: dict[str, Any],
    oracle: dict[str, Any],
    *,
    source_paths: dict[str, str] | None = None,
) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []

    roadmap_latest = (roadmap.get("policy") or {}).get("latest_version")
    if roadmap.get("decision") != "roadmap_reconciled":
        add_blocker(blockers, "ERR_WORKFLOW_NARRATIVE_ROADMAP_NOT_READY", "roadmap is not reconciled", surface="roadmap", actual=roadmap.get("decision"), expected="roadmap_reconciled")
    if roadmap_latest != "V117":
        add_blocker(blockers, "ERR_WORKFLOW_NARRATIVE_ROADMAP_STALE", "roadmap latest version is stale", surface="roadmap", actual=roadmap_latest, expected="V117")
    if roadmap.get("blocked_by"):
        add_blocker(blockers, "ERR_WORKFLOW_NARRATIVE_ROADMAP_BLOCKED", "roadmap contains blockers", surface="roadmap")

    if command_safety.get("decision") != "keep":
        add_blocker(blockers, "ERR_WORKFLOW_NARRATIVE_COMMAND_SAFETY_NOT_READY", "command safety did not keep", surface="command_safety", actual=command_safety.get("decision"), expected="keep")
    if command_safety.get("failed") not in (0, None):
        add_blocker(blockers, "ERR_WORKFLOW_NARRATIVE_COMMAND_SAFETY_FAILED", "command safety fixtures failed", surface="command_safety", actual=command_safety.get("failed"), expected=0)
    if not required_passed(command_safety):
        add_blocker(blockers, "ERR_WORKFLOW_NARRATIVE_COMMAND_SAFETY_INCOMPLETE", "command safety required fixtures are incomplete", surface="command_safety")

    if activation.get("decision") != "ready_for_next_workflow_design":
        add_blocker(blockers, "ERR_WORKFLOW_NARRATIVE_ACTIVATION_NOT_READY", "workflow activation is not ready", surface="activation", actual=activation.get("decision"), expected="ready_for_next_workflow_design")
    if activation.get("blocked_by"):
        add_blocker(blockers, "ERR_WORKFLOW_NARRATIVE_ACTIVATION_BLOCKED", "workflow activation contains blockers", surface="activation")
    activation_inputs = activation.get("inputs") if isinstance(activation.get("inputs"), dict) else {}
    if activation_inputs.get("roadmap_latest_version") != "V117":
        add_blocker(blockers, "ERR_WORKFLOW_NARRATIVE_ACTIVATION_ROADMAP_STALE", "activation consumed a stale roadmap version", surface="activation", actual=activation_inputs.get("roadmap_latest_version"), expected="V117")
    source_hashes = activation.get("source_hashes") if isinstance(activation.get("source_hashes"), dict) else {}
    if source_hashes.get("roadmap_reconciliation") != canonical_hash(roadmap):
        add_blocker(blockers, "ERR_WORKFLOW_NARRATIVE_ROADMAP_HASH_DRIFT", "activation roadmap hash does not match current roadmap artifact", surface="activation")
    if source_hashes.get("command_safety") != canonical_hash(command_safety):
        add_blocker(blockers, "ERR_WORKFLOW_NARRATIVE_COMMAND_SAFETY_HASH_DRIFT", "activation command-safety hash does not match current command-safety artifact", surface="activation")

    if oracle.get("decision") != "evidence_verified":
        add_blocker(blockers, "ERR_WORKFLOW_NARRATIVE_ORACLE_NOT_VERIFIED", "evidence oracle did not verify claims", surface="oracle", actual=oracle.get("decision"), expected="evidence_verified")
    if oracle.get("blocked_by"):
        add_blocker(blockers, "ERR_WORKFLOW_NARRATIVE_ORACLE_BLOCKED", "evidence oracle contains blockers", surface="oracle")
    if (oracle.get("execution_policy") or {}).get("executes_commands") is not False:
        add_blocker(blockers, "ERR_WORKFLOW_NARRATIVE_ORACLE_EXECUTION_POLICY", "oracle execution policy is not read-only", surface="oracle")

    stages = [
        stage(
            "chart",
            "Chart",
            "clear" if roadmap.get("decision") == "roadmap_reconciled" and roadmap_latest == "V117" and not roadmap.get("blocked_by") else "blocked",
            f"Chart: roadmap reconciled at {roadmap_latest or 'unknown'}",
            {"decision": roadmap.get("decision"), "latest_version": roadmap_latest},
        ),
        stage(
            "gate",
            "Gate",
            "clear" if command_safety.get("decision") == "keep" and command_safety.get("failed") in (0, None) and required_passed(command_safety) else "blocked",
            "Gate: command safety clear" if command_safety.get("decision") == "keep" else "Gate: command safety blocked",
            {"decision": command_safety.get("decision"), "required_passed": command_safety.get("required_passed"), "required_fixture_count": command_safety.get("required_fixture_count")},
        ),
        stage(
            "activation",
            "Activation",
            "clear" if activation.get("decision") == "ready_for_next_workflow_design" and not activation.get("blocked_by") else "blocked",
            f"Activation: {activation.get('decision', 'unknown')}",
            {"decision": activation.get("decision"), "next_safe_action": activation.get("next_safe_action")},
        ),
        stage(
            "oracle",
            "Oracle",
            "clear" if oracle.get("decision") == "evidence_verified" and not oracle.get("blocked_by") else "blocked",
            "Oracle: evidence claims verified" if oracle.get("decision") == "evidence_verified" else "Oracle: evidence claims blocked",
            {"decision": oracle.get("decision"), "assertion_count": oracle.get("assertion_count"), "artifact_count": oracle.get("artifact_count")},
        ),
    ]
    decision = "control_deck_ready" if not blockers else "blocked"
    next_move = activation.get("next_safe_action") if decision == "control_deck_ready" else "preserve_artifacts_and_fix_blockers"
    return {
        "schema_version": NARRATIVE_VERSION,
        "tool": TOOL,
        "narrative_id": narrative_id,
        "decision": decision,
        "blocked_by": blockers,
        "surface": "Depone Control Deck",
        "voice_policy": {
            "uses_evocative_labels": True,
            "labels_are_status_rendering_only": True,
            "does_not_claim_autonomous_execution": True,
            "source_of_truth": "artifact assertions and source hashes",
        },
        "control_deck": {
            "chart": stages[0]["status"],
            "gate": stages[1]["status"],
            "activation": stages[2]["status"],
            "oracle": stages[3]["status"],
            "next_move": next_move,
        },
        "stages": stages,
        "narrative_lines": [item["line"] for item in stages] + [f"Next move: {next_move}"],
        "source_paths": source_paths or {},
        "source_hashes": {
            "roadmap": canonical_hash(roadmap),
            "command_safety": canonical_hash(command_safety),
            "activation": canonical_hash(activation),
            "oracle": canonical_hash(oracle),
        },
        "execution_policy": {
            "executes_commands": False,
            "creates_worktrees": False,
            "uses_network": False,
            "renders_status_only": True,
        },
    }


def render_markdown(narrative: dict[str, Any]) -> str:
    lines = [
        "# Depone Control Deck",
        "",
        f"- Decision: `{narrative['decision']}`",
        f"- Next move: `{narrative['control_deck']['next_move']}`",
        "- Source of truth: artifact assertions and source hashes",
        f"- Executes commands: `{narrative['execution_policy']['executes_commands']}`",
        "",
        "## Signals",
        "",
    ]
    for item in narrative["stages"]:
        lines.append(f"- {item['line']}")
    lines.extend(["", "## Blockers", ""])
    if narrative["blocked_by"]:
        for blocker in narrative["blocked_by"]:
            lines.append(f"- `{blocker['code']}` `{blocker.get('surface')}`")
    else:
        lines.append("- none")
    lines.extend(["", "## Source Paths", ""])
    for name, path in sorted(narrative.get("source_paths", {}).items()):
        lines.append(f"- `{name}`: `{path}`")
    lines.append("")
    return "\n".join(lines)


def write_narrative(out_dir: Path, narrative: dict[str, Any]) -> None:
    write_json_atomic(out_dir / "workflow-narrative.json", narrative, root=out_dir)
    write_json_atomic(out_dir / "status.json", narrative, root=out_dir)
    write_text_atomic(out_dir / "workflow-narrative.md", render_markdown(narrative), root=out_dir)


def render_from_files(roadmap_path: Path, command_safety_path: Path, activation_path: Path, oracle_path: Path, out_dir: Path) -> dict[str, Any]:
    resolved = {
        "roadmap": resolve_input(roadmap_path),
        "command_safety": resolve_input(command_safety_path),
        "activation": resolve_input(activation_path),
        "oracle": resolve_input(oracle_path),
    }
    out_dir = resolve_out(out_dir)
    prepare_out_dir(out_dir, out_dir.name, source=ROOT)
    narrative = make_narrative(
        out_dir.name,
        read_json(resolved["roadmap"]),
        read_json(resolved["command_safety"]),
        read_json(resolved["activation"]),
        read_json(resolved["oracle"]),
        source_paths={name: rel(path) for name, path in resolved.items()},
    )
    write_narrative(out_dir, narrative)
    if narrative["decision"] != "control_deck_ready":
        raise WorkflowNarrativeError("ERR_WORKFLOW_NARRATIVE_BLOCKED", "workflow narrative is blocked", path=out_dir)
    return narrative


def run_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    fixtures = manifest.get("fixtures")
    if not isinstance(fixtures, list):
        raise WorkflowNarrativeError("ERR_WORKFLOW_NARRATIVE_MANIFEST_INVALID", "manifest fixtures must be a list", path=manifest_path)
    suite_id = str(manifest.get("suite_id", "v93-workflow-narrative"))
    out_dir = resolve_out(out_dir)
    prepare_out_dir(out_dir, out_dir.name, source=manifest_path)
    records = []
    for fixture in fixtures:
        if not isinstance(fixture, dict):
            raise WorkflowNarrativeError("ERR_WORKFLOW_NARRATIVE_MANIFEST_INVALID", "fixture must be an object", path=manifest_path)
        fixture_id = str(fixture.get("id", "fixture"))
        fixture_out = out_dir / fixture_id
        prepare_out_dir(fixture_out, fixture_id, source=manifest_path)
        artifacts = fixture.get("artifacts")
        if not isinstance(artifacts, dict):
            raise WorkflowNarrativeError("ERR_WORKFLOW_NARRATIVE_MANIFEST_INVALID", "fixture artifacts must be an object", path=manifest_path, fixture_id=fixture_id)
        narrative = make_narrative(
            fixture_id,
            artifacts.get("roadmap") if isinstance(artifacts.get("roadmap"), dict) else {},
            artifacts.get("command_safety") if isinstance(artifacts.get("command_safety"), dict) else {},
            artifacts.get("activation") if isinstance(artifacts.get("activation"), dict) else {},
            artifacts.get("oracle") if isinstance(artifacts.get("oracle"), dict) else {},
        )
        write_narrative(fixture_out, narrative)
        expected_decision = fixture.get("expected_decision")
        expected_codes = fixture.get("expected_blocked_codes")
        errors: list[str] = []
        if expected_decision is not None and expected_decision != narrative["decision"]:
            errors.append(f"expected {expected_decision}, got {narrative['decision']}")
        if expected_codes is not None:
            actual_codes = [str(blocker.get("code")) for blocker in narrative["blocked_by"]]
            if list(expected_codes) != actual_codes:
                errors.append(f"expected blockers {expected_codes}, got {actual_codes}")
        records.append({"id": fixture_id, "required": bool(fixture.get("required", True)), "status": "pass" if not errors else "fail", "decision": narrative["decision"], "error": "; ".join(errors) if errors else None})
    failed_required = [record for record in records if record["required"] and record["status"] != "pass"]
    summary = {
        "schema_version": NARRATIVE_VERSION,
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
        raise WorkflowNarrativeError("ERR_WORKFLOW_NARRATIVE_FIXTURE_FAILED", "required workflow narrative fixture failed", path=manifest_path)
    return summary


def ready_records() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    roadmap = {"decision": "roadmap_reconciled", "blocked_by": [], "policy": {"latest_version": "V117"}}
    command_safety = {"decision": "keep", "failed": 0, "required_fixture_count": 4, "required_passed": 4}
    activation = {
        "decision": "ready_for_next_workflow_design",
        "blocked_by": [],
        "inputs": {"roadmap_latest_version": "V117"},
        "next_safe_action": "design_next_workflow",
        "source_hashes": {
            "roadmap_reconciliation": canonical_hash(roadmap),
            "command_safety": canonical_hash(command_safety),
        },
    }
    oracle = {"decision": "evidence_verified", "blocked_by": [], "assertion_count": 12, "artifact_count": 4, "execution_policy": {"executes_commands": False}}
    return roadmap, command_safety, activation, oracle


def self_test() -> None:
    roadmap, command_safety, activation, oracle = ready_records()
    ready = make_narrative("self-test", roadmap, command_safety, activation, oracle)
    if ready["decision"] != "control_deck_ready":
        raise ValueError("ready records should render a ready control deck")
    stale = dict(roadmap)
    stale["policy"] = {"latest_version": "V93"}
    blocked = make_narrative("self-test-stale", stale, command_safety, activation, oracle)
    if blocked["decision"] != "blocked" or blocked["blocked_by"][0]["code"] != "ERR_WORKFLOW_NARRATIVE_ROADMAP_STALE":
        raise ValueError("stale roadmap should block")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--out", type=Path)
    subparsers = parser.add_subparsers(dest="command")
    render = subparsers.add_parser("render")
    render.add_argument("--roadmap", type=Path, default=DEFAULT_ROADMAP)
    render.add_argument("--command-safety", type=Path, default=DEFAULT_COMMAND_SAFETY)
    render.add_argument("--activation", type=Path, default=DEFAULT_ACTIVATION)
    render.add_argument("--oracle", type=Path, default=DEFAULT_ORACLE)
    render.add_argument("--out", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        if args.self_test:
            self_test()
            print("workflow narrative self-test: pass")
            return
        if args.manifest:
            if args.out is None:
                raise WorkflowNarrativeError("ERR_WORKFLOW_NARRATIVE_OUT_REQUIRED", "--out is required with --manifest")
            summary = run_manifest(args.manifest, args.out)
            print(json.dumps(summary, sort_keys=True))
            return
        if args.command == "render":
            narrative = render_from_files(args.roadmap, args.command_safety, args.activation, args.oracle, args.out)
            print(json.dumps({"decision": narrative["decision"], "blocked_by": narrative["blocked_by"], "narrative_id": narrative["narrative_id"]}, sort_keys=True))
            return
        raise WorkflowNarrativeError("ERR_WORKFLOW_NARRATIVE_COMMAND_REQUIRED", "use --self-test, --manifest, or render")
    except WorkflowNarrativeError as exc:
        print(json.dumps({"error": exc.to_record()}, sort_keys=True), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
