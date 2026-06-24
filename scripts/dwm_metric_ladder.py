#!/usr/bin/env python3
"""V96 metric ladder gate for graph claim levels."""

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


TOOL = "dwm_metric_ladder.py"
LADDER_VERSION = "96.0.0"
LADDER_ROOT = ROOT / "out" / "metric-ladders"
SENTINEL = ".dwm_metric_ladder-owned.json"
DEFAULT_HISTORY = ROOT / "out" / "control-deck-score-history" / "v95-canonical" / "control-deck-score-history.json"
DEFAULT_GRAPH_TIMING = ROOT / "out" / "graph-timing" / "v78-canonical" / "graph-timing.json"


class MetricLadderError(ValueError):
    """Structured V96 metric ladder failure."""

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
        raise MetricLadderError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise MetricLadderError(code, "path contains a symlink", path=current)


def resolve_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_METRIC_LADDER_PATH_UNSAFE", message="ladder output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = LADDER_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise MetricLadderError("ERR_METRIC_LADDER_PATH_UNSAFE", f"ladder output must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise MetricLadderError("ERR_METRIC_LADDER_PATH_UNSAFE", "ladder output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_METRIC_LADDER_PATH_SYMLINK")
    return resolved


def resolve_input(value: str | Path, *, required: bool = True) -> Path | None:
    raw = Path(value)
    reject_traversal(raw, code="ERR_METRIC_LADDER_INPUT_UNSAFE", message="ladder input path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(ROOT.resolve(strict=False))
    except ValueError as exc:
        raise MetricLadderError("ERR_METRIC_LADDER_INPUT_UNSAFE", "ladder input must resolve inside this repository", path=value) from exc
    check_components_not_symlink(candidate, code="ERR_METRIC_LADDER_PATH_SYMLINK")
    if not resolved.is_file() or resolved.is_symlink():
        if required:
            raise MetricLadderError("ERR_METRIC_LADDER_INPUT_MISSING", "ladder input is missing or unsafe", path=value)
        return None
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


def prepare_out_dir(path: Path, ladder_id: str, *, source: Path | str) -> None:
    if path.exists():
        if path.is_symlink():
            raise MetricLadderError("ERR_METRIC_LADDER_PATH_SYMLINK", "ladder output is a symlink", path=path)
        if not path.is_dir():
            raise MetricLadderError("ERR_METRIC_LADDER_PATH_UNSAFE", "ladder output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("ladder_id") != ladder_id:
            raise MetricLadderError("ERR_METRIC_LADDER_PATH_UNSAFE", "existing ladder output is not ladder-owned", path=path)
        shutil.rmtree(path)
    LADDER_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(
        path / SENTINEL,
        {"tool": TOOL, "ladder_version": LADDER_VERSION, "ladder_id": ladder_id, "source_path": str(source), "created_at": now_utc()},
        root=path,
    )


def blocker(code: str, message: str, *, level: str) -> dict[str, Any]:
    return {"code": code, "message": message, "level": level}


def validate_history(history: dict[str, Any]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if history.get("decision") != "history_ready":
        blockers.append(blocker("ERR_METRIC_LADDER_HISTORY_NOT_READY", "score history is not ready", level="operator_readiness"))
    policy = history.get("claim_policy") if isinstance(history.get("claim_policy"), dict) else {}
    if policy.get("operator_readiness_only") is not True:
        blockers.append(blocker("ERR_METRIC_LADDER_HISTORY_POLICY_UNSAFE", "history is not explicitly operator-readiness-only", level="operator_readiness"))
    if policy.get("is_public_benchmark") is not False or policy.get("is_upward_trend_claim") is not False:
        blockers.append(blocker("ERR_METRIC_LADDER_HISTORY_OVERCLAIM", "history attempts a public benchmark or upward trend claim", level="operator_readiness"))
    if not isinstance(history.get("entries"), list) or history.get("entry_count") != len(history.get("entries", [])):
        blockers.append(blocker("ERR_METRIC_LADDER_HISTORY_INVALID", "history entries are invalid", level="operator_readiness"))
    return blockers


def graph_timing_level(graph_timing: dict[str, Any] | None) -> dict[str, Any]:
    if graph_timing is None:
        return {"id": "process_progress", "ready": False, "claim": "process graph unavailable", "public_claim_allowed": False, "blocked_by": [{"code": "ERR_METRIC_LADDER_GRAPH_TIMING_MISSING"}]}
    ready = graph_timing.get("decision") == "progress-only-visible"
    return {
        "id": "process_progress",
        "ready": ready,
        "claim": "process progress only",
        "public_claim_allowed": False,
        "blocked_by": [] if ready else [{"code": "ERR_METRIC_LADDER_GRAPH_TIMING_NOT_READY", "decision": graph_timing.get("decision")}],
    }


def promotion_level(promotion: dict[str, Any] | None) -> dict[str, Any]:
    if promotion is None:
        return {
            "id": "public_benchmark",
            "ready": False,
            "claim": "public benchmark graph blocked",
            "public_claim_allowed": False,
            "blocked_by": [{"code": "ERR_METRIC_LADDER_PUBLIC_PROMOTION_MISSING"}],
        }
    ready = promotion.get("status") == "promotion-ready"
    return {
        "id": "public_benchmark",
        "ready": ready,
        "claim": "public benchmark promotion reviewed" if ready else "public benchmark graph blocked",
        "public_claim_allowed": ready,
        "blocked_by": [] if ready else [{"code": "ERR_METRIC_LADDER_PUBLIC_PROMOTION_NOT_READY", "status": promotion.get("status")}],
    }


def make_ladder(ladder_id: str, history: dict[str, Any], *, graph_timing: dict[str, Any] | None = None, promotion: dict[str, Any] | None = None, source_paths: dict[str, str] | None = None) -> dict[str, Any]:
    history_blockers = validate_history(history)
    process = graph_timing_level(graph_timing)
    operator_ready = not history_blockers
    operator = {
        "id": "operator_readiness",
        "ready": operator_ready,
        "claim": "operator readiness history",
        "public_claim_allowed": False,
        "entry_count": history.get("entry_count"),
        "trend": history.get("trend"),
        "blocked_by": history_blockers,
    }
    public = promotion_level(promotion)
    levels = [process, operator, public]
    blockers = [item for level in levels for item in level.get("blocked_by", [])]
    decision = "metric_ladder_ready" if operator_ready else "blocked"
    return {
        "schema_version": LADDER_VERSION,
        "tool": TOOL,
        "ladder_id": ladder_id,
        "decision": decision,
        "blocked_by": blockers,
        "levels": levels,
        "current_public_level": "operator_readiness" if operator_ready else "process_progress",
        "next_public_benchmark_gate": "benchmark promotion receipt with release-backed history",
        "claim_policy": {
            "process_graph_is_benchmark": False,
            "operator_readiness_is_benchmark": False,
            "public_benchmark_requires_promotion": True,
            "do_not_publish_upward_claim_from_readiness_history": True,
        },
        "source_paths": source_paths or {},
        "source_hashes": {
            "history": canonical_hash(history),
            "graph_timing": canonical_hash(graph_timing) if graph_timing is not None else None,
            "promotion": canonical_hash(promotion) if promotion is not None else None,
        },
        "execution_policy": {"executes_commands": False, "creates_worktrees": False, "uses_network": False},
    }


def render_markdown(ladder: dict[str, Any]) -> str:
    lines = [
        "# Metric Ladder",
        "",
        f"- Decision: `{ladder['decision']}`",
        f"- Current public level: `{ladder['current_public_level']}`",
        f"- Next benchmark gate: `{ladder['next_public_benchmark_gate']}`",
        "",
        "| Level | Ready | Public claim allowed | Claim |",
        "| --- | --- | --- | --- |",
    ]
    for level in ladder["levels"]:
        lines.append(f"| `{level['id']}` | `{level['ready']}` | `{level['public_claim_allowed']}` | `{level['claim']}` |")
    lines.extend(["", "Operator readiness history is a real metric, but it is not public benchmark evidence.", ""])
    return "\n".join(lines)


def write_ladder(out_dir: Path, ladder: dict[str, Any]) -> None:
    write_json_atomic(out_dir / "metric-ladder.json", ladder, root=out_dir)
    write_json_atomic(out_dir / "status.json", ladder, root=out_dir)
    write_text_atomic(out_dir / "metric-ladder.md", render_markdown(ladder), root=out_dir)


def ladder_from_files(history_path: Path, out_dir: Path, *, graph_timing_path: Path | None, promotion_path: Path | None) -> dict[str, Any]:
    resolved_history = resolve_input(history_path)
    resolved_timing = resolve_input(graph_timing_path, required=False) if graph_timing_path else None
    resolved_promotion = resolve_input(promotion_path, required=False) if promotion_path else None
    out_dir = resolve_out(out_dir)
    prepare_out_dir(out_dir, out_dir.name, source=ROOT)
    history = read_json(resolved_history)
    graph_timing = read_json(resolved_timing) if resolved_timing else None
    promotion = read_json(resolved_promotion) if resolved_promotion else None
    ladder = make_ladder(
        out_dir.name,
        history,
        graph_timing=graph_timing,
        promotion=promotion,
        source_paths={
            "history": rel(resolved_history),
            **({"graph_timing": rel(resolved_timing)} if resolved_timing else {}),
            **({"promotion": rel(resolved_promotion)} if resolved_promotion else {}),
        },
    )
    write_ladder(out_dir, ladder)
    if ladder["decision"] != "metric_ladder_ready":
        raise MetricLadderError("ERR_METRIC_LADDER_BLOCKED", "metric ladder is blocked", path=out_dir)
    return ladder


def run_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    fixtures = manifest.get("fixtures")
    if not isinstance(fixtures, list):
        raise MetricLadderError("ERR_METRIC_LADDER_MANIFEST_INVALID", "manifest fixtures must be a list", path=manifest_path)
    suite_id = str(manifest.get("suite_id", "v96-metric-ladder"))
    out_dir = resolve_out(out_dir)
    prepare_out_dir(out_dir, out_dir.name, source=manifest_path)
    records = []
    for fixture in fixtures:
        fixture_id = str(fixture.get("id", "fixture"))
        fixture_out = out_dir / fixture_id
        prepare_out_dir(fixture_out, fixture_id, source=manifest_path)
        ladder = make_ladder(
            fixture_id,
            fixture.get("history") if isinstance(fixture.get("history"), dict) else {},
            graph_timing=fixture.get("graph_timing") if isinstance(fixture.get("graph_timing"), dict) else None,
            promotion=fixture.get("promotion") if isinstance(fixture.get("promotion"), dict) else None,
        )
        write_ladder(fixture_out, ladder)
        errors: list[str] = []
        if fixture.get("expected_decision") is not None and fixture["expected_decision"] != ladder["decision"]:
            errors.append(f"expected {fixture['expected_decision']}, got {ladder['decision']}")
        if fixture.get("expected_public_claim_allowed") is not None:
            actual = next(level for level in ladder["levels"] if level["id"] == "public_benchmark")["public_claim_allowed"]
            if fixture["expected_public_claim_allowed"] != actual:
                errors.append(f"expected public claim {fixture['expected_public_claim_allowed']}, got {actual}")
        records.append({"id": fixture_id, "required": bool(fixture.get("required", True)), "status": "pass" if not errors else "fail", "decision": ladder["decision"], "error": "; ".join(errors) if errors else None})
    failed_required = [record for record in records if record["required"] and record["status"] != "pass"]
    summary = {
        "schema_version": LADDER_VERSION,
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
        raise MetricLadderError("ERR_METRIC_LADDER_FIXTURE_FAILED", "required metric ladder fixture failed", path=manifest_path)
    return summary


def sample_history(*, public: bool = False, decision: str = "history_ready") -> dict[str, Any]:
    return {
        "decision": decision,
        "entry_count": 2,
        "entries": [{"label": "a", "readiness_percent": 83}, {"label": "b", "readiness_percent": 100}],
        "trend": {"kind": "readiness_increased", "delta": 17, "public_claim_allowed": False},
        "claim_policy": {"operator_readiness_only": True, "is_public_benchmark": public, "is_upward_trend_claim": False},
    }


def self_test() -> None:
    ready = make_ladder("self-test", sample_history(), graph_timing={"decision": "progress-only-visible"})
    if ready["decision"] != "metric_ladder_ready" or ready["current_public_level"] != "operator_readiness":
        raise ValueError("ready metric ladder should expose operator readiness")
    blocked = make_ladder("self-test-blocked", sample_history(public=True))
    if blocked["decision"] != "blocked":
        raise ValueError("public benchmark overclaim should block metric ladder")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--out", type=Path)
    subparsers = parser.add_subparsers(dest="command")
    assess = subparsers.add_parser("assess")
    assess.add_argument("--history", type=Path, default=DEFAULT_HISTORY)
    assess.add_argument("--graph-timing", type=Path, default=DEFAULT_GRAPH_TIMING)
    assess.add_argument("--promotion", type=Path)
    assess.add_argument("--out", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        if args.self_test:
            self_test()
            print("metric ladder self-test: pass")
            return
        if args.manifest:
            if args.out is None:
                raise MetricLadderError("ERR_METRIC_LADDER_OUT_REQUIRED", "--out is required with --manifest")
            summary = run_manifest(args.manifest, args.out)
            print(json.dumps(summary, sort_keys=True))
            return
        if args.command == "assess":
            ladder = ladder_from_files(args.history, args.out, graph_timing_path=args.graph_timing, promotion_path=args.promotion)
            print(json.dumps({"decision": ladder["decision"], "current_public_level": ladder["current_public_level"], "ladder_id": ladder["ladder_id"]}, sort_keys=True))
            return
        raise MetricLadderError("ERR_METRIC_LADDER_COMMAND_REQUIRED", "use --self-test, --manifest, or assess")
    except MetricLadderError as exc:
        print(json.dumps({"error": exc.to_record()}, sort_keys=True), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
