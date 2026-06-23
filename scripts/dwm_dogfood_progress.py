#!/usr/bin/env python3
"""V66 dogfood evidence process progress graph."""

from __future__ import annotations

import argparse
import html
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

from compile_workflow import canonical_hash, canonical_json_text, read_json, write_json_atomic, write_text_atomic  # noqa: E402


TOOL = "dwm_dogfood_progress.py"
SCHEMA_VERSION = "1.0"
PROGRESS_VERSION = "66.0.0"
PROGRESS_ROOT = ROOT / "out" / "dogfood-progress"
SENTINEL = ".dwm_dogfood_progress-owned.json"


STAGES = [
    {
        "id": "acquisition",
        "label": "Acquisition",
        "root": "out/dogfood-acquisitions",
        "artifact": "acquisition.json",
        "expected_status": "dogfood-acquisition-recorded",
    },
    {
        "id": "pair",
        "label": "Pairs",
        "root": "out/dogfood-pairs",
        "artifact": "comparison-pair.json",
        "status_artifact": "pair-status.json",
        "expected_status": "dogfood-comparison-pair-recorded",
    },
    {
        "id": "clean_root",
        "label": "Clean Root",
        "root": "out/dogfood-pair-selections",
        "artifact": "pair-selection.json",
        "expected_status": "dogfood-pair-selection-recorded",
        "expected_decision": "clean-pair-root-ready",
    },
    {
        "id": "series",
        "label": "Series",
        "root": "out/dogfood-pair-series",
        "artifact": "pair-series.json",
        "expected_status": "dogfood-pair-series-recorded",
        "graph_ready": True,
    },
    {
        "id": "candidate",
        "label": "Candidate",
        "root": "out/dogfood-chart-candidates",
        "artifact": "chart-candidate.json",
        "expected_status": "dogfood-chart-candidate-recorded",
    },
    {
        "id": "review",
        "label": "Review",
        "root": "out/dogfood-chart-reviews",
        "artifact": "chart-review.json",
        "expected_status": "dogfood-chart-review-approved",
    },
    {
        "id": "render",
        "label": "Local Render",
        "root": "out/dogfood-chart-renders",
        "artifact": "chart-render.json",
        "expected_status": "dogfood-chart-render-recorded",
    },
]


class DogfoodProgressError(ValueError):
    """Structured V66 dogfood progress failure."""

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
        raise DogfoodProgressError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise DogfoodProgressError(code, "path contains a symlink", path=current)


