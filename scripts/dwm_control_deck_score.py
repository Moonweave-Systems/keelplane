#!/usr/bin/env python3
"""V94 Control Deck readiness score for Keelplane."""

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


TOOL = "dwm_control_deck_score.py"
SCORE_VERSION = "94.0.0"
SCORE_ROOT = ROOT / "out" / "control-deck-scores"
SENTINEL = ".dwm_control_deck_score-owned.json"
DEFAULT_NARRATIVE = ROOT / "out" / "workflow-narratives" / "v93-canonical" / "workflow-narrative.json"
DEFAULT_ROADMAP = ROOT / "out" / "roadmap-reconciliations" / "v88-canonical" / "roadmap-reconciliation.json"
DEFAULT_COMMAND_SAFETY = ROOT / "out" / "command-safety" / "v89-final" / "summary.json"
DEFAULT_ACTIVATION = ROOT / "out" / "workflow-activations" / "v90-canonical" / "workflow-activation.json"
DEFAULT_ORACLE = ROOT / "out" / "evidence-oracles" / "v92-canonical" / "evidence-oracle.json"


class ControlDeckScoreError(ValueError):
    """Structured V94 Control Deck score failure."""

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
        raise ControlDeckScoreError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise ControlDeckScoreError(code, "path contains a symlink", path=current)


