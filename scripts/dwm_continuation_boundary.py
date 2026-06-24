#!/usr/bin/env python3
"""V80 continuation boundary gate for multi-slice DWM work."""

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


TOOL = "dwm_continuation_boundary.py"
SCHEMA_VERSION = "1.0"
BOUNDARY_VERSION = "80.0.0"
BOUNDARY_ROOT = ROOT / "out" / "continuation-boundaries"
DEFAULT_PREFLIGHT = ROOT / "out" / "large-workflow-queue-preflight" / "v77-canonical" / "queue-preflight.json"
DEFAULT_TIMING = ROOT / "out" / "graph-timing" / "v78-canonical" / "graph-timing.json"
DEFAULT_VISIBILITY = ROOT / "out" / "readme-graph-visibility" / "v79-canonical" / "readme-graph-visibility.json"
SENTINEL = ".dwm_continuation_boundary-owned.json"

HARD_STOP_RISKS = ["write", "delete", "network", "deploy", "secret", "dependency", "database", "external-message", "history-rewrite"]


class ContinuationBoundaryError(ValueError):
    """Structured V80 continuation boundary failure."""

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
        raise ContinuationBoundaryError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise ContinuationBoundaryError(code, "path contains a symlink", path=current)


def resolve_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_CONTINUATION_BOUNDARY_PATH_UNSAFE", message="boundary output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = BOUNDARY_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ContinuationBoundaryError("ERR_CONTINUATION_BOUNDARY_PATH_UNSAFE", f"boundary output must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise ContinuationBoundaryError("ERR_CONTINUATION_BOUNDARY_PATH_UNSAFE", "boundary output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_CONTINUATION_BOUNDARY_PATH_SYMLINK")
    return resolved


def resolve_input(value: str | Path, *, code: str) -> Path:
    raw = Path(value)
    reject_traversal(raw, code=code, message="boundary input path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to((ROOT / "out").resolve(strict=False))
    except ValueError as exc:
        raise ContinuationBoundaryError(code, "boundary input must resolve under out", path=value) from exc
    check_components_not_symlink(candidate, code="ERR_CONTINUATION_BOUNDARY_PATH_SYMLINK")
    if not resolved.is_file() or resolved.is_symlink():
        raise ContinuationBoundaryError(code, "boundary input is missing or unsafe", path=value)
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


def prepare_out_dir(path: Path, boundary_id: str, *, source: Path | str) -> None:
    if path.exists():
        if path.is_symlink():
            raise ContinuationBoundaryError("ERR_CONTINUATION_BOUNDARY_PATH_SYMLINK", "boundary output is a symlink", path=path)
        if not path.is_dir():
            raise ContinuationBoundaryError("ERR_CONTINUATION_BOUNDARY_PATH_UNSAFE", "boundary output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("boundary_id") != boundary_id:
            raise ContinuationBoundaryError("ERR_CONTINUATION_BOUNDARY_PATH_UNSAFE", "existing boundary output is not boundary-owned", path=path)
        shutil.rmtree(path)
    BOUNDARY_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(
        path / SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "boundary_version": BOUNDARY_VERSION,
            "boundary_id": boundary_id,
            "source_path": str(source),
            "created_at": now_utc(),
        },
        root=path,
    )


def blocker(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def assess_boundary(boundary_id: str, *, preflight: dict[str, Any], timing: dict[str, Any], visibility: dict[str, Any], source_paths: dict[str, str | None] | None = None) -> dict[str, Any]:
    blockers: list[dict[str, str]] = []
    if preflight.get("status") != "queue-preflight-ready":
        blockers.append(blocker("ERR_CONTINUATION_BOUNDARY_PREFLIGHT_NOT_READY", "queue preflight is not ready"))
    risk_codes = preflight.get("risk_codes", [])
    if any(code in HARD_STOP_RISKS for code in risk_codes if isinstance(code, str)):
        blockers.append(blocker("ERR_CONTINUATION_BOUNDARY_HARD_RISK", "queue preflight contains hard-stop risk codes"))
    if timing.get("decision") != "progress-only-visible":
        blockers.append(blocker("ERR_CONTINUATION_BOUNDARY_GRAPH_TIMING_NOT_SAFE", "graph timing is not progress-only-visible"))
    if visibility.get("decision") != "readme_visibility_ready":
        blockers.append(blocker("ERR_CONTINUATION_BOUNDARY_README_VISIBILITY_NOT_READY", "README graph visibility is not ready"))

    can_continue = not blockers
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "boundary_version": BOUNDARY_VERSION,
        "boundary_id": boundary_id,
        "status": "continuation-boundary-ready" if can_continue else "continuation-boundary-blocked",
        "decision": "continue_source_control_plane" if can_continue else "blocked",
        "can_continue_without_human": can_continue,
        "continuous_until": "V83 source-only control-plane and receipt-schema work",
        "must_stop_before": [
            "queued command execution",
            "live adapter execution",
            "network, dependency, deploy, database, secret, delete, external-message, or history-rewrite actions",
            "public upward benchmark promotion",
        ],
        "safe_batchable_slices": [
            {"id": "V80", "name": "continuation boundary gate", "risk": "source-only"},
            {"id": "V81", "name": "multi-slice batch planner", "risk": "source-only"},
            {"id": "V82", "name": "execution receipt schema preflight", "risk": "source-only"},
            {"id": "V83", "name": "runner receipt dry-run gate", "risk": "fixture-only"},
        ],
        "first_human_gate": {
            "id": "V84",
            "reason": "actual queued command execution or live adapter execution requires an explicit gate",
        },
        "blocked_by": blockers,
        "source_paths": source_paths or {},
        "source_hashes": {
            "preflight": canonical_hash(preflight),
            "timing": canonical_hash(timing),
            "visibility": canonical_hash(visibility),
        },
    }


def render_markdown(boundary: dict[str, Any]) -> str:
    lines = [
        f"# Continuation Boundary {boundary['boundary_id']}",
        "",
        f"- Status: `{boundary['status']}`",
        f"- Decision: `{boundary['decision']}`",
        f"- Can continue without human: `{boundary['can_continue_without_human']}`",
        f"- Continuous until: {boundary['continuous_until']}",
        "",
        "## Safe Batchable Slices",
        "",
    ]
    for item in boundary["safe_batchable_slices"]:
        lines.append(f"- `{item['id']}`: {item['name']} (`{item['risk']}`)")
    lines.extend(["", "## Must Stop Before", ""])
    for item in boundary["must_stop_before"]:
        lines.append(f"- {item}")
    lines.extend(["", "## Blockers", ""])
    if boundary["blocked_by"]:
        for item in boundary["blocked_by"]:
            lines.append(f"- `{item['code']}`: {item['message']}")
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def write_boundary(out_dir: Path, boundary: dict[str, Any]) -> None:
    write_json_atomic(out_dir / "continuation-boundary.json", boundary, root=out_dir)
    write_json_atomic(out_dir / "status.json", boundary, root=out_dir)
    write_text_atomic(out_dir / "continuation-boundary.md", render_markdown(boundary), root=out_dir)


def run_assess(preflight_path: Path, timing_path: Path, visibility_path: Path, out_dir: Path) -> dict[str, Any]:
    preflight_path = resolve_input(preflight_path, code="ERR_CONTINUATION_BOUNDARY_PREFLIGHT_UNSAFE")
    timing_path = resolve_input(timing_path, code="ERR_CONTINUATION_BOUNDARY_TIMING_UNSAFE")
    visibility_path = resolve_input(visibility_path, code="ERR_CONTINUATION_BOUNDARY_VISIBILITY_UNSAFE")
    out_dir = resolve_out(out_dir)
    prepare_out_dir(out_dir, out_dir.name, source=preflight_path)
    preflight = read_json(preflight_path)
    timing = read_json(timing_path)
    visibility = read_json(visibility_path)
    boundary = assess_boundary(
        out_dir.name,
        preflight=preflight,
        timing=timing,
        visibility=visibility,
        source_paths={"preflight": rel(preflight_path), "timing": rel(timing_path), "visibility": rel(visibility_path)},
    )
    write_boundary(out_dir, boundary)
    return boundary


def run_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    fixtures = manifest.get("fixtures")
    if not isinstance(fixtures, list):
        raise ContinuationBoundaryError("ERR_CONTINUATION_BOUNDARY_MANIFEST_INVALID", "manifest fixtures must be a list", path=manifest_path)
    suite_id = str(manifest.get("suite_id", "v80-continuation-boundary"))
    out_dir = resolve_out(out_dir)
    prepare_out_dir(out_dir, out_dir.name, source=manifest_path)
    records = []
    for fixture in fixtures:
        if not isinstance(fixture, dict):
            raise ContinuationBoundaryError("ERR_CONTINUATION_BOUNDARY_MANIFEST_INVALID", "fixture must be an object", path=manifest_path)
        fixture_id = str(fixture.get("id", "fixture"))
        fixture_out = out_dir / fixture_id
        prepare_out_dir(fixture_out, fixture_id, source=manifest_path)
        boundary = assess_boundary(
            fixture_id,
            preflight=fixture.get("preflight") if isinstance(fixture.get("preflight"), dict) else {},
            timing=fixture.get("timing") if isinstance(fixture.get("timing"), dict) else {},
            visibility=fixture.get("visibility") if isinstance(fixture.get("visibility"), dict) else {},
        )
        write_boundary(fixture_out, boundary)
        expected_decision = fixture.get("expected_decision")
        status = "pass" if expected_decision in (None, boundary["decision"]) else "fail"
        records.append({"id": fixture_id, "required": bool(fixture.get("required", True)), "status": status, "decision": boundary["decision"], "error": None if status == "pass" else f"expected {expected_decision}, got {boundary['decision']}"})
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
        raise ContinuationBoundaryError("ERR_CONTINUATION_BOUNDARY_FIXTURE_FAILED", "required continuation boundary fixture failed", path=manifest_path)
    return summary


def ready_preflight() -> dict[str, Any]:
    return {"status": "queue-preflight-ready", "risk_codes": [], "packet_id": "large-workflow-queue-refresh"}


def ready_timing() -> dict[str, Any]:
    return {"status": "graph-timing-recorded", "decision": "progress-only-visible"}


def ready_visibility() -> dict[str, Any]:
    return {"status": "readme-graph-visibility-ready", "decision": "readme_visibility_ready"}


def self_test() -> None:
    ready = assess_boundary("self-test", preflight=ready_preflight(), timing=ready_timing(), visibility=ready_visibility())
    if ready["decision"] != "continue_source_control_plane":
        raise ContinuationBoundaryError("ERR_CONTINUATION_BOUNDARY_SELF_TEST_FAILED", "ready inputs should continue")
    risky = assess_boundary("self-test-risky", preflight={"status": "queue-preflight-ready", "risk_codes": ["network"]}, timing=ready_timing(), visibility=ready_visibility())
    if risky["decision"] != "blocked":
        raise ContinuationBoundaryError("ERR_CONTINUATION_BOUNDARY_SELF_TEST_FAILED", "hard risk should block")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--out", type=Path)
    subparsers = parser.add_subparsers(dest="command")
    assess_parser = subparsers.add_parser("assess")
    assess_parser.add_argument("--preflight", type=Path, default=DEFAULT_PREFLIGHT)
    assess_parser.add_argument("--timing", type=Path, default=DEFAULT_TIMING)
    assess_parser.add_argument("--visibility", type=Path, default=DEFAULT_VISIBILITY)
    assess_parser.add_argument("--out", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        if args.self_test:
            self_test()
            print("continuation boundary self-test: pass")
            return
        if args.manifest:
            if args.out is None:
                raise ContinuationBoundaryError("ERR_CONTINUATION_BOUNDARY_ARGS_INVALID", "--manifest requires --out")
            print(json.dumps(run_manifest(args.manifest, args.out), sort_keys=True))
            return
        if args.command == "assess":
            boundary = run_assess(args.preflight, args.timing, args.visibility, args.out)
            print(json.dumps({"status": boundary["status"], "decision": boundary["decision"], "boundary_id": boundary["boundary_id"]}, sort_keys=True))
            return
        raise ContinuationBoundaryError("ERR_CONTINUATION_BOUNDARY_ARGS_INVALID", "choose --self-test, --manifest, or assess")
    except ContinuationBoundaryError as exc:
        print(json.dumps({"status": "error", "error": exc.to_record()}, sort_keys=True), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
