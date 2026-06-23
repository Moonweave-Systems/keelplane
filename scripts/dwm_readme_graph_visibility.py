#!/usr/bin/env python3
"""V79 README graph visibility audit for DWM."""

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


TOOL = "dwm_readme_graph_visibility.py"
SCHEMA_VERSION = "1.0"
VISIBILITY_VERSION = "79.0.0"
VISIBILITY_ROOT = ROOT / "out" / "readme-graph-visibility"
DEFAULT_TIMING = ROOT / "out" / "graph-timing" / "v78-canonical" / "graph-timing.json"
DEFAULT_README = ROOT / "README.md"
SENTINEL = ".dwm_readme_graph_visibility-owned.json"

PROCESS_IMAGE = "assets/dwm-dogfood-progress.svg"
BENCHMARK_IMAGE = "assets/dwm-live-benchmark.svg"
PROCESS_REQUIRED_TERMS = [
    "It is not a public benchmark graph",
    "does not claim upward performance",
]
BENCHMARK_REQUIRED_TERMS = [
    "Benchmark visuals are source-bound",
    "Trend promotion is blocked until release history supports the claim",
    "public trend promotion requires real release history",
]
FORBIDDEN_CLAIMS = [
    "beats claude",
    "beats codex",
    "model superiority",
    "direct-agent superiority is proven",
    "public upward benchmark is ready",
    "public benchmark trend is ready",
]


class ReadmeGraphVisibilityError(ValueError):
    """Structured V79 README graph visibility failure."""

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
        raise ReadmeGraphVisibilityError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise ReadmeGraphVisibilityError(code, "path contains a symlink", path=current)