def resolve_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_DOGFOOD_PROGRESS_PATH_UNSAFE", message="progress output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = PROGRESS_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise DogfoodProgressError("ERR_DOGFOOD_PROGRESS_PATH_UNSAFE", f"progress output must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise DogfoodProgressError("ERR_DOGFOOD_PROGRESS_PATH_UNSAFE", "progress output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_DOGFOOD_PROGRESS_PATH_SYMLINK")
    return resolved


def resolve_source_root(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_DOGFOOD_PROGRESS_SOURCE_ROOT_UNSAFE", message="source root must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to((ROOT / "out").resolve(strict=False))
    except ValueError as exc:
        raise DogfoodProgressError("ERR_DOGFOOD_PROGRESS_SOURCE_ROOT_UNSAFE", "source root must resolve under out", path=value) from exc
    check_components_not_symlink(candidate, code="ERR_DOGFOOD_PROGRESS_PATH_SYMLINK")
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


def prepare_out_dir(path: Path, progress_id: str, *, source: Path) -> None:
    if path.exists():
        if path.is_symlink():
            raise DogfoodProgressError("ERR_DOGFOOD_PROGRESS_PATH_SYMLINK", "progress output is a symlink", path=path)
        if not path.is_dir():
            raise DogfoodProgressError("ERR_DOGFOOD_PROGRESS_PATH_UNSAFE", "progress output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("progress_id") != progress_id:
            raise DogfoodProgressError("ERR_DOGFOOD_PROGRESS_PATH_UNSAFE", "existing progress output is not progress-owned", path=path)
        shutil.rmtree(path)
    PROGRESS_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(
        path / SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "progress_version": PROGRESS_VERSION,
            "progress_id": progress_id,
            "source_path": rel(source),
            "created_at": now_utc(),
        },
        root=path,
    )


def stage_roots(overrides: dict[str, str]) -> list[dict[str, Any]]:
    stages = []
    for stage in STAGES:
        copied = dict(stage)
        if stage["id"] in overrides:
            copied["root"] = overrides[stage["id"]]
        stages.append(copied)
    return stages


def artifact_dirs(root: Path, artifact: str) -> list[Path]:
    if not root.is_dir() or root.is_symlink():
        return []
    return [
        child
        for child in sorted(root.iterdir())
        if child.is_dir() and not child.is_symlink() and not child.name.startswith(".") and (child / artifact).is_file()
    ]


def load_artifact(directory: Path, artifact: str, status_artifact: str = "status.json") -> tuple[dict[str, Any], str]:
    artifact_path = directory / artifact
    status_path = directory / status_artifact
    if not artifact_path.is_file() or artifact_path.is_symlink():
        raise DogfoodProgressError("ERR_DOGFOOD_PROGRESS_ARTIFACT_MISSING", f"{artifact} is missing", path=directory)
    if not status_path.is_file() or status_path.is_symlink():
        raise DogfoodProgressError("ERR_DOGFOOD_PROGRESS_STATUS_MISSING", "status.json is missing", path=directory)
    artifact_data = read_json(artifact_path)
    status_data = read_json(status_path)
    if artifact_data != status_data:
        raise DogfoodProgressError("ERR_DOGFOOD_PROGRESS_STALE_ARTIFACT", "artifact and status differ", path=directory)
    return artifact_data, canonical_hash(artifact_data)


def stage_record(stage: dict[str, Any]) -> dict[str, Any]:
    root = resolve_source_root(stage["root"])
    candidates = []
    blockers = []
    for directory in artifact_dirs(root, stage["artifact"]):
        try:
            data, source_hash = load_artifact(directory, stage["artifact"], stage.get("status_artifact", "status.json"))
        except DogfoodProgressError as exc:
            if exc.code == "ERR_DOGFOOD_PROGRESS_STATUS_MISSING":
                blockers.append(f"{exc.code}:{rel(directory)}")
                continue
            raise
        status_ok = data.get("status") == stage["expected_status"]
        decision_ok = stage.get("expected_decision") is None or data.get("decision") == stage["expected_decision"]
        graph_ok = True
        if stage.get("graph_ready") is True:
            graph_ok = data.get("graph_readiness", {}).get("graph_ready") is True
            if not graph_ok:
                blockers.extend(data.get("graph_readiness", {}).get("blocked_by", []))
        if status_ok and decision_ok and graph_ok:
            candidates.append({"path": rel(directory), "source_hash": source_hash})
        else:
            blockers.append(str(data.get("decision") or data.get("status") or "not-ready"))
    return {
        "id": stage["id"],
        "label": stage["label"],
        "root": rel(root),
        "artifact": stage["artifact"],
        "status": "complete" if candidates else "not-ready",
        "artifact_count": len(candidates),
        "latest_path": candidates[-1]["path"] if candidates else "",
        "blocked_by": sorted(set(blockers)),
        "source_hashes": [item["source_hash"] for item in candidates],
    }


def render_svg(stages: list[dict[str, Any]]) -> str:
    width = 980
    height = 210
    start_x = 70
    gap = 135
    y = 98
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="DWM dogfood evidence progress">',
        '<rect width="100%" height="100%" fill="#f8fafc"/>',
        '<text x="28" y="34" font-family="Arial, sans-serif" font-size="18" font-weight="700" fill="#0f172a">DWM dogfood evidence progress</text>',
        '<text x="28" y="56" font-family="Arial, sans-serif" font-size="12" fill="#475569">Process completion, not upward performance claim</text>',
    ]
    for index, stage in enumerate(stages):
        x = start_x + index * gap
        complete = stage["status"] == "complete"
        fill = "#059669" if complete else "#cbd5e1"
        stroke = "#047857" if complete else "#64748b"
        if index:
            prev_x = start_x + (index - 1) * gap
            line_color = "#059669" if stages[index - 1]["status"] == "complete" and complete else "#94a3b8"
            lines.append(f'<line x1="{prev_x + 31}" y1="{y}" x2="{x - 31}" y2="{y}" stroke="{line_color}" stroke-width="3"/>')
        lines.extend(
            [
                f'<circle cx="{x}" cy="{y}" r="28" fill="{fill}" stroke="{stroke}" stroke-width="2"/>',
                f'<text x="{x}" y="{y + 5}" text-anchor="middle" font-family="Arial, sans-serif" font-size="14" font-weight="700" fill="white">{stage["artifact_count"]}</text>',
                f'<text x="{x}" y="{y + 50}" text-anchor="middle" font-family="Arial, sans-serif" font-size="11" fill="#0f172a">{html.escape(stage["label"])}</text>',
            ]
        )
    lines.extend(
        [
            '<text x="28" y="184" font-family="Arial, sans-serif" font-size="11" fill="#64748b">Green means a hash/status-bound artifact exists. This is not a public benchmark graph.</text>',
            "</svg>",
        ]
    )
    return "\n".join(lines)


def render_md(record: dict[str, Any]) -> str:
    lines = [
        "# DWM Dogfood Progress",
        "",
        f"- progress: `{record['progress_id']}`",
        f"- completed stages: `{record['completed_stage_count']}/{record['stage_count']}`",
        f"- public README ready: `{record['public_readme_ready']}`",
        "- claim policy: process progress only; not an upward benchmark claim",
        "",
        "| Stage | Status | Artifacts | Latest |",
        "| --- | --- | --- | --- |",
    ]
    for stage in record["stages"]:
        latest = stage["latest_path"] or ""
        lines.append(f"| `{stage['label']}` | `{stage['status']}` | `{stage['artifact_count']}` | `{latest}` |")
    lines.append("")
    return "\n".join(lines)


def build_progress(out_dir: Path, *, overrides: dict[str, str]) -> dict[str, Any]:
    out_dir = resolve_out(out_dir)
    progress_id = out_dir.name
    stages = [stage_record(stage) for stage in stage_roots(overrides)]
    completed = sum(1 for stage in stages if stage["status"] == "complete")
    prepare_out_dir(out_dir, progress_id, source=Path("dogfood-progress-inputs"))
    svg_path = out_dir / "dogfood-progress.svg"
    write_text_atomic(svg_path, render_svg(stages), root=out_dir)
    record = {
        "tool": TOOL,
        "schema_version": SCHEMA_VERSION,
        "progress_version": PROGRESS_VERSION,
        "status": "dogfood-progress-recorded",
        "decision": "process-progress-recorded",
        "progress_id": progress_id,
        "stage_count": len(stages),
        "completed_stage_count": completed,
        "stages": stages,
        "svg_path": rel(svg_path),
        "public_readme_ready": False,
        "safe_next_step": "update process progress freely; keep benchmark promotion gated",
        "source_hashes": {
            "stages": canonical_hash(stages),
            "svg": canonical_hash(svg_path.read_text()),
        },
    }
    write_json_atomic(out_dir / "dogfood-progress.json", record, root=out_dir)
    write_json_atomic(out_dir / "status.json", record, root=out_dir)
    write_text_atomic(out_dir / "dogfood-progress.md", render_md(record), root=out_dir)
    return record


def write_fixture_artifact(root: Path, item_id: str, artifact: str, payload: dict[str, Any], *, status_artifact: str = "status.json") -> None:
    directory = root / item_id
    directory.mkdir(parents=True, exist_ok=True)
    write_json_atomic(directory / artifact, payload, root=directory)
    write_json_atomic(directory / status_artifact, payload, root=directory)


def make_fixture_roots(suite_dir: Path, kind: str) -> dict[str, str]:
    base = suite_dir / "sources" / kind
    roots = {stage["id"]: base / stage["id"] for stage in STAGES}
    if kind in {"partial", "full", "stale"}:
        write_fixture_artifact(roots["acquisition"], "a", "acquisition.json", {"status": "dogfood-acquisition-recorded", "decision": "pair-recorded-series-updated"})
        write_fixture_artifact(roots["pair"], "p", "comparison-pair.json", {"status": "dogfood-comparison-pair-recorded", "task_id": "t1"}, status_artifact="pair-status.json")
    if kind in {"full", "stale"}:
        write_fixture_artifact(roots["clean_root"], "s", "pair-selection.json", {"status": "dogfood-pair-selection-recorded", "decision": "clean-pair-root-ready"})
        write_fixture_artifact(roots["series"], "series", "pair-series.json", {"status": "dogfood-pair-series-recorded", "graph_readiness": {"graph_ready": True, "blocked_by": []}})
        write_fixture_artifact(roots["candidate"], "c", "chart-candidate.json", {"status": "dogfood-chart-candidate-recorded"})
        write_fixture_artifact(roots["review"], "r", "chart-review.json", {"status": "dogfood-chart-review-approved", "public_readme_ready": False})
        write_fixture_artifact(roots["render"], "render", "chart-render.json", {"status": "dogfood-chart-render-recorded"})
    if kind == "stale":
        status_path = roots["render"] / "render" / "status.json"
        status = read_json(status_path)
        status["status"] = "stale"
        write_json_atomic(status_path, status, root=status_path.parent)
    return {key: rel(value) for key, value in roots.items()}


def blocked_fixture_status(kind: str, fixture: dict[str, Any], suite_dir: Path) -> dict[str, Any]:
    try:
        build_progress(suite_dir / kind, overrides=make_fixture_roots(suite_dir, kind))
    except DogfoodProgressError as exc:
        if fixture.get("expected_error") != exc.code:
            raise
        return {"status": "blocked", "error": exc.to_record()}
    raise DogfoodProgressError("ERR_DOGFOOD_PROGRESS_FIXTURE_FAILED", f"{kind} unexpectedly passed")


def run_fixture(fixture: dict[str, Any], suite_dir: Path) -> dict[str, Any]:
    fixture_id = fixture["id"]
    try:
        kind = fixture["kind"]
        if kind in {"partial", "full"}:
            status = build_progress(suite_dir / fixture_id, overrides=make_fixture_roots(suite_dir, kind))
        elif kind == "stale":
            status = blocked_fixture_status(kind, fixture, suite_dir)
        else:
            raise DogfoodProgressError("ERR_DOGFOOD_PROGRESS_FIXTURE_FAILED", f"unknown fixture kind: {kind}")
        expected_completed = fixture.get("expected_completed_stage_count")
        if expected_completed is not None and status.get("completed_stage_count") != expected_completed:
            raise DogfoodProgressError("ERR_DOGFOOD_PROGRESS_FIXTURE_FAILED", f"expected completed {expected_completed}, got {status.get('completed_stage_count')}")
        expected_error = fixture.get("expected_error")
        actual_error = status.get("error", {}).get("code") if isinstance(status.get("error"), dict) else None
        if expected_error is not None and actual_error != expected_error:
            raise DogfoodProgressError("ERR_DOGFOOD_PROGRESS_FIXTURE_FAILED", f"expected error {expected_error}, got {actual_error}")
        return {"id": fixture_id, "status": "pass", "observed_status": status.get("status"), "required": fixture.get("required", True)}
    except DogfoodProgressError as exc:
        record = exc.to_record()
        record["fixture_id"] = fixture_id
        return {"id": fixture_id, "status": "fail", "required": fixture.get("required", True), "error": record}


def evaluate_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    suite_id = Path(out_dir).name
    suite_dir = resolve_out(out_dir)
    if suite_dir.exists():
        sentinel = read_sentinel(suite_dir)
        if sentinel is None or sentinel.get("progress_id") != suite_id:
            raise DogfoodProgressError("ERR_DOGFOOD_PROGRESS_PATH_UNSAFE", "existing progress suite is not progress-owned", path=suite_dir)
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
        raise DogfoodProgressError("ERR_DOGFOOD_PROGRESS_FIXTURE_FAILED", "manifest decision is kill", path=manifest_path)
    return summary


def parse_override(values: list[str]) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise DogfoodProgressError("ERR_DOGFOOD_PROGRESS_SOURCE_ROOT_UNSAFE", "override must be stage_id=path", path=value)
        key, path = value.split("=", 1)
        if key not in {stage["id"] for stage in STAGES}:
            raise DogfoodProgressError("ERR_DOGFOOD_PROGRESS_SOURCE_ROOT_UNSAFE", "unknown stage override", path=key)
        overrides[key] = path
    return overrides


def self_test() -> None:
    PROGRESS_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dwm-dogfood-progress-self-test-", dir=PROGRESS_ROOT) as tmp:
        summary = evaluate_manifest(ROOT / "fixtures" / "v66" / "manifest.json", Path(tmp) / "dogfood-progress-self-test")
    if summary["decision"] != "keep":
        raise DogfoodProgressError("ERR_DOGFOOD_PROGRESS_FIXTURE_FAILED", "dogfood progress self-test manifest did not keep")
    print("dwm_dogfood_progress self-test: pass")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", choices=["build"])
    parser.add_argument("--manifest")
    parser.add_argument("--out")
    parser.add_argument("--override", action="append", default=[])
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
        elif args.manifest:
            if not args.out:
                raise DogfoodProgressError("ERR_DOGFOOD_PROGRESS_PATH_UNSAFE", "--manifest requires --out")
            summary = evaluate_manifest(Path(args.manifest), Path(args.out))
            print(canonical_json_text({key: summary[key] for key in ["suite_id", "fixture_count", "required_fixture_count", "required_passed", "passed", "failed", "skipped", "decision"]}))
        elif args.command == "build":
            if not args.out:
                raise DogfoodProgressError("ERR_DOGFOOD_PROGRESS_PATH_UNSAFE", "build requires --out")
            print(canonical_json_text(build_progress(Path(args.out), overrides=parse_override(args.override))))
        else:
            parser.error("expected --self-test, --manifest, or build")
    except DogfoodProgressError as exc:
        print(canonical_json_text(exc.to_record()), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