def resolve_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_CONTROL_DECK_SCORE_PATH_UNSAFE", message="score output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = SCORE_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ControlDeckScoreError("ERR_CONTROL_DECK_SCORE_PATH_UNSAFE", f"score output must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise ControlDeckScoreError("ERR_CONTROL_DECK_SCORE_PATH_UNSAFE", "score output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_CONTROL_DECK_SCORE_PATH_SYMLINK")
    return resolved


def resolve_input(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_CONTROL_DECK_SCORE_INPUT_UNSAFE", message="score input path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(ROOT.resolve(strict=False))
    except ValueError as exc:
        raise ControlDeckScoreError("ERR_CONTROL_DECK_SCORE_INPUT_UNSAFE", "score input must resolve inside this repository", path=value) from exc
    check_components_not_symlink(candidate, code="ERR_CONTROL_DECK_SCORE_PATH_SYMLINK")
    if not resolved.is_file() or resolved.is_symlink():
        raise ControlDeckScoreError("ERR_CONTROL_DECK_SCORE_INPUT_MISSING", "score input is missing or unsafe", path=value)
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


def prepare_out_dir(path: Path, score_id: str, *, source: Path | str) -> None:
    if path.exists():
        if path.is_symlink():
            raise ControlDeckScoreError("ERR_CONTROL_DECK_SCORE_PATH_SYMLINK", "score output is a symlink", path=path)
        if not path.is_dir():
            raise ControlDeckScoreError("ERR_CONTROL_DECK_SCORE_PATH_UNSAFE", "score output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("score_id") != score_id:
            raise ControlDeckScoreError("ERR_CONTROL_DECK_SCORE_PATH_UNSAFE", "existing score output is not score-owned", path=path)
        shutil.rmtree(path)
    SCORE_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(
        path / SENTINEL,
        {
            "tool": TOOL,
            "score_version": SCORE_VERSION,
            "score_id": score_id,
            "source_path": str(source),
            "created_at": now_utc(),
        },
        root=path,
    )


def add_blocker(blockers: list[dict[str, Any]], code: str, message: str, *, axis: str, actual: Any = None, expected: Any = None) -> None:
    record: dict[str, Any] = {"code": code, "message": message, "axis": axis}
    if actual is not None:
        record["actual"] = actual
    if expected is not None:
        record["expected"] = expected
    blockers.append(record)


def axis(axis_id: str, label: str, score: int, max_score: int, evidence: dict[str, Any]) -> dict[str, Any]:
    return {"id": axis_id, "label": label, "score": score, "max_score": max_score, "evidence": evidence}


def stage_statuses(narrative: dict[str, Any]) -> dict[str, str]:
    stages = narrative.get("stages")
    if not isinstance(stages, list):
        return {}
    statuses: dict[str, str] = {}
    for item in stages:
        if isinstance(item, dict):
            statuses[str(item.get("id"))] = str(item.get("status"))
    return statuses


def make_score(
    score_id: str,
    narrative: dict[str, Any],
    roadmap: dict[str, Any],
    command_safety: dict[str, Any],
    activation: dict[str, Any],
    oracle: dict[str, Any],
    *,
    source_paths: dict[str, str] | None = None,
) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    statuses = stage_statuses(narrative)
    hashes = narrative.get("source_hashes") if isinstance(narrative.get("source_hashes"), dict) else {}
    voice = narrative.get("voice_policy") if isinstance(narrative.get("voice_policy"), dict) else {}

    if narrative.get("decision") != "control_deck_ready":
        add_blocker(blockers, "ERR_CONTROL_DECK_SCORE_NARRATIVE_NOT_READY", "workflow narrative is not ready", axis="narrative", actual=narrative.get("decision"), expected="control_deck_ready")
    if narrative.get("blocked_by"):
        add_blocker(blockers, "ERR_CONTROL_DECK_SCORE_NARRATIVE_BLOCKED", "workflow narrative contains blockers", axis="narrative")
    if voice.get("labels_are_status_rendering_only") is not True or voice.get("does_not_claim_autonomous_execution") is not True:
        add_blocker(blockers, "ERR_CONTROL_DECK_SCORE_VOICE_POLICY_UNSAFE", "voice policy does not preserve source-truth boundary", axis="voice_policy")
    if (narrative.get("execution_policy") or {}).get("executes_commands") is not False:
        add_blocker(blockers, "ERR_CONTROL_DECK_SCORE_EXECUTION_POLICY_UNSAFE", "narrative execution policy is not read-only", axis="execution_policy")

    expected_hashes = {
        "roadmap": canonical_hash(roadmap),
        "command_safety": canonical_hash(command_safety),
        "activation": canonical_hash(activation),
        "oracle": canonical_hash(oracle),
    }
    for name, expected_hash in expected_hashes.items():
        if hashes.get(name) != expected_hash:
            add_blocker(blockers, f"ERR_CONTROL_DECK_SCORE_{name.upper()}_HASH_DRIFT", f"{name} hash drifted from narrative", axis="source_integrity")

    axes = [
        axis("chart", "Chart", 2 if statuses.get("chart") == "clear" else 0, 2, {"stage_status": statuses.get("chart"), "roadmap_decision": roadmap.get("decision")}),
        axis("gate", "Gate", 2 if statuses.get("gate") == "clear" else 0, 2, {"stage_status": statuses.get("gate"), "command_safety_decision": command_safety.get("decision")}),
        axis("activation", "Activation", 2 if statuses.get("activation") == "clear" else 0, 2, {"stage_status": statuses.get("activation"), "activation_decision": activation.get("decision")}),
        axis("oracle", "Oracle", 2 if statuses.get("oracle") == "clear" else 0, 2, {"stage_status": statuses.get("oracle"), "oracle_decision": oracle.get("decision")}),
        axis("source_integrity", "Source Integrity", 2 if not [blocker for blocker in blockers if blocker.get("axis") == "source_integrity"] else 0, 2, {"checked_hashes": sorted(expected_hashes)}),
        axis("voice_policy", "Voice Policy", 2 if not [blocker for blocker in blockers if blocker.get("axis") == "voice_policy"] else 0, 2, {"labels_are_status_rendering_only": voice.get("labels_are_status_rendering_only")}),
    ]
    total = sum(item["score"] for item in axes)
    max_total = sum(item["max_score"] for item in axes)
    readiness_percent = int(round((total / max_total) * 100)) if max_total else 0
    decision = "score_ready" if total == max_total and not blockers else "blocked"
    return {
        "schema_version": SCORE_VERSION,
        "tool": TOOL,
        "score_id": score_id,
        "decision": decision,
        "blocked_by": blockers,
        "score": {
            "total": total,
            "max": max_total,
            "readiness_percent": readiness_percent,
            "axes": axes,
        },
        "claim_policy": {
            "is_public_benchmark": False,
            "is_upward_trend_claim": False,
            "may_feed_operator_status": True,
            "requires_more_history_for_public_graph": True,
        },
        "source_paths": source_paths or {},
        "source_hashes": {
            "narrative": canonical_hash(narrative),
            "roadmap": expected_hashes["roadmap"],
            "command_safety": expected_hashes["command_safety"],
            "activation": expected_hashes["activation"],
            "oracle": expected_hashes["oracle"],
        },
        "execution_policy": {
            "executes_commands": False,
            "creates_worktrees": False,
            "uses_network": False,
            "scores_existing_artifacts_only": True,
        },
    }


def render_markdown(score: dict[str, Any]) -> str:
    lines = [
        "# Control Deck Score",
        "",
        f"- Decision: `{score['decision']}`",
        f"- Readiness: `{score['score']['readiness_percent']}%`",
        f"- Score: `{score['score']['total']}/{score['score']['max']}`",
        f"- Public benchmark: `{score['claim_policy']['is_public_benchmark']}`",
        f"- Executes commands: `{score['execution_policy']['executes_commands']}`",
        "",
        "## Axes",
        "",
    ]
    for item in score["score"]["axes"]:
        lines.append(f"- `{item['id']}`: `{item['score']}/{item['max_score']}`")
    lines.extend(["", "## Blockers", ""])
    if score["blocked_by"]:
        for blocker in score["blocked_by"]:
            lines.append(f"- `{blocker['code']}` `{blocker.get('axis')}`")
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def write_score(out_dir: Path, score: dict[str, Any]) -> None:
    write_json_atomic(out_dir / "control-deck-score.json", score, root=out_dir)
    write_json_atomic(out_dir / "status.json", score, root=out_dir)
    write_text_atomic(out_dir / "control-deck-score.md", render_markdown(score), root=out_dir)


def score_from_files(narrative_path: Path, roadmap_path: Path, command_safety_path: Path, activation_path: Path, oracle_path: Path, out_dir: Path) -> dict[str, Any]:
    resolved = {
        "narrative": resolve_input(narrative_path),
        "roadmap": resolve_input(roadmap_path),
        "command_safety": resolve_input(command_safety_path),
        "activation": resolve_input(activation_path),
        "oracle": resolve_input(oracle_path),
    }
    out_dir = resolve_out(out_dir)
    prepare_out_dir(out_dir, out_dir.name, source=ROOT)
    score = make_score(
        out_dir.name,
        read_json(resolved["narrative"]),
        read_json(resolved["roadmap"]),
        read_json(resolved["command_safety"]),
        read_json(resolved["activation"]),
        read_json(resolved["oracle"]),
        source_paths={name: rel(path) for name, path in resolved.items()},
    )
    write_score(out_dir, score)
    if score["decision"] != "score_ready":
        raise ControlDeckScoreError("ERR_CONTROL_DECK_SCORE_BLOCKED", "control deck score is blocked", path=out_dir)
    return score


def run_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    fixtures = manifest.get("fixtures")
    if not isinstance(fixtures, list):
        raise ControlDeckScoreError("ERR_CONTROL_DECK_SCORE_MANIFEST_INVALID", "manifest fixtures must be a list", path=manifest_path)
    suite_id = str(manifest.get("suite_id", "v94-control-deck-score"))
    out_dir = resolve_out(out_dir)
    prepare_out_dir(out_dir, out_dir.name, source=manifest_path)
    records = []
    for fixture in fixtures:
        if not isinstance(fixture, dict):
            raise ControlDeckScoreError("ERR_CONTROL_DECK_SCORE_MANIFEST_INVALID", "fixture must be an object", path=manifest_path)
        fixture_id = str(fixture.get("id", "fixture"))
        fixture_out = out_dir / fixture_id
        prepare_out_dir(fixture_out, fixture_id, source=manifest_path)
        artifacts = fixture.get("artifacts")
        if not isinstance(artifacts, dict):
            raise ControlDeckScoreError("ERR_CONTROL_DECK_SCORE_MANIFEST_INVALID", "fixture artifacts must be an object", path=manifest_path, fixture_id=fixture_id)
        score = make_score(
            fixture_id,
            artifacts.get("narrative") if isinstance(artifacts.get("narrative"), dict) else {},
            artifacts.get("roadmap") if isinstance(artifacts.get("roadmap"), dict) else {},
            artifacts.get("command_safety") if isinstance(artifacts.get("command_safety"), dict) else {},
            artifacts.get("activation") if isinstance(artifacts.get("activation"), dict) else {},
            artifacts.get("oracle") if isinstance(artifacts.get("oracle"), dict) else {},
        )
        write_score(fixture_out, score)
        expected_decision = fixture.get("expected_decision")
        expected_percent = fixture.get("expected_readiness_percent")
        expected_codes = fixture.get("expected_blocked_codes")
        errors: list[str] = []
        if expected_decision is not None and expected_decision != score["decision"]:
            errors.append(f"expected {expected_decision}, got {score['decision']}")
        if expected_percent is not None and expected_percent != score["score"]["readiness_percent"]:
            errors.append(f"expected readiness {expected_percent}, got {score['score']['readiness_percent']}")
        if expected_codes is not None:
            actual_codes = [str(blocker.get("code")) for blocker in score["blocked_by"]]
            if list(expected_codes) != actual_codes:
                errors.append(f"expected blockers {expected_codes}, got {actual_codes}")
        records.append({"id": fixture_id, "required": bool(fixture.get("required", True)), "status": "pass" if not errors else "fail", "decision": score["decision"], "readiness_percent": score["score"]["readiness_percent"], "error": "; ".join(errors) if errors else None})
    failed_required = [record for record in records if record["required"] and record["status"] != "pass"]
    summary = {
        "schema_version": SCORE_VERSION,
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
        raise ControlDeckScoreError("ERR_CONTROL_DECK_SCORE_FIXTURE_FAILED", "required control deck score fixture failed", path=manifest_path)
    return summary


def ready_records() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    roadmap = {"decision": "roadmap_reconciled", "blocked_by": [], "policy": {"latest_version": "V101"}}
    command_safety = {"decision": "keep", "failed": 0, "required_fixture_count": 4, "required_passed": 4}
    activation = {
        "decision": "ready_for_next_workflow_design",
        "blocked_by": [],
        "inputs": {"roadmap_latest_version": "V101"},
        "next_safe_action": "design_next_workflow",
        "source_hashes": {"roadmap_reconciliation": canonical_hash(roadmap), "command_safety": canonical_hash(command_safety)},
    }
    oracle = {"decision": "evidence_verified", "blocked_by": [], "assertion_count": 12, "artifact_count": 4, "execution_policy": {"executes_commands": False}}
    narrative = {
        "decision": "control_deck_ready",
        "blocked_by": [],
        "stages": [{"id": "chart", "status": "clear"}, {"id": "gate", "status": "clear"}, {"id": "activation", "status": "clear"}, {"id": "oracle", "status": "clear"}],
        "voice_policy": {"labels_are_status_rendering_only": True, "does_not_claim_autonomous_execution": True},
        "execution_policy": {"executes_commands": False},
        "source_hashes": {"roadmap": canonical_hash(roadmap), "command_safety": canonical_hash(command_safety), "activation": canonical_hash(activation), "oracle": canonical_hash(oracle)},
    }
    return narrative, roadmap, command_safety, activation, oracle


def self_test() -> None:
    narrative, roadmap, command_safety, activation, oracle = ready_records()
    ready = make_score("self-test", narrative, roadmap, command_safety, activation, oracle)
    if ready["decision"] != "score_ready" or ready["score"]["readiness_percent"] != 100:
        raise ValueError("ready records should score 100")
    drifted = dict(narrative)
    drifted["source_hashes"] = {**narrative["source_hashes"], "oracle": "stale"}
    blocked = make_score("self-test-drift", drifted, roadmap, command_safety, activation, oracle)
    if blocked["decision"] != "blocked" or blocked["blocked_by"][0]["code"] != "ERR_CONTROL_DECK_SCORE_ORACLE_HASH_DRIFT":
        raise ValueError("hash drift should block score")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--out", type=Path)
    subparsers = parser.add_subparsers(dest="command")
    score = subparsers.add_parser("score")
    score.add_argument("--narrative", type=Path, default=DEFAULT_NARRATIVE)
    score.add_argument("--roadmap", type=Path, default=DEFAULT_ROADMAP)
    score.add_argument("--command-safety", type=Path, default=DEFAULT_COMMAND_SAFETY)
    score.add_argument("--activation", type=Path, default=DEFAULT_ACTIVATION)
    score.add_argument("--oracle", type=Path, default=DEFAULT_ORACLE)
    score.add_argument("--out", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        if args.self_test:
            self_test()
            print("control deck score self-test: pass")
            return
        if args.manifest:
            if args.out is None:
                raise ControlDeckScoreError("ERR_CONTROL_DECK_SCORE_OUT_REQUIRED", "--out is required with --manifest")
            summary = run_manifest(args.manifest, args.out)
            print(json.dumps(summary, sort_keys=True))
            return
        if args.command == "score":
            score = score_from_files(args.narrative, args.roadmap, args.command_safety, args.activation, args.oracle, args.out)
            print(json.dumps({"decision": score["decision"], "blocked_by": score["blocked_by"], "readiness_percent": score["score"]["readiness_percent"], "score_id": score["score_id"]}, sort_keys=True))
            return
        raise ControlDeckScoreError("ERR_CONTROL_DECK_SCORE_COMMAND_REQUIRED", "use --self-test, --manifest, or score")
    except ControlDeckScoreError as exc:
        print(json.dumps({"error": exc.to_record()}, sort_keys=True), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
