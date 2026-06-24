#!/usr/bin/env python3
"""V59 local dogfood chart candidate gate."""

from __future__ import annotations

import argparse
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
from dwm_dogfood_pair_series import PAIR_SERIES_ROOT, build_series, make_pair_dir  # noqa: E402


TOOL = "dwm_dogfood_chart_candidate.py"
SCHEMA_VERSION = "1.0"
CHART_CANDIDATE_VERSION = "59.0.0"
CHART_ROOT = ROOT / "out" / "dogfood-chart-candidates"
SENTINEL = ".dwm_dogfood_chart_candidate-owned.json"


class DogfoodChartCandidateError(ValueError):
    """Structured V59 dogfood chart candidate failure."""

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
        raise DogfoodChartCandidateError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise DogfoodChartCandidateError(code, "path contains a symlink", path=current)


def resolve_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_DOGFOOD_CHART_CANDIDATE_PATH_UNSAFE", message="chart candidate output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = CHART_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise DogfoodChartCandidateError("ERR_DOGFOOD_CHART_CANDIDATE_PATH_UNSAFE", f"chart candidate output must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise DogfoodChartCandidateError("ERR_DOGFOOD_CHART_CANDIDATE_PATH_UNSAFE", "chart candidate output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_DOGFOOD_CHART_CANDIDATE_PATH_SYMLINK")
    return resolved


def resolve_series(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_DOGFOOD_CHART_CANDIDATE_SERIES_INVALID", message="series path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = PAIR_SERIES_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise DogfoodChartCandidateError("ERR_DOGFOOD_CHART_CANDIDATE_SERIES_INVALID", f"series must resolve under {root_resolved}", path=value) from exc
    check_components_not_symlink(candidate, code="ERR_DOGFOOD_CHART_CANDIDATE_PATH_SYMLINK")
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


def prepare_out_dir(path: Path, chart_id: str, *, source: Path) -> None:
    if path.exists():
        if path.is_symlink():
            raise DogfoodChartCandidateError("ERR_DOGFOOD_CHART_CANDIDATE_PATH_SYMLINK", "chart candidate output is a symlink", path=path)
        if not path.is_dir():
            raise DogfoodChartCandidateError("ERR_DOGFOOD_CHART_CANDIDATE_PATH_UNSAFE", "chart candidate output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("chart_id") != chart_id:
            raise DogfoodChartCandidateError("ERR_DOGFOOD_CHART_CANDIDATE_PATH_UNSAFE", "existing chart candidate output is not chart-owned", path=path)
        shutil.rmtree(path)
    CHART_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(
        path / SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "chart_candidate_version": CHART_CANDIDATE_VERSION,
            "chart_id": chart_id,
            "source_path": rel(source),
            "created_at": now_utc(),
        },
        root=path,
    )


def load_series(series_dir: Path) -> dict[str, Any]:
    series_dir = resolve_series(series_dir)
    series_path = series_dir / "pair-series.json"
    status_path = series_dir / "status.json"
    readiness_path = series_dir / "graph-readiness.json"
    if not series_path.is_file() or series_path.is_symlink() or not status_path.is_file() or status_path.is_symlink():
        raise DogfoodChartCandidateError("ERR_DOGFOOD_CHART_CANDIDATE_SERIES_MISSING", "series artifacts are missing", path=series_dir)
    if not readiness_path.is_file() or readiness_path.is_symlink():
        raise DogfoodChartCandidateError("ERR_DOGFOOD_CHART_CANDIDATE_SERIES_MISSING", "graph-readiness.json is missing", path=series_dir)
    series = read_json(series_path)
    status = read_json(status_path)
    readiness = read_json(readiness_path)
    if series != status or series.get("graph_readiness") != readiness:
        raise DogfoodChartCandidateError("ERR_DOGFOOD_CHART_CANDIDATE_STALE_SERIES", "series status or readiness artifact does not match", path=series_dir)
    if series.get("status") != "dogfood-pair-series-recorded":
        raise DogfoodChartCandidateError("ERR_DOGFOOD_CHART_CANDIDATE_STALE_SERIES", "series is not recorded", path=series_dir)
    if series.get("public_graph_ready") is True:
        raise DogfoodChartCandidateError("ERR_DOGFOOD_CHART_CANDIDATE_OVERCLAIM", "series must not pre-claim public graph readiness", path=series_dir)
    if readiness.get("graph_ready") is not True:
        raise DogfoodChartCandidateError("ERR_DOGFOOD_CHART_CANDIDATE_NOT_READY", "series graph readiness is blocked", path=series_dir)
    pairs = series.get("pairs")
    if not isinstance(pairs, list) or not pairs:
        raise DogfoodChartCandidateError("ERR_DOGFOOD_CHART_CANDIDATE_SERIES_INVALID", "series pairs are missing", path=series_dir)
    return series


def chart_rows(series: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for pair in series["pairs"]:
        task_id = str(pair.get("task_id", ""))
        dwm_seconds = pair.get("dwm_elapsed_seconds")
        direct_seconds = pair.get("direct_elapsed_seconds")
        if not task_id or not isinstance(dwm_seconds, int | float) or not isinstance(direct_seconds, int | float):
            raise DogfoodChartCandidateError("ERR_DOGFOOD_CHART_CANDIDATE_SERIES_INVALID", "series pair timing fields are invalid")
        rows.append(
            {
                "task_id": task_id,
                "dwm_elapsed_seconds": float(dwm_seconds),
                "direct_elapsed_seconds": float(direct_seconds),
                "delta_seconds": round(float(direct_seconds) - float(dwm_seconds), 6),
            }
        )
    return rows


def render_markdown(chart: dict[str, Any]) -> str:
    lines = [
        "# DWM Dogfood Chart Candidate",
        "",
        f"- chart: `{chart['chart_id']}`",
        f"- source series: `{chart['series_id']}`",
        f"- pair count: `{chart['pair_count']}`",
        f"- public README ready: `{chart['public_readme_ready']}`",
        "- claim policy: local candidate only; no public benchmark graph promotion",
        "",
        "| Task | DWM seconds | Direct seconds | Delta seconds |",
        "| --- | --- | --- | --- |",
    ]
    for row in chart["rows"]:
        lines.append(
            f"| `{row['task_id']}` | `{row['dwm_elapsed_seconds']}` | `{row['direct_elapsed_seconds']}` | `{row['delta_seconds']}` |"
        )
    lines.append("")
    return "\n".join(lines)


def render_csv(rows: list[dict[str, Any]]) -> str:
    lines = ["task_id,dwm_elapsed_seconds,direct_elapsed_seconds,delta_seconds"]
    for row in rows:
        lines.append(f"{row['task_id']},{row['dwm_elapsed_seconds']},{row['direct_elapsed_seconds']},{row['delta_seconds']}")
    return "\n".join(lines) + "\n"


def create_candidate(series_dir: Path, out_dir: Path, *, chart_id: str) -> dict[str, Any]:
    series_dir = resolve_series(series_dir)
    series = load_series(series_dir)
    rows = chart_rows(series)
    prepare_out_dir(out_dir, chart_id, source=series_dir)
    chart = {
        "tool": TOOL,
        "schema_version": SCHEMA_VERSION,
        "chart_candidate_version": CHART_CANDIDATE_VERSION,
        "status": "dogfood-chart-candidate-recorded",
        "decision": "local-chart-candidate-ready",
        "chart_id": chart_id,
        "series_id": series["series_id"],
        "pair_count": len(rows),
        "rows": rows,
        "public_readme_ready": False,
        "safe_next_step": "human review before rendering or README graph promotion",
        "source_hashes": {
            "series": canonical_hash(series),
        },
    }
    write_json_atomic(out_dir / "chart-candidate.json", chart, root=out_dir)
    write_json_atomic(out_dir / "status.json", chart, root=out_dir)
    write_text_atomic(out_dir / "chart-candidate.md", render_markdown(chart), root=out_dir)
    write_text_atomic(out_dir / "chart-data.csv", render_csv(rows), root=out_dir)
    return chart


def make_series_dir(base_name: str, suite_dir: Path, *, ready: bool) -> Path:
    task_ids = ["v44-candidate-review-gate", "v45-readme-asset-promotion", "v46-workflow-queue"]
    if not ready:
        task_ids = task_ids[:1]
    pair_dirs = [make_pair_dir(base_name, index, suite_dir, task_id=task_id) for index, task_id in enumerate(task_ids)]
    series_dir = PAIR_SERIES_ROOT / suite_dir.name / f"{base_name}-series"
    build_series(pair_dirs, series_dir, series_id=series_dir.name, source=suite_dir)
    return series_dir


def blocked_fixture_status(kind: str, fixture: dict[str, Any], suite_dir: Path) -> dict[str, Any]:
    try:
        if kind == "not-ready":
            series_dir = make_series_dir(f"{suite_dir.name}-not-ready", suite_dir, ready=False)
            create_candidate(series_dir, suite_dir / kind, chart_id=kind)
        elif kind == "stale-series":
            series_dir = make_series_dir(f"{suite_dir.name}-stale", suite_dir, ready=True)
            status = read_json(series_dir / "status.json")
            status["series_id"] = "stale"
            write_json_atomic(series_dir / "status.json", status, root=series_dir)
            create_candidate(series_dir, suite_dir / kind, chart_id=kind)
        elif kind == "overclaim":
            series_dir = make_series_dir(f"{suite_dir.name}-overclaim", suite_dir, ready=True)
            series = read_json(series_dir / "pair-series.json")
            series["public_graph_ready"] = True
            write_json_atomic(series_dir / "pair-series.json", series, root=series_dir)
            write_json_atomic(series_dir / "status.json", series, root=series_dir)
            create_candidate(series_dir, suite_dir / kind, chart_id=kind)
        else:
            raise DogfoodChartCandidateError("ERR_DOGFOOD_CHART_CANDIDATE_FIXTURE_FAILED", f"unknown blocked fixture kind: {kind}")
    except DogfoodChartCandidateError as exc:
        if fixture.get("expected_error") != exc.code:
            raise
        return {"status": "blocked", "error": exc.to_record()}
    raise DogfoodChartCandidateError("ERR_DOGFOOD_CHART_CANDIDATE_FIXTURE_FAILED", f"{kind} unexpectedly passed")


def run_fixture(fixture: dict[str, Any], suite_dir: Path) -> dict[str, Any]:
    fixture_id = fixture["id"]
    try:
        kind = fixture["kind"]
        if kind == "chart-candidate-ready":
            series_dir = make_series_dir(f"{suite_dir.name}-{fixture_id}", suite_dir, ready=True)
            status = create_candidate(series_dir, suite_dir / fixture_id, chart_id=fixture_id)
        elif kind in {"not-ready", "stale-series", "overclaim"}:
            status = blocked_fixture_status(kind, fixture, suite_dir)
        else:
            raise DogfoodChartCandidateError("ERR_DOGFOOD_CHART_CANDIDATE_FIXTURE_FAILED", f"unknown fixture kind: {kind}")
        expected_status = fixture.get("expected_status")
        if expected_status is not None and status.get("status") != expected_status:
            raise DogfoodChartCandidateError("ERR_DOGFOOD_CHART_CANDIDATE_FIXTURE_FAILED", f"expected status {expected_status}, got {status.get('status')}")
        expected_decision = fixture.get("expected_decision")
        if expected_decision is not None and status.get("decision") != expected_decision:
            raise DogfoodChartCandidateError("ERR_DOGFOOD_CHART_CANDIDATE_FIXTURE_FAILED", f"expected decision {expected_decision}, got {status.get('decision')}")
        expected_error = fixture.get("expected_error")
        actual_error = status.get("error", {}).get("code") if isinstance(status.get("error"), dict) else None
        if expected_error is not None and actual_error != expected_error:
            raise DogfoodChartCandidateError("ERR_DOGFOOD_CHART_CANDIDATE_FIXTURE_FAILED", f"expected error {expected_error}, got {actual_error}")
        return {"id": fixture_id, "status": "pass", "observed_status": status.get("status"), "required": fixture.get("required", True)}
    except DogfoodChartCandidateError as exc:
        record = exc.to_record()
        record["fixture_id"] = fixture_id
        return {"id": fixture_id, "status": "fail", "required": fixture.get("required", True), "error": record}


def evaluate_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    suite_id = Path(out_dir).name
    suite_dir = resolve_out(out_dir)
    if suite_dir.exists():
        sentinel = read_sentinel(suite_dir)
        if sentinel is None or sentinel.get("chart_id") != suite_id:
            raise DogfoodChartCandidateError("ERR_DOGFOOD_CHART_CANDIDATE_PATH_UNSAFE", "existing chart candidate suite is not chart-owned", path=suite_dir)
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
        raise DogfoodChartCandidateError("ERR_DOGFOOD_CHART_CANDIDATE_FIXTURE_FAILED", "manifest decision is kill", path=manifest_path)
    return summary


def self_test() -> None:
    CHART_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dwm-dogfood-chart-candidate-self-test-", dir=CHART_ROOT) as tmp:
        summary = evaluate_manifest(ROOT / "fixtures" / "v59" / "manifest.json", Path(tmp) / "dogfood-chart-candidate-self-test")
    if summary["decision"] != "keep":
        raise DogfoodChartCandidateError("ERR_DOGFOOD_CHART_CANDIDATE_FIXTURE_FAILED", "dogfood chart candidate self-test manifest did not keep")
    print("dwm_dogfood_chart_candidate self-test: pass")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", choices=["candidate"])
    parser.add_argument("--manifest")
    parser.add_argument("--out")
    parser.add_argument("--series")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
        elif args.manifest:
            if not args.out:
                raise DogfoodChartCandidateError("ERR_DOGFOOD_CHART_CANDIDATE_PATH_UNSAFE", "--manifest requires --out")
            summary = evaluate_manifest(Path(args.manifest), Path(args.out))
            print(canonical_json_text({key: summary[key] for key in ["suite_id", "fixture_count", "required_fixture_count", "required_passed", "passed", "failed", "skipped", "decision"]}))
        elif args.command == "candidate":
            if not args.series or not args.out:
                raise DogfoodChartCandidateError("ERR_DOGFOOD_CHART_CANDIDATE_PATH_UNSAFE", "candidate requires --series and --out")
            print(canonical_json_text(create_candidate(Path(args.series), resolve_out(args.out), chart_id=Path(args.out).name)))
        else:
            parser.error("expected --self-test, --manifest, or candidate")
    except DogfoodChartCandidateError as exc:
        print(canonical_json_text(exc.to_record()), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