def resolve_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_README_GRAPH_VISIBILITY_PATH_UNSAFE", message="visibility output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = VISIBILITY_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ReadmeGraphVisibilityError("ERR_README_GRAPH_VISIBILITY_PATH_UNSAFE", f"visibility output must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise ReadmeGraphVisibilityError("ERR_README_GRAPH_VISIBILITY_PATH_UNSAFE", "visibility output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_README_GRAPH_VISIBILITY_PATH_SYMLINK")
    return resolved


def resolve_readme(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_README_GRAPH_VISIBILITY_README_UNSAFE", message="README path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(ROOT.resolve(strict=False))
    except ValueError as exc:
        raise ReadmeGraphVisibilityError("ERR_README_GRAPH_VISIBILITY_README_UNSAFE", "README path must resolve under repo root", path=value) from exc
    check_components_not_symlink(candidate, code="ERR_README_GRAPH_VISIBILITY_PATH_SYMLINK")
    if not resolved.is_file() or resolved.is_symlink():
        raise ReadmeGraphVisibilityError("ERR_README_GRAPH_VISIBILITY_README_MISSING", "README is missing or unsafe", path=value)
    return resolved


def resolve_timing(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_README_GRAPH_VISIBILITY_TIMING_UNSAFE", message="timing path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to((ROOT / "out" / "graph-timing").resolve(strict=False))
    except ValueError as exc:
        raise ReadmeGraphVisibilityError("ERR_README_GRAPH_VISIBILITY_TIMING_UNSAFE", "timing path must resolve under out/graph-timing", path=value) from exc
    check_components_not_symlink(candidate, code="ERR_README_GRAPH_VISIBILITY_PATH_SYMLINK")
    if not resolved.is_file() or resolved.is_symlink():
        raise ReadmeGraphVisibilityError("ERR_README_GRAPH_VISIBILITY_TIMING_MISSING", "graph timing artifact is missing or unsafe", path=value)
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


def prepare_out_dir(path: Path, visibility_id: str, *, source: Path | str) -> None:
    if path.exists():
        if path.is_symlink():
            raise ReadmeGraphVisibilityError("ERR_README_GRAPH_VISIBILITY_PATH_SYMLINK", "visibility output is a symlink", path=path)
        if not path.is_dir():
            raise ReadmeGraphVisibilityError("ERR_README_GRAPH_VISIBILITY_PATH_UNSAFE", "visibility output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("visibility_id") != visibility_id:
            raise ReadmeGraphVisibilityError("ERR_README_GRAPH_VISIBILITY_PATH_UNSAFE", "existing visibility output is not visibility-owned", path=path)
        shutil.rmtree(path)
    VISIBILITY_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(
        path / SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "visibility_version": VISIBILITY_VERSION,
            "visibility_id": visibility_id,
            "source_path": str(source),
            "created_at": now_utc(),
        },
        root=path,
    )


def decision_for(timing: dict[str, Any], graph_type: str) -> dict[str, Any] | None:
    decisions = timing.get("decisions")
    if not isinstance(decisions, list):
        return None
    for decision in decisions:
        if isinstance(decision, dict) and decision.get("graph_type") == graph_type:
            return decision
    return None


def blocked(code: str, message: str) -> dict[str, Any]:
    return {"code": code, "message": message}


def normalized(text: str) -> str:
    return " ".join(text.split())


def contains_term(text: str, term: str) -> bool:
    return normalized(term) in normalized(text)


def audit_readme_text(readme_text: str, timing: dict[str, Any], *, readme_path: Path | None = None, timing_path: Path | None = None, visibility_id: str) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    lower = readme_text.lower()

    if timing.get("status") != "graph-timing-recorded":
        blockers.append(blocked("ERR_README_GRAPH_VISIBILITY_TIMING_NOT_RECORDED", "graph timing status is not graph-timing-recorded"))
    if timing.get("decision") != "progress-only-visible":
        blockers.append(blocked("ERR_README_GRAPH_VISIBILITY_TIMING_DECISION_UNSAFE", "graph timing decision must be progress-only-visible"))

    process = decision_for(timing, "process_progress")
    public = decision_for(timing, "public_benchmark_trend")
    if not process or process.get("ready") is not True or process.get("public_claim_allowed") is not False:
        blockers.append(blocked("ERR_README_GRAPH_VISIBILITY_PROCESS_NOT_READY", "process progress is not approved for safe local visibility"))
    if not public or public.get("ready") is not False or public.get("public_claim_allowed") is not False:
        blockers.append(blocked("ERR_README_GRAPH_VISIBILITY_PUBLIC_TREND_NOT_BLOCKED", "public benchmark trend is not explicitly blocked"))

    if PROCESS_IMAGE not in readme_text:
        blockers.append(blocked("ERR_README_GRAPH_VISIBILITY_PROCESS_IMAGE_MISSING", "README does not embed the process progress graph"))
    for term in PROCESS_REQUIRED_TERMS:
        if not contains_term(readme_text, term):
            blockers.append(blocked("ERR_README_GRAPH_VISIBILITY_PROCESS_LABEL_MISSING", f"README missing process label: {term}"))

    if BENCHMARK_IMAGE in readme_text:
        for term in BENCHMARK_REQUIRED_TERMS:
            if not contains_term(readme_text, term):
                blockers.append(blocked("ERR_README_GRAPH_VISIBILITY_BENCHMARK_LABEL_MISSING", f"README missing benchmark label: {term}"))

    forbidden = [term for term in FORBIDDEN_CLAIMS if term in lower]
    if forbidden:
        blockers.append({"code": "ERR_README_GRAPH_VISIBILITY_OVERCLAIM", "message": "README contains forbidden graph claim text", "terms": forbidden})

    ready = not blockers
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "visibility_version": VISIBILITY_VERSION,
        "visibility_id": visibility_id,
        "status": "readme-graph-visibility-ready" if ready else "readme-graph-visibility-blocked",
        "decision": "readme_visibility_ready" if ready else "blocked",
        "readme_path": rel(readme_path) if readme_path is not None else None,
        "timing_path": rel(timing_path) if timing_path is not None else None,
        "process_graph_visible": PROCESS_IMAGE in readme_text,
        "benchmark_graph_visible": BENCHMARK_IMAGE in readme_text,
        "public_benchmark_claim_allowed": False,
        "safe_label": "process progress visible; public upward benchmark graph blocked",
        "blocked_by": blockers,
        "source_hashes": {
            "readme": canonical_hash(readme_text),
            "timing": canonical_hash(timing),
        },
    }


def render_markdown(audit: dict[str, Any]) -> str:
    blockers = audit.get("blocked_by", [])
    lines = [
        f"# README Graph Visibility {audit['visibility_id']}",
        "",
        f"- Status: `{audit['status']}`",
        f"- Decision: `{audit['decision']}`",
        f"- Process graph visible: `{audit['process_graph_visible']}`",
        f"- Benchmark graph visible: `{audit['benchmark_graph_visible']}`",
        f"- Public benchmark claim allowed: `{audit['public_benchmark_claim_allowed']}`",
        f"- Safe label: {audit['safe_label']}",
        "",
        "## Blockers",
        "",
    ]
    if blockers:
        for blocker in blockers:
            lines.append(f"- `{blocker['code']}`: {blocker.get('message', '')}")
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def write_audit(out_dir: Path, audit: dict[str, Any]) -> None:
    write_json_atomic(out_dir / "readme-graph-visibility.json", audit, root=out_dir)
    write_json_atomic(out_dir / "status.json", audit, root=out_dir)
    write_text_atomic(out_dir / "readme-graph-visibility.md", render_markdown(audit), root=out_dir)


def run_audit(readme_path: Path, timing_path: Path, out_dir: Path) -> dict[str, Any]:
    readme_path = resolve_readme(readme_path)
    timing_path = resolve_timing(timing_path)
    out_dir = resolve_out(out_dir)
    prepare_out_dir(out_dir, out_dir.name, source=readme_path)
    timing = read_json(timing_path)
    audit = audit_readme_text(readme_path.read_text(), timing, readme_path=readme_path, timing_path=timing_path, visibility_id=out_dir.name)
    write_audit(out_dir, audit)
    return audit


def run_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    fixtures = manifest.get("fixtures")
    if not isinstance(fixtures, list):
        raise ReadmeGraphVisibilityError("ERR_README_GRAPH_VISIBILITY_MANIFEST_INVALID", "manifest fixtures must be a list", path=manifest_path)
    suite_id = str(manifest.get("suite_id", "v79-readme-graph-visibility"))
    out_dir = resolve_out(out_dir)
    prepare_out_dir(out_dir, out_dir.name, source=manifest_path)
    records = []
    for fixture in fixtures:
        if not isinstance(fixture, dict):
            raise ReadmeGraphVisibilityError("ERR_README_GRAPH_VISIBILITY_MANIFEST_INVALID", "fixture must be an object", path=manifest_path)
        fixture_id = str(fixture.get("id", "fixture"))
        fixture_out = out_dir / fixture_id
        prepare_out_dir(fixture_out, fixture_id, source=manifest_path)
        readme_text = fixture.get("readme_text")
        timing = fixture.get("timing")
        audit = audit_readme_text(
            readme_text if isinstance(readme_text, str) else "",
            timing if isinstance(timing, dict) else {},
            visibility_id=fixture_id,
        )
        write_audit(fixture_out, audit)
        expected_decision = fixture.get("expected_decision")
        status = "pass" if expected_decision in (None, audit["decision"]) else "fail"
        records.append(
            {
                "id": fixture_id,
                "required": bool(fixture.get("required", True)),
                "status": status,
                "decision": audit["decision"],
                "error": None if status == "pass" else f"expected {expected_decision}, got {audit['decision']}",
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
        raise ReadmeGraphVisibilityError("ERR_README_GRAPH_VISIBILITY_FIXTURE_FAILED", "required README graph visibility fixture failed", path=manifest_path)
    return summary


def ready_timing() -> dict[str, Any]:
    return {
        "status": "graph-timing-recorded",
        "decision": "progress-only-visible",
        "decisions": [
            {"graph_type": "process_progress", "decision": "process_progress_ready", "ready": True, "public_claim_allowed": False, "blocked_by": []},
            {"graph_type": "local_benchmark_candidate", "decision": "local_candidate_ready_for_review", "ready": True, "public_claim_allowed": False, "blocked_by": []},
            {
                "graph_type": "public_benchmark_trend",
                "decision": "blocked",
                "ready": False,
                "public_claim_allowed": False,
                "blocked_by": [{"code": "ERR_GRAPH_TIMING_PUBLIC_PROMOTION_MISSING"}],
            },
        ],
    }


def ready_readme() -> str:
    return "\n".join(
        [
            "# DWM",
            "## Evidence Graphs",
            "### Process Progress",
            "![DWM dogfood evidence progress](assets/dwm-dogfood-progress.svg)",
            "It is not a public benchmark graph and does not claim upward performance.",
            "### Benchmark Evidence",
            "![DWM live benchmark evidence](assets/dwm-live-benchmark.svg)",
            "Benchmark visuals are source-bound.",
            "Trend promotion is blocked until release history supports the claim; public trend promotion requires real release history.",
            "",
        ]
    )


def self_test() -> None:
    ready = audit_readme_text(ready_readme(), ready_timing(), visibility_id="self-test")
    if ready["decision"] != "readme_visibility_ready":
        raise ReadmeGraphVisibilityError("ERR_README_GRAPH_VISIBILITY_SELF_TEST_FAILED", "ready README and timing should pass")
    missing_label = audit_readme_text(ready_readme().replace("does not claim upward performance", ""), ready_timing(), visibility_id="self-test-missing-label")
    if missing_label["decision"] != "blocked":
        raise ReadmeGraphVisibilityError("ERR_README_GRAPH_VISIBILITY_SELF_TEST_FAILED", "missing process label should block")
    public_ready = ready_timing()
    public_ready["decision"] = "public-benchmark-visible"
    public_ready["decisions"][2]["ready"] = True
    public_ready["decisions"][2]["public_claim_allowed"] = True
    blocked_public = audit_readme_text(ready_readme(), public_ready, visibility_id="self-test-public-ready")
    if blocked_public["decision"] != "blocked":
        raise ReadmeGraphVisibilityError("ERR_README_GRAPH_VISIBILITY_SELF_TEST_FAILED", "public benchmark trend readiness should not pass this gate")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="run V79 README graph visibility self-test")
    parser.add_argument("--manifest", type=Path, help="run README graph visibility fixtures from a manifest")
    parser.add_argument("--out", type=Path, help="output directory under out/readme-graph-visibility")
    subparsers = parser.add_subparsers(dest="command")
    audit_parser = subparsers.add_parser("audit", help="audit README graph visibility against graph timing")
    audit_parser.add_argument("--readme", type=Path, default=DEFAULT_README)
    audit_parser.add_argument("--timing", type=Path, default=DEFAULT_TIMING)
    audit_parser.add_argument("--out", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        if args.self_test:
            self_test()
            print("README graph visibility self-test: pass")
            return
        if args.manifest:
            if args.out is None:
                raise ReadmeGraphVisibilityError("ERR_README_GRAPH_VISIBILITY_ARGS_INVALID", "--manifest requires --out")
            summary = run_manifest(args.manifest, args.out)
            print(json.dumps(summary, sort_keys=True))
            return
        if args.command == "audit":
            audit = run_audit(args.readme, args.timing, args.out)
            print(json.dumps({"status": audit["status"], "decision": audit["decision"], "visibility_id": audit["visibility_id"]}, sort_keys=True))
            return
        raise ReadmeGraphVisibilityError("ERR_README_GRAPH_VISIBILITY_ARGS_INVALID", "choose --self-test, --manifest, or audit")
    except ReadmeGraphVisibilityError as exc:
        print(json.dumps({"status": "error", "error": exc.to_record()}, sort_keys=True), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
