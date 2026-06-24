#!/usr/bin/env python3
"""V78 graph timing gate for DWM visibility claims."""

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


TOOL = "dwm_graph_timing_gate.py"
SCHEMA_VERSION = "1.0"
GRAPH_TIMING_VERSION = "78.0.0"
GRAPH_TIMING_ROOT = ROOT / "out" / "graph-timing"
DEFAULT_PROGRESS = ROOT / "out" / "dogfood-progress" / "local-v66-current" / "dogfood-progress.json"
DEFAULT_PREFLIGHT = ROOT / "out" / "large-workflow-queue-preflight" / "v77-canonical" / "queue-preflight.json"
DEFAULT_READINESS = ROOT / "out" / "dogfood-pair-series" / "local-v64-selected-series" / "graph-readiness.json"
SENTINEL = ".dwm_graph_timing-owned.json"


class GraphTimingError(ValueError):
    """Structured V78 graph timing failure."""

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
        raise GraphTimingError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise GraphTimingError(code, "path contains a symlink", path=current)


def resolve_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_GRAPH_TIMING_PATH_UNSAFE", message="graph timing output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = GRAPH_TIMING_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise GraphTimingError("ERR_GRAPH_TIMING_PATH_UNSAFE", f"graph timing output must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise GraphTimingError("ERR_GRAPH_TIMING_PATH_UNSAFE", "graph timing output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_GRAPH_TIMING_PATH_SYMLINK")
    return resolved


def resolve_input(value: str | Path, *, code: str) -> Path:
    raw = Path(value)
    reject_traversal(raw, code=code, message="graph timing input path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    out_resolved = (ROOT / "out").resolve(strict=False)
    try:
        resolved.relative_to(out_resolved)
    except ValueError as exc:
        raise GraphTimingError(code, "graph timing input must resolve under out", path=value) from exc
    check_components_not_symlink(candidate, code="ERR_GRAPH_TIMING_PATH_SYMLINK")
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


def prepare_out_dir(path: Path, timing_id: str, *, source: Path | str) -> None:
    if path.exists():
        if path.is_symlink():
            raise GraphTimingError("ERR_GRAPH_TIMING_PATH_SYMLINK", "graph timing output is a symlink", path=path)
        if not path.is_dir():
            raise GraphTimingError("ERR_GRAPH_TIMING_PATH_UNSAFE", "graph timing output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("timing_id") != timing_id:
            raise GraphTimingError("ERR_GRAPH_TIMING_PATH_UNSAFE", "existing graph timing output is not graph-timing-owned", path=path)
        shutil.rmtree(path)
    GRAPH_TIMING_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(
        path / SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "graph_timing_version": GRAPH_TIMING_VERSION,
            "timing_id": timing_id,
            "source_path": str(source),
            "created_at": now_utc(),
        },
        root=path,
    )


def load_optional_json(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    if not path.is_file() or path.is_symlink():
        return None
    return read_json(path)


def process_progress_decision(progress: dict[str, Any] | None, progress_path: Path | None) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if progress is None:
        blockers.append({"code": "ERR_GRAPH_TIMING_PROGRESS_MISSING", "message": "process progress artifact is missing"})
        return {
            "decision": "blocked",
            "ready": False,
            "graph_type": "process_progress",
            "public_claim_allowed": False,
            "safe_label": "Process progress, not benchmark performance",
            "blocked_by": blockers,
        }
    if progress.get("status") != "dogfood-progress-recorded":
        blockers.append({"code": "ERR_GRAPH_TIMING_PROGRESS_NOT_RECORDED", "status": progress.get("status")})
    svg_path = progress.get("svg_path")
    if not isinstance(svg_path, str) or not (ROOT / svg_path).is_file() or (ROOT / svg_path).is_symlink():
        blockers.append({"code": "ERR_GRAPH_TIMING_PROGRESS_SVG_MISSING", "svg_path": svg_path})
    if progress.get("public_readme_ready") is True:
        blockers.append({"code": "ERR_GRAPH_TIMING_PROGRESS_OVERCLAIM", "message": "process progress must not claim public benchmark readiness"})
    completed = progress.get("completed_stage_count")
    total = progress.get("stage_count")
    ready = not blockers
    return {
        "decision": "process_progress_ready" if ready else "blocked",
        "ready": ready,
        "graph_type": "process_progress",
        "public_claim_allowed": False,
        "source_path": rel(progress_path) if progress_path is not None else None,
        "completed_stage_count": completed,
        "stage_count": total,
        "safe_label": "Process progress, not benchmark performance",
        "blocked_by": blockers,
    }


def local_benchmark_decision(readiness: dict[str, Any] | None, readiness_path: Path | None) -> dict[str, Any]:
    if readiness is None:
        return {
            "decision": "blocked",
            "ready": False,
            "graph_type": "local_benchmark_candidate",
            "public_claim_allowed": False,
            "blocked_by": [{"code": "ERR_GRAPH_TIMING_READINESS_MISSING", "message": "graph-readiness artifact is missing"}],
        }
    graph_ready = readiness.get("graph_ready") is True
    return {
        "decision": "local_candidate_ready_for_review" if graph_ready else "blocked",
        "ready": graph_ready,
        "graph_type": "local_benchmark_candidate",
        "public_claim_allowed": False,
        "source_path": rel(readiness_path) if readiness_path is not None else None,
        "pair_count": readiness.get("pair_count"),
        "min_pairs": readiness.get("min_pairs"),
        "blocked_by": [] if graph_ready else [{"code": code} for code in readiness.get("blocked_by", [])],
        "safe_label": "Local reviewed candidate only; no public upward trend claim",
    }


def public_benchmark_decision(progress: dict[str, Any] | None, readiness: dict[str, Any] | None, preflight: dict[str, Any] | None) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = [
        {"code": "ERR_GRAPH_TIMING_PUBLIC_PROMOTION_MISSING", "message": "public benchmark promotion receipt is not present"},
    ]
    if progress is None or progress.get("public_readme_ready") is not True:
        blockers.append({"code": "ERR_GRAPH_TIMING_PUBLIC_PROGRESS_NOT_READY", "message": "progress artifact does not approve public README readiness"})
    if readiness is None or readiness.get("graph_ready") is not True:
        blockers.append({"code": "ERR_GRAPH_TIMING_PUBLIC_SERIES_NOT_READY", "message": "pair-series readiness is not ready"})
    if preflight is None or preflight.get("status") != "queue-preflight-ready":
        blockers.append({"code": "ERR_GRAPH_TIMING_PUBLIC_PREFLIGHT_NOT_READY", "message": "latest queue preflight is not ready"})
    return {
        "decision": "blocked",
        "ready": False,
        "graph_type": "public_benchmark_trend",
        "public_claim_allowed": False,
        "safe_label": "Do not publish upward benchmark graph yet",
        "blocked_by": blockers,
    }


def make_timing(
    timing_id: str,
    *,
    progress: dict[str, Any] | None,
    progress_path: Path | None,
    readiness: dict[str, Any] | None,
    readiness_path: Path | None,
    preflight: dict[str, Any] | None,
    preflight_path: Path | None,
) -> dict[str, Any]:
    process = process_progress_decision(progress, progress_path)
    local = local_benchmark_decision(readiness, readiness_path)
    public = public_benchmark_decision(progress, readiness, preflight)
    decisions = [process, local, public]
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "graph_timing_version": GRAPH_TIMING_VERSION,
        "timing_id": timing_id,
        "status": "graph-timing-recorded",
        "decision": "progress-only-visible" if process["ready"] and not public["ready"] else "blocked",
        "summary": "Progress visibility is allowed; public upward benchmark graph remains blocked.",
        "decisions": decisions,
        "safe_next_step": "show process progress if useful; keep benchmark/upward graph behind promotion evidence",
        "source_hashes": {
            "progress": canonical_hash(progress) if progress is not None else None,
            "readiness": canonical_hash(readiness) if readiness is not None else None,
            "preflight": canonical_hash(preflight) if preflight is not None else None,
        },
        "source_paths": {
            "progress": rel(progress_path) if progress_path is not None else None,
            "readiness": rel(readiness_path) if readiness_path is not None else None,
            "preflight": rel(preflight_path) if preflight_path is not None else None,
        },
    }


def render_markdown(timing: dict[str, Any]) -> str:
    lines = [
        f"# Graph Timing {timing['timing_id']}",
        "",
        f"- Status: `{timing['status']}`",
        f"- Decision: `{timing['decision']}`",
        f"- Summary: {timing['summary']}",
        f"- Safe next step: {timing['safe_next_step']}",
        "",
        "| Graph Type | Decision | Ready | Public Claim | Blockers |",
        "| --- | --- | --- | --- | --- |",
    ]
    for decision in timing["decisions"]:
        blockers = ", ".join(blocker["code"] for blocker in decision.get("blocked_by", [])) or "none"
        lines.append(
            f"| `{decision['graph_type']}` | `{decision['decision']}` | `{decision['ready']}` | `{decision['public_claim_allowed']}` | {blockers} |"
        )
    lines.append("")
    return "\n".join(lines)


def write_timing(out_dir: Path, timing: dict[str, Any]) -> None:
    write_json_atomic(out_dir / "graph-timing.json", timing, root=out_dir)
    write_json_atomic(
        out_dir / "status.json",
        {
            "schema_version": SCHEMA_VERSION,
            "tool": TOOL,
            "timing_id": timing["timing_id"],
            "status": timing["status"],
            "decision": timing["decision"],
            "source_hashes": timing["source_hashes"],
        },
        root=out_dir,
    )
    write_text_atomic(out_dir / "graph-timing.md", render_markdown(timing), root=out_dir)


def run_check(progress_path: Path | None, readiness_path: Path | None, preflight_path: Path | None, out_dir: Path) -> dict[str, Any]:
    resolved_progress = resolve_input(progress_path, code="ERR_GRAPH_TIMING_PROGRESS_UNSAFE") if progress_path is not None else None
    resolved_readiness = resolve_input(readiness_path, code="ERR_GRAPH_TIMING_READINESS_UNSAFE") if readiness_path is not None else None
    resolved_preflight = resolve_input(preflight_path, code="ERR_GRAPH_TIMING_PREFLIGHT_UNSAFE") if preflight_path is not None else None
    progress = load_optional_json(resolved_progress)
    readiness = load_optional_json(resolved_readiness)
    preflight = load_optional_json(resolved_preflight)
    out_dir = resolve_out(out_dir)
    prepare_out_dir(out_dir, out_dir.name, source=resolved_progress or "graph-timing-inputs")
    timing = make_timing(
        out_dir.name,
        progress=progress,
        progress_path=resolved_progress,
        readiness=readiness,
        readiness_path=resolved_readiness,
        preflight=preflight,
        preflight_path=resolved_preflight,
    )
    write_timing(out_dir, timing)
    return timing


def run_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    fixtures = manifest.get("fixtures")
    if not isinstance(fixtures, list):
        raise GraphTimingError("ERR_GRAPH_TIMING_MANIFEST_INVALID", "manifest fixtures must be a list", path=manifest_path)
    suite_id = str(manifest.get("suite_id", "v78-graph-timing"))
    out_dir = resolve_out(out_dir)
    prepare_out_dir(out_dir, out_dir.name, source=manifest_path)
    records = []
    for fixture in fixtures:
        if not isinstance(fixture, dict):
            raise GraphTimingError("ERR_GRAPH_TIMING_MANIFEST_INVALID", "fixture must be an object", path=manifest_path)
        fixture_id = str(fixture.get("id", "fixture"))
        fixture_out = out_dir / fixture_id
        prepare_out_dir(fixture_out, fixture_id, source=manifest_path)
        progress = fixture.get("progress")
        if isinstance(progress, dict):
            progress = dict(progress)
            if fixture.get("materialize_progress_svg") is True:
                svg_path = fixture_out / "progress.svg"
                write_text_atomic(
                    svg_path,
                    "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"120\" height=\"40\"><title>fixture progress</title></svg>\n",
                    root=fixture_out,
                )
                progress["svg_path"] = rel(svg_path)
        readiness = fixture.get("readiness")
        preflight = fixture.get("preflight")
        timing = make_timing(
            fixture_id,
            progress=progress if isinstance(progress, dict) else None,
            progress_path=None,
            readiness=readiness if isinstance(readiness, dict) else None,
            readiness_path=None,
            preflight=preflight if isinstance(preflight, dict) else None,
            preflight_path=None,
        )
        write_timing(fixture_out, timing)
        expected_decision = fixture.get("expected_decision")
        status = "pass" if expected_decision in (None, timing["decision"]) else "fail"
        records.append(
            {
                "id": fixture_id,
                "required": bool(fixture.get("required", True)),
                "status": status,
                "decision": timing["decision"],
                "error": None if status == "pass" else f"expected {expected_decision}, got {timing['decision']}",
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
        raise GraphTimingError("ERR_GRAPH_TIMING_FIXTURE_FAILED", "required graph timing fixture failed", path=manifest_path)
    return summary


def ready_progress() -> dict[str, Any]:
    return {
        "status": "dogfood-progress-recorded",
        "decision": "process-progress-recorded",
        "completed_stage_count": 7,
        "stage_count": 7,
        "svg_path": "assets/dwm-dogfood-progress.svg",
        "public_readme_ready": False,
    }


def ready_readiness() -> dict[str, Any]:
    return {"graph_ready": True, "blocked_by": [], "min_pairs": 3, "pair_count": 3}


def ready_preflight() -> dict[str, Any]:
    return {"status": "queue-preflight-ready", "packet_id": "large-workflow-queue-refresh"}


def self_test() -> None:
    timing = make_timing(
        "self-test",
        progress=ready_progress(),
        progress_path=None,
        readiness=ready_readiness(),
        readiness_path=None,
        preflight=ready_preflight(),
        preflight_path=None,
    )
    if timing["decision"] != "progress-only-visible":
        raise GraphTimingError("ERR_GRAPH_TIMING_SELF_TEST_FAILED", "ready local inputs should allow progress-only visibility")
    public_decision = [item for item in timing["decisions"] if item["graph_type"] == "public_benchmark_trend"][0]
    if public_decision["ready"] is not False:
        raise GraphTimingError("ERR_GRAPH_TIMING_SELF_TEST_FAILED", "public benchmark graph should remain blocked")
    missing = make_timing("self-test-missing", progress=None, progress_path=None, readiness=None, readiness_path=None, preflight=None, preflight_path=None)
    if missing["decision"] != "blocked":
        raise GraphTimingError("ERR_GRAPH_TIMING_SELF_TEST_FAILED", "missing progress should block")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="run V78 graph timing self-test")
    parser.add_argument("--manifest", type=Path, help="run graph timing fixtures from a manifest")
    parser.add_argument("--out", type=Path, help="output directory under out/graph-timing")
    subparsers = parser.add_subparsers(dest="command")
    check_parser = subparsers.add_parser("check", help="check graph timing over current artifacts")
    check_parser.add_argument("--progress", type=Path, default=DEFAULT_PROGRESS)
    check_parser.add_argument("--readiness", type=Path, default=DEFAULT_READINESS)
    check_parser.add_argument("--preflight", type=Path, default=DEFAULT_PREFLIGHT)
    check_parser.add_argument("--out", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        if args.self_test:
            self_test()
            print("graph timing self-test: pass")
            return
        if args.manifest:
            if args.out is None:
                raise GraphTimingError("ERR_GRAPH_TIMING_ARGS_INVALID", "--manifest requires --out")
            summary = run_manifest(args.manifest, args.out)
            print(json.dumps(summary, sort_keys=True))
            return
        if args.command == "check":
            timing = run_check(args.progress, args.readiness, args.preflight, args.out)
            print(json.dumps({"status": timing["status"], "decision": timing["decision"], "timing_id": timing["timing_id"]}, sort_keys=True))
            return
        raise GraphTimingError("ERR_GRAPH_TIMING_ARGS_INVALID", "choose --self-test, --manifest, or check")
    except GraphTimingError as exc:
        print(json.dumps({"status": "error", "error": exc.to_record()}, sort_keys=True), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
