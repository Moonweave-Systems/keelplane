#!/usr/bin/env python3
"""V97 benchmark readiness report from metric ladder evidence."""

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


TOOL = "dwm_benchmark_readiness.py"
READINESS_VERSION = "97.0.0"
READINESS_ROOT = ROOT / "out" / "benchmark-readiness"
SENTINEL = ".dwm_benchmark_readiness-owned.json"
DEFAULT_LADDER = ROOT / "out" / "metric-ladders" / "v96-canonical" / "metric-ladder.json"


class BenchmarkReadinessError(ValueError):
    """Structured V97 benchmark readiness failure."""

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
        raise BenchmarkReadinessError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise BenchmarkReadinessError(code, "path contains a symlink", path=current)


def resolve_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_BENCHMARK_READINESS_PATH_UNSAFE", message="readiness output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = READINESS_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise BenchmarkReadinessError("ERR_BENCHMARK_READINESS_PATH_UNSAFE", f"readiness output must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise BenchmarkReadinessError("ERR_BENCHMARK_READINESS_PATH_UNSAFE", "readiness output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_BENCHMARK_READINESS_PATH_SYMLINK")
    return resolved


def resolve_input(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_BENCHMARK_READINESS_INPUT_UNSAFE", message="readiness input path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(ROOT.resolve(strict=False))
    except ValueError as exc:
        raise BenchmarkReadinessError("ERR_BENCHMARK_READINESS_INPUT_UNSAFE", "readiness input must resolve inside this repository", path=value) from exc
    check_components_not_symlink(candidate, code="ERR_BENCHMARK_READINESS_PATH_SYMLINK")
    if not resolved.is_file() or resolved.is_symlink():
        raise BenchmarkReadinessError("ERR_BENCHMARK_READINESS_INPUT_MISSING", "readiness input is missing or unsafe", path=value)
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


def prepare_out_dir(path: Path, report_id: str, *, source: Path | str) -> None:
    if path.exists():
        if path.is_symlink():
            raise BenchmarkReadinessError("ERR_BENCHMARK_READINESS_PATH_SYMLINK", "readiness output is a symlink", path=path)
        if not path.is_dir():
            raise BenchmarkReadinessError("ERR_BENCHMARK_READINESS_PATH_UNSAFE", "readiness output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("report_id") != report_id:
            raise BenchmarkReadinessError("ERR_BENCHMARK_READINESS_PATH_UNSAFE", "existing readiness output is not readiness-owned", path=path)
        shutil.rmtree(path)
    READINESS_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(path / SENTINEL, {"tool": TOOL, "readiness_version": READINESS_VERSION, "report_id": report_id, "source_path": str(source), "created_at": now_utc()}, root=path)


def level_map(ladder: dict[str, Any]) -> dict[str, dict[str, Any]]:
    levels = ladder.get("levels")
    if not isinstance(levels, list):
        raise BenchmarkReadinessError("ERR_BENCHMARK_READINESS_LADDER_INVALID", "metric ladder levels are missing")
    mapped = {str(level.get("id")): level for level in levels if isinstance(level, dict)}
    for required in ["process_progress", "operator_readiness", "public_benchmark"]:
        if required not in mapped:
            raise BenchmarkReadinessError("ERR_BENCHMARK_READINESS_LADDER_INVALID", f"metric ladder lacks {required}")
    return mapped


def make_report(report_id: str, ladder: dict[str, Any], *, source_paths: dict[str, str] | None = None) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    critical_blocked = False
    if ladder.get("tool") != "dwm_metric_ladder.py":
        blockers.append({"code": "ERR_BENCHMARK_READINESS_LADDER_TOOL_INVALID", "message": "input was not produced by metric ladder"})
        critical_blocked = True
    if ladder.get("decision") != "metric_ladder_ready":
        blockers.append({"code": "ERR_BENCHMARK_READINESS_LADDER_BLOCKED", "message": "metric ladder is not ready", "decision": ladder.get("decision")})
        critical_blocked = True
    policy = ladder.get("claim_policy") if isinstance(ladder.get("claim_policy"), dict) else {}
    if policy.get("public_benchmark_requires_promotion") is not True:
        blockers.append({"code": "ERR_BENCHMARK_READINESS_PROMOTION_POLICY_MISSING", "message": "metric ladder does not require benchmark promotion"})
        critical_blocked = True
    levels = level_map(ladder)
    process_ready = levels["process_progress"].get("ready") is True
    operator_ready = levels["operator_readiness"].get("ready") is True
    public_ready = levels["public_benchmark"].get("public_claim_allowed") is True
    if not process_ready:
        blockers.append({"code": "ERR_BENCHMARK_READINESS_PROCESS_NOT_READY", "message": "process graph is not ready"})
        critical_blocked = True
    if not operator_ready:
        blockers.append({"code": "ERR_BENCHMARK_READINESS_OPERATOR_NOT_READY", "message": "operator readiness history is not ready"})
        critical_blocked = True
    if not public_ready:
        blockers.append({"code": "ERR_BENCHMARK_READINESS_PUBLIC_PROMOTION_MISSING", "message": "public benchmark promotion evidence is missing"})
    readiness_score = (30 if process_ready else 0) + (40 if operator_ready else 0) + (30 if public_ready else 0)
    return {
        "schema_version": READINESS_VERSION,
        "tool": TOOL,
        "report_id": report_id,
        "decision": "blocked" if critical_blocked else "benchmark_readiness_recorded",
        "blocked_by": blockers,
        "readiness_score": readiness_score,
        "readiness_axes": {
            "process_progress": process_ready,
            "operator_readiness": operator_ready,
            "public_benchmark": public_ready,
        },
        "public_benchmark_publish_allowed": public_ready,
        "current_truth": "operator readiness is measurable; public benchmark remains gated" if operator_ready and not public_ready else "public benchmark promotion ready" if public_ready else "readiness blocked",
        "next_gate": "benchmark promotion receipt" if not public_ready else "human review before README benchmark publication",
        "claim_policy": {
            "readiness_score_is_public_benchmark": False,
            "requires_promotion_for_public_graph": True,
            "requires_human_review_for_readme_publication": True,
        },
        "source_paths": source_paths or {},
        "source_hashes": {"metric_ladder": canonical_hash(ladder)},
        "execution_policy": {"executes_commands": False, "creates_worktrees": False, "uses_network": False},
    }


def render_markdown(report: dict[str, Any]) -> str:
    axes = report["readiness_axes"]
    lines = [
        "# Benchmark Readiness",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Readiness score: `{report['readiness_score']}`",
        f"- Public benchmark publish allowed: `{report['public_benchmark_publish_allowed']}`",
        f"- Current truth: {report['current_truth']}",
        f"- Next gate: `{report['next_gate']}`",
        "",
        "| Axis | Ready |",
        "| --- | --- |",
        f"| `process_progress` | `{axes['process_progress']}` |",
        f"| `operator_readiness` | `{axes['operator_readiness']}` |",
        f"| `public_benchmark` | `{axes['public_benchmark']}` |",
        "",
        "This score is an internal readiness indicator, not a public benchmark graph.",
        "",
    ]
    return "\n".join(lines)


def write_report(out_dir: Path, report: dict[str, Any]) -> None:
    write_json_atomic(out_dir / "benchmark-readiness.json", report, root=out_dir)
    write_json_atomic(out_dir / "status.json", report, root=out_dir)
    write_text_atomic(out_dir / "benchmark-readiness.md", render_markdown(report), root=out_dir)


def report_from_file(ladder_path: Path, out_dir: Path) -> dict[str, Any]:
    resolved = resolve_input(ladder_path)
    out_dir = resolve_out(out_dir)
    prepare_out_dir(out_dir, out_dir.name, source=resolved)
    report = make_report(out_dir.name, read_json(resolved), source_paths={"metric_ladder": rel(resolved)})
    write_report(out_dir, report)
    if report["decision"] != "benchmark_readiness_recorded":
        raise BenchmarkReadinessError("ERR_BENCHMARK_READINESS_BLOCKED", "benchmark readiness is blocked", path=out_dir)
    return report


def run_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    fixtures = manifest.get("fixtures")
    if not isinstance(fixtures, list):
        raise BenchmarkReadinessError("ERR_BENCHMARK_READINESS_MANIFEST_INVALID", "manifest fixtures must be a list", path=manifest_path)
    suite_id = str(manifest.get("suite_id", "v97-benchmark-readiness"))
    out_dir = resolve_out(out_dir)
    prepare_out_dir(out_dir, out_dir.name, source=manifest_path)
    records = []
    for fixture in fixtures:
        fixture_id = str(fixture.get("id", "fixture"))
        fixture_out = out_dir / fixture_id
        prepare_out_dir(fixture_out, fixture_id, source=manifest_path)
        report = make_report(fixture_id, fixture.get("ladder") if isinstance(fixture.get("ladder"), dict) else {})
        write_report(fixture_out, report)
        errors: list[str] = []
        if fixture.get("expected_decision") is not None and fixture["expected_decision"] != report["decision"]:
            errors.append(f"expected {fixture['expected_decision']}, got {report['decision']}")
        if fixture.get("expected_public_allowed") is not None and fixture["expected_public_allowed"] != report["public_benchmark_publish_allowed"]:
            errors.append(f"expected public allowed {fixture['expected_public_allowed']}, got {report['public_benchmark_publish_allowed']}")
        records.append({"id": fixture_id, "required": bool(fixture.get("required", True)), "status": "pass" if not errors else "fail", "decision": report["decision"], "readiness_score": report["readiness_score"], "error": "; ".join(errors) if errors else None})
    failed_required = [record for record in records if record["required"] and record["status"] != "pass"]
    summary = {
        "schema_version": READINESS_VERSION,
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
        raise BenchmarkReadinessError("ERR_BENCHMARK_READINESS_FIXTURE_FAILED", "required benchmark readiness fixture failed", path=manifest_path)
    return summary


def sample_ladder(*, operator: bool = True, public: bool = False, decision: str = "metric_ladder_ready") -> dict[str, Any]:
    return {
        "tool": "dwm_metric_ladder.py",
        "decision": decision,
        "claim_policy": {"public_benchmark_requires_promotion": True},
        "levels": [
            {"id": "process_progress", "ready": True, "public_claim_allowed": False},
            {"id": "operator_readiness", "ready": operator, "public_claim_allowed": False},
            {"id": "public_benchmark", "ready": public, "public_claim_allowed": public},
        ],
    }


def self_test() -> None:
    report = make_report("self-test", sample_ladder())
    if report["decision"] != "benchmark_readiness_recorded" or report["public_benchmark_publish_allowed"] is not False:
        raise ValueError("operator-ready ladder should record readiness without public publish")
    public = make_report("self-test-public", sample_ladder(public=True))
    if public["readiness_score"] != 100 or public["public_benchmark_publish_allowed"] is not True:
        raise ValueError("public promotion fixture should reach 100")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--out", type=Path)
    subparsers = parser.add_subparsers(dest="command")
    assess = subparsers.add_parser("assess")
    assess.add_argument("--ladder", type=Path, default=DEFAULT_LADDER)
    assess.add_argument("--out", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        if args.self_test:
            self_test()
            print("benchmark readiness self-test: pass")
            return
        if args.manifest:
            if args.out is None:
                raise BenchmarkReadinessError("ERR_BENCHMARK_READINESS_OUT_REQUIRED", "--out is required with --manifest")
            summary = run_manifest(args.manifest, args.out)
            print(json.dumps(summary, sort_keys=True))
            return
        if args.command == "assess":
            report = report_from_file(args.ladder, args.out)
            print(json.dumps({"decision": report["decision"], "public_benchmark_publish_allowed": report["public_benchmark_publish_allowed"], "readiness_score": report["readiness_score"], "report_id": report["report_id"]}, sort_keys=True))
            return
        raise BenchmarkReadinessError("ERR_BENCHMARK_READINESS_COMMAND_REQUIRED", "use --self-test, --manifest, or assess")
    except BenchmarkReadinessError as exc:
        print(json.dumps({"error": exc.to_record()}, sort_keys=True), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
