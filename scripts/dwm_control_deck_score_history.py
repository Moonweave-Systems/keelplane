#!/usr/bin/env python3
"""V95 Control Deck readiness history ledger."""

from __future__ import annotations

import argparse
import html
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


TOOL = "dwm_control_deck_score_history.py"
HISTORY_VERSION = "95.0.0"
HISTORY_ROOT = ROOT / "out" / "control-deck-score-history"
SENTINEL = ".dwm_control_deck_score_history-owned.json"


class ControlDeckScoreHistoryError(ValueError):
    """Structured V95 Control Deck score history failure."""

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
        raise ControlDeckScoreHistoryError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise ControlDeckScoreHistoryError(code, "path contains a symlink", path=current)


def resolve_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_CONTROL_DECK_SCORE_HISTORY_PATH_UNSAFE", message="history output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = HISTORY_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ControlDeckScoreHistoryError("ERR_CONTROL_DECK_SCORE_HISTORY_PATH_UNSAFE", f"history output must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise ControlDeckScoreHistoryError("ERR_CONTROL_DECK_SCORE_HISTORY_PATH_UNSAFE", "history output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_CONTROL_DECK_SCORE_HISTORY_PATH_SYMLINK")
    return resolved


def resolve_score_dir(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_CONTROL_DECK_SCORE_HISTORY_INPUT_UNSAFE", message="score path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(ROOT.resolve(strict=False))
    except ValueError as exc:
        raise ControlDeckScoreHistoryError("ERR_CONTROL_DECK_SCORE_HISTORY_INPUT_UNSAFE", "score path must resolve inside this repository", path=value) from exc
    check_components_not_symlink(candidate, code="ERR_CONTROL_DECK_SCORE_HISTORY_PATH_SYMLINK")
    if not resolved.is_dir() or resolved.is_symlink():
        raise ControlDeckScoreHistoryError("ERR_CONTROL_DECK_SCORE_HISTORY_INPUT_MISSING", "score input directory is missing or unsafe", path=value)
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


def prepare_out_dir(path: Path, history_id: str, *, source: Path | str) -> None:
    if path.exists():
        if path.is_symlink():
            raise ControlDeckScoreHistoryError("ERR_CONTROL_DECK_SCORE_HISTORY_PATH_SYMLINK", "history output is a symlink", path=path)
        if not path.is_dir():
            raise ControlDeckScoreHistoryError("ERR_CONTROL_DECK_SCORE_HISTORY_PATH_UNSAFE", "history output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("history_id") != history_id:
            raise ControlDeckScoreHistoryError("ERR_CONTROL_DECK_SCORE_HISTORY_PATH_UNSAFE", "existing history output is not history-owned", path=path)
        shutil.rmtree(path)
    HISTORY_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(
        path / SENTINEL,
        {
            "tool": TOOL,
            "history_version": HISTORY_VERSION,
            "history_id": history_id,
            "source_path": str(source),
            "created_at": now_utc(),
        },
        root=path,
    )


def load_score(directory: Path) -> dict[str, Any]:
    score_path = directory / "control-deck-score.json"
    status_path = directory / "status.json"
    if not score_path.is_file() or score_path.is_symlink() or not status_path.is_file() or status_path.is_symlink():
        raise ControlDeckScoreHistoryError("ERR_CONTROL_DECK_SCORE_HISTORY_ARTIFACT_MISSING", "score artifacts are missing", path=directory)
    score = read_json(score_path)
    status = read_json(status_path)
    if score != status:
        raise ControlDeckScoreHistoryError("ERR_CONTROL_DECK_SCORE_HISTORY_STALE_SCORE", "score artifact and status differ", path=directory)
    return score


def validate_score(score: dict[str, Any], *, path: Path | str, index: int) -> dict[str, Any]:
    if score.get("tool") != "dwm_control_deck_score.py":
        raise ControlDeckScoreHistoryError("ERR_CONTROL_DECK_SCORE_HISTORY_SCORE_INVALID", "score was not produced by the V94 score tool", path=path)
    score_body = score.get("score")
    claim_policy = score.get("claim_policy")
    if not isinstance(score_body, dict) or not isinstance(claim_policy, dict):
        raise ControlDeckScoreHistoryError("ERR_CONTROL_DECK_SCORE_HISTORY_SCORE_INVALID", "score body or claim policy is missing", path=path)
    if claim_policy.get("is_public_benchmark") is not False or claim_policy.get("is_upward_trend_claim") is not False:
        raise ControlDeckScoreHistoryError("ERR_CONTROL_DECK_SCORE_HISTORY_UNSAFE_CLAIM_POLICY", "score tries to act as a public benchmark or upward trend claim", path=path)
    readiness = score_body.get("readiness_percent")
    total = score_body.get("total")
    max_total = score_body.get("max")
    if not isinstance(readiness, int) or not 0 <= readiness <= 100 or not isinstance(total, int) or not isinstance(max_total, int) or max_total <= 0:
        raise ControlDeckScoreHistoryError("ERR_CONTROL_DECK_SCORE_HISTORY_SCORE_INVALID", "score numeric fields are invalid", path=path)
    decision = score.get("decision")
    if decision not in {"score_ready", "blocked"}:
        raise ControlDeckScoreHistoryError("ERR_CONTROL_DECK_SCORE_HISTORY_SCORE_INVALID", "score decision is unsupported", path=path)
    blocked_by = score.get("blocked_by") if isinstance(score.get("blocked_by"), list) else []
    return {
        "index": index,
        "label": str(score.get("score_id") or f"score-{index}"),
        "score_id": str(score.get("score_id") or ""),
        "decision": decision,
        "readiness_percent": readiness,
        "score_total": total,
        "score_max": max_total,
        "blocked_count": len(blocked_by),
        "source_path": str(path),
        "source_hash": canonical_hash(score),
    }


def trend(entries: list[dict[str, Any]]) -> dict[str, Any]:
    if len(entries) < 2:
        return {"kind": "single_point", "delta": 0, "public_claim_allowed": False}
    delta = entries[-1]["readiness_percent"] - entries[0]["readiness_percent"]
    if delta > 0:
        kind = "readiness_increased"
    elif delta < 0:
        kind = "readiness_decreased"
    else:
        kind = "readiness_flat"
    return {"kind": kind, "delta": delta, "public_claim_allowed": False}


def build_history(history_id: str, entries: list[dict[str, Any]], *, source_paths: list[str]) -> dict[str, Any]:
    if not entries:
        raise ControlDeckScoreHistoryError("ERR_CONTROL_DECK_SCORE_HISTORY_EMPTY", "at least one score is required")
    labels = [entry["label"] for entry in entries]
    if len(set(labels)) != len(labels):
        raise ControlDeckScoreHistoryError("ERR_CONTROL_DECK_SCORE_HISTORY_DUPLICATE_LABEL", "score labels must be unique")
    history = {
        "schema_version": HISTORY_VERSION,
        "tool": TOOL,
        "history_id": history_id,
        "decision": "history_ready",
        "entry_count": len(entries),
        "entries": entries,
        "trend": trend(entries),
        "claim_policy": {
            "operator_readiness_only": True,
            "is_public_benchmark": False,
            "is_upward_trend_claim": False,
            "may_render_internal_graph": True,
            "may_publish_as_benchmark_graph": False,
        },
        "safe_next_step": "use as internal readiness history; keep public benchmark graph promotion gated",
        "source_paths": source_paths,
        "source_hashes": {"entries": canonical_hash(entries)},
        "execution_policy": {
            "executes_commands": False,
            "creates_worktrees": False,
            "uses_network": False,
            "scores_existing_artifacts_only": True,
        },
    }
    return history


def render_markdown(history: dict[str, Any]) -> str:
    lines = [
        "# Control Deck Score History",
        "",
        f"- Decision: `{history['decision']}`",
        f"- Entries: `{history['entry_count']}`",
        f"- Trend: `{history['trend']['kind']}`",
        f"- Delta: `{history['trend']['delta']}`",
        f"- Public benchmark: `{history['claim_policy']['is_public_benchmark']}`",
        f"- Upward trend claim: `{history['claim_policy']['is_upward_trend_claim']}`",
        "",
        "| Entry | Decision | Readiness | Blockers |",
        "| --- | --- | --- | --- |",
    ]
    for entry in history["entries"]:
        lines.append(f"| `{entry['label']}` | `{entry['decision']}` | `{entry['readiness_percent']}%` | `{entry['blocked_count']}` |")
    lines.extend(["", "This is operator readiness history, not a public benchmark graph.", ""])
    return "\n".join(lines)


def render_svg(history: dict[str, Any]) -> str:
    entries = history["entries"]
    width = 900
    height = 260
    left = 70
    right = 40
    top = 48
    bottom = 64
    chart_w = width - left - right
    chart_h = height - top - bottom
    points = []
    for index, entry in enumerate(entries):
        x = left + (chart_w * index / max(1, len(entries) - 1))
        y = top + chart_h - (chart_h * entry["readiness_percent"] / 100)
        points.append((x, y, entry))
    polyline = " ".join(f"{x:.1f},{y:.1f}" for x, y, _entry in points)
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="Control Deck readiness history">',
        '<rect width="100%" height="100%" fill="#f8fafc"/>',
        '<text x="28" y="30" font-family="Arial, sans-serif" font-size="18" font-weight="700" fill="#0f172a">Control Deck readiness history</text>',
        '<text x="28" y="50" font-family="Arial, sans-serif" font-size="12" fill="#475569">Operator readiness only; not a public benchmark graph</text>',
        f'<line x1="{left}" y1="{top + chart_h}" x2="{width - right}" y2="{top + chart_h}" stroke="#94a3b8"/>',
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + chart_h}" stroke="#94a3b8"/>',
        f'<polyline points="{polyline}" fill="none" stroke="#2563eb" stroke-width="3"/>',
    ]
    for x, y, entry in points:
        lines.extend(
            [
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="#2563eb"/>',
                f'<text x="{x:.1f}" y="{top + chart_h + 22}" text-anchor="middle" font-family="Arial, sans-serif" font-size="11" fill="#0f172a">{html.escape(entry["label"])}</text>',
                f'<text x="{x:.1f}" y="{y - 10:.1f}" text-anchor="middle" font-family="Arial, sans-serif" font-size="11" fill="#1e3a8a">{entry["readiness_percent"]}%</text>',
            ]
        )
    lines.extend(
        [
            '<text x="28" y="238" font-family="Arial, sans-serif" font-size="11" fill="#64748b">Readiness movement is process state, not model superiority or benchmark performance.</text>',
            "</svg>",
        ]
    )
    return "\n".join(lines)


def write_history(out_dir: Path, history: dict[str, Any]) -> None:
    write_json_atomic(out_dir / "control-deck-score-history.json", history, root=out_dir)
    write_json_atomic(out_dir / "status.json", history, root=out_dir)
    write_text_atomic(out_dir / "control-deck-score-history.md", render_markdown(history), root=out_dir)
    write_text_atomic(out_dir / "control-deck-score-history.svg", render_svg(history), root=out_dir)


def history_from_score_dirs(score_dirs: list[Path], out_dir: Path) -> dict[str, Any]:
    if not score_dirs:
        raise ControlDeckScoreHistoryError("ERR_CONTROL_DECK_SCORE_HISTORY_EMPTY", "at least one --score is required")
    resolved = [resolve_score_dir(path) for path in score_dirs]
    out_dir = resolve_out(out_dir)
    prepare_out_dir(out_dir, out_dir.name, source=ROOT)
    entries = [validate_score(load_score(path), path=rel(path), index=index) for index, path in enumerate(resolved, 1)]
    history = build_history(out_dir.name, entries, source_paths=[rel(path) for path in resolved])
    write_history(out_dir, history)
    return history


def run_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    fixtures = manifest.get("fixtures")
    if not isinstance(fixtures, list):
        raise ControlDeckScoreHistoryError("ERR_CONTROL_DECK_SCORE_HISTORY_MANIFEST_INVALID", "manifest fixtures must be a list", path=manifest_path)
    suite_id = str(manifest.get("suite_id", "v95-control-deck-score-history"))
    out_dir = resolve_out(out_dir)
    prepare_out_dir(out_dir, out_dir.name, source=manifest_path)
    records = []
    for fixture in fixtures:
        fixture_id = str(fixture.get("id", "fixture"))
        fixture_out = out_dir / fixture_id
        prepare_out_dir(fixture_out, fixture_id, source=manifest_path)
        errors: list[str] = []
        history: dict[str, Any] | None = None
        try:
            raw_scores = fixture.get("scores")
            if not isinstance(raw_scores, list):
                raise ControlDeckScoreHistoryError("ERR_CONTROL_DECK_SCORE_HISTORY_MANIFEST_INVALID", "fixture scores must be a list", fixture_id=fixture_id)
            entries = [validate_score(score if isinstance(score, dict) else {}, path=f"fixture:{fixture_id}:{index}", index=index) for index, score in enumerate(raw_scores, 1)]
            history = build_history(fixture_id, entries, source_paths=[f"fixture:{fixture_id}"])
            write_history(fixture_out, history)
        except ControlDeckScoreHistoryError as exc:
            expected_error = fixture.get("expected_error")
            if expected_error != exc.code:
                errors.append(f"expected error {expected_error}, got {exc.code}")
            records.append({"id": fixture_id, "required": bool(fixture.get("required", True)), "status": "pass" if not errors else "fail", "observed_error": exc.code, "error": "; ".join(errors) if errors else None})
            continue
        expected_decision = fixture.get("expected_decision")
        expected_entries = fixture.get("expected_entry_count")
        if expected_decision is not None and history and expected_decision != history["decision"]:
            errors.append(f"expected {expected_decision}, got {history['decision']}")
        if expected_entries is not None and history and expected_entries != history["entry_count"]:
            errors.append(f"expected {expected_entries} entries, got {history['entry_count']}")
        if fixture.get("expected_error") is not None:
            errors.append(f"expected error {fixture.get('expected_error')}, got none")
        records.append({"id": fixture_id, "required": bool(fixture.get("required", True)), "status": "pass" if not errors else "fail", "decision": history["decision"] if history else None, "entry_count": history["entry_count"] if history else 0, "error": "; ".join(errors) if errors else None})
    failed_required = [record for record in records if record["required"] and record["status"] != "pass"]
    summary = {
        "schema_version": HISTORY_VERSION,
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
        raise ControlDeckScoreHistoryError("ERR_CONTROL_DECK_SCORE_HISTORY_FIXTURE_FAILED", "required score history fixture failed", path=manifest_path)
    return summary


def sample_score(score_id: str, readiness: int, *, decision: str = "score_ready", public: bool = False, upward: bool = False) -> dict[str, Any]:
    return {
        "schema_version": "94.0.0",
        "tool": "dwm_control_deck_score.py",
        "score_id": score_id,
        "decision": decision,
        "blocked_by": [] if decision == "score_ready" else [{"code": "ERR_SAMPLE_BLOCKED"}],
        "score": {"total": round(readiness * 12 / 100), "max": 12, "readiness_percent": readiness, "axes": []},
        "claim_policy": {"is_public_benchmark": public, "is_upward_trend_claim": upward, "may_feed_operator_status": True, "requires_more_history_for_public_graph": True},
    }


def self_test() -> None:
    ready = build_history(
        "self-test",
        [
            validate_score(sample_score("a", 83, decision="blocked"), path="fixture:a", index=1),
            validate_score(sample_score("b", 100), path="fixture:b", index=2),
        ],
        source_paths=["fixture:a", "fixture:b"],
    )
    if ready["decision"] != "history_ready" or ready["entry_count"] != 2 or ready["trend"]["delta"] != 17:
        raise ValueError("ready score history should record two entries")
    try:
        validate_score(sample_score("unsafe", 100, public=True), path="fixture:unsafe", index=1)
    except ControlDeckScoreHistoryError as exc:
        if exc.code != "ERR_CONTROL_DECK_SCORE_HISTORY_UNSAFE_CLAIM_POLICY":
            raise
    else:
        raise ValueError("unsafe public benchmark claim should block")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--out", type=Path)
    subparsers = parser.add_subparsers(dest="command")
    build = subparsers.add_parser("build")
    build.add_argument("--score", action="append", type=Path, default=[])
    build.add_argument("--out", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        if args.self_test:
            self_test()
            print("control deck score history self-test: pass")
            return
        if args.manifest:
            if args.out is None:
                raise ControlDeckScoreHistoryError("ERR_CONTROL_DECK_SCORE_HISTORY_OUT_REQUIRED", "--out is required with --manifest")
            summary = run_manifest(args.manifest, args.out)
            print(json.dumps(summary, sort_keys=True))
            return
        if args.command == "build":
            history = history_from_score_dirs(args.score, args.out)
            print(json.dumps({"decision": history["decision"], "entry_count": history["entry_count"], "history_id": history["history_id"], "trend": history["trend"]}, sort_keys=True))
            return
        raise ControlDeckScoreHistoryError("ERR_CONTROL_DECK_SCORE_HISTORY_COMMAND_REQUIRED", "use --self-test, --manifest, or build")
    except ControlDeckScoreHistoryError as exc:
        print(json.dumps({"error": exc.to_record()}, sort_keys=True), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
