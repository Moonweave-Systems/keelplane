#!/usr/bin/env python3
"""V38 benchmark history ledger and trend graph."""

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

from compile_workflow import canonical_hash, canonical_json_text, read_json, write_json_atomic  # noqa: E402
from dwm_live_report import REPORT_ROOT, make_review_dir, publish_report  # noqa: E402


TOOL = "dwm_benchmark_history.py"
SCHEMA_VERSION = "1.0"
HISTORY_VERSION = "38.0.0"
HISTORY_ROOT = ROOT / "out" / "benchmark-history"
SENTINEL = ".dwm_benchmark_history-owned.json"


class BenchmarkHistoryError(ValueError):
    """Structured V38 benchmark history failure."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        path: Path | str | None = None,
        fixture_id: str | None = None,
    ) -> None:
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
        raise BenchmarkHistoryError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise BenchmarkHistoryError(code, "path contains a symlink", path=current)


def resolve_history_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_BENCHMARK_HISTORY_PATH_UNSAFE", message="benchmark history output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = HISTORY_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise BenchmarkHistoryError("ERR_BENCHMARK_HISTORY_PATH_UNSAFE", f"benchmark history output must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise BenchmarkHistoryError("ERR_BENCHMARK_HISTORY_PATH_UNSAFE", "benchmark history output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_BENCHMARK_HISTORY_PATH_SYMLINK")
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


def prepare_out_dir(path: Path, history_id: str, *, source: Path) -> None:
    if path.exists():
        if path.is_symlink():
            raise BenchmarkHistoryError("ERR_BENCHMARK_HISTORY_PATH_SYMLINK", "benchmark history output is a symlink", path=path)
        if not path.is_dir():
            raise BenchmarkHistoryError("ERR_BENCHMARK_HISTORY_PATH_UNSAFE", "benchmark history output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("history_id") != history_id:
            raise BenchmarkHistoryError("ERR_BENCHMARK_HISTORY_PATH_UNSAFE", "existing benchmark history output is not history-owned", path=path)
        shutil.rmtree(path)
    HISTORY_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(
        path / SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "history_version": HISTORY_VERSION,
            "history_id": history_id,
            "source_path": rel(source),
            "created_at": now_utc(),
        },
        root=path,
    )


def load_report(report_dir: Path) -> dict[str, Any]:
    report_path = report_dir / "report.json"
    status_path = report_dir / "status.json"
    if not report_path.is_file() or report_path.is_symlink() or not status_path.is_file() or status_path.is_symlink():
        raise BenchmarkHistoryError("ERR_BENCHMARK_HISTORY_ARTIFACT_MISSING", "report artifacts are missing", path=report_dir)
    report = read_json(report_path)
    status = read_json(status_path)
    if report != status:
        raise BenchmarkHistoryError("ERR_BENCHMARK_HISTORY_STALE_REPORT", "report status and artifact do not match", path=report_dir)
    if report.get("status") != "report-recorded":
        raise BenchmarkHistoryError("ERR_BENCHMARK_HISTORY_STALE_REPORT", "report is not recorded", path=report_dir)
    return report


def validate_metrics(report: dict[str, Any], *, report_dir: Path) -> dict[str, int]:
    metrics = report.get("graph_metrics")
    required = ["task_count", "pass_count", "failed_task_count", "refuted_count", "unverified_count", "claim_value"]
    if not isinstance(metrics, dict):
        raise BenchmarkHistoryError("ERR_BENCHMARK_HISTORY_METRICS_INVALID", "report graph_metrics are missing", path=report_dir)
    if any(key not in metrics for key in required):
        raise BenchmarkHistoryError("ERR_BENCHMARK_HISTORY_METRICS_INVALID", "report graph_metrics are incomplete", path=report_dir)
    normalized: dict[str, int] = {}
    for key in required:
        value = metrics[key]
        if not isinstance(value, int) or value < 0:
            raise BenchmarkHistoryError("ERR_BENCHMARK_HISTORY_METRICS_INVALID", f"{key} must be a non-negative integer", path=report_dir)
        normalized[key] = value
    if normalized["task_count"] <= 0:
        raise BenchmarkHistoryError("ERR_BENCHMARK_HISTORY_METRICS_INVALID", "task_count must be positive", path=report_dir)
    if normalized["pass_count"] > normalized["task_count"] or normalized["failed_task_count"] > normalized["task_count"]:
        raise BenchmarkHistoryError("ERR_BENCHMARK_HISTORY_METRICS_INVALID", "graph_metrics counts exceed task_count", path=report_dir)
    return normalized


def score_bps(metrics: dict[str, int]) -> int:
    return round(10000 * metrics["pass_count"] / metrics["task_count"])


def normalize_labels(reports: list[Path], labels: list[str] | None) -> list[str]:
    if labels is None or not labels:
        return [report.name for report in reports]
    if len(labels) != len(reports):
        raise BenchmarkHistoryError("ERR_BENCHMARK_HISTORY_LABEL_MISMATCH", "label count must match report count")
    if any(not label.strip() for label in labels):
        raise BenchmarkHistoryError("ERR_BENCHMARK_HISTORY_LABEL_MISMATCH", "labels must not be empty")
    if len(set(labels)) != len(labels):
        raise BenchmarkHistoryError("ERR_BENCHMARK_HISTORY_LABEL_MISMATCH", "labels must be unique")
    return labels


def normalize_expected_hashes(reports: list[Path], expected_hashes: list[str] | None) -> list[str | None]:
    if expected_hashes is None or not expected_hashes:
        return [None for _ in reports]
    if len(expected_hashes) != len(reports):
        raise BenchmarkHistoryError("ERR_BENCHMARK_HISTORY_STALE_REPORT", "expected report hash count must match report count")
    return expected_hashes


def normalize_source_kinds(reports: list[Path], source_kinds: list[str] | None) -> list[str]:
    if source_kinds is None or not source_kinds:
        return ["ad-hoc" for _ in reports]
    if len(source_kinds) != len(reports):
        raise BenchmarkHistoryError("ERR_BENCHMARK_HISTORY_SOURCE_KIND_MISMATCH", "source-kind count must match report count")
    allowed = {"ad-hoc", "fixture", "release"}
    if any(kind not in allowed for kind in source_kinds):
        raise BenchmarkHistoryError("ERR_BENCHMARK_HISTORY_SOURCE_KIND_MISMATCH", f"source-kind must be one of {sorted(allowed)}")
    return source_kinds


def history_entry(index: int, label: str, report_dir: Path, expected_hash: str | None, source_kind: str) -> dict[str, Any]:
    report = load_report(report_dir)
    metrics = validate_metrics(report, report_dir=report_dir)
    report_hash = canonical_hash(report)
    if expected_hash is not None and expected_hash != report_hash:
        raise BenchmarkHistoryError("ERR_BENCHMARK_HISTORY_STALE_REPORT", "expected report hash does not match current report", path=report_dir)
    return {
        "index": index,
        "label": label,
        "source_path": rel(report_dir),
        "source_kind": source_kind,
        "report_hash": report_hash,
        "score_bps": score_bps(metrics),
        "benchmark_success_claimed": bool(report.get("benchmark_success_claimed")),
        "conclusion": report.get("conclusion"),
        "graph_metrics": metrics,
    }


def snapshot_history_entry(index: int, snapshot_dir: Path, expected_hash: str | None = None) -> dict[str, Any]:
    snapshot_path = snapshot_dir / "snapshot.json"
    status_path = snapshot_dir / "status.json"
    if not snapshot_path.is_file() or snapshot_path.is_symlink() or not status_path.is_file() or status_path.is_symlink():
        raise BenchmarkHistoryError("ERR_BENCHMARK_HISTORY_ARTIFACT_MISSING", "snapshot artifacts are missing", path=snapshot_dir)
    snapshot = read_json(snapshot_path)
    status = read_json(status_path)
    if snapshot != status or snapshot.get("status") != "snapshot-recorded":
        raise BenchmarkHistoryError("ERR_BENCHMARK_HISTORY_STALE_REPORT", "snapshot status and artifact do not match", path=snapshot_dir)
    snapshot_hash = canonical_hash(snapshot)
    if expected_hash is not None and expected_hash != snapshot_hash:
        raise BenchmarkHistoryError("ERR_BENCHMARK_HISTORY_STALE_REPORT", "expected snapshot hash does not match current snapshot", path=snapshot_dir)
    metrics = snapshot.get("graph_metrics")
    if not isinstance(metrics, dict):
        raise BenchmarkHistoryError("ERR_BENCHMARK_HISTORY_METRICS_INVALID", "snapshot graph_metrics are missing", path=snapshot_dir)
    normalized = {key: metrics[key] for key in ["task_count", "pass_count", "failed_task_count", "refuted_count", "unverified_count", "claim_value"]}
    release_id = str(snapshot.get("release_id") or snapshot_dir.name)
    return {
        "index": index,
        "label": release_id,
        "source_path": rel(snapshot_dir),
        "source_kind": snapshot.get("source_kind"),
        "snapshot_hash": snapshot_hash,
        "report_hash": snapshot.get("source_hashes", {}).get("report"),
        "score_bps": snapshot.get("score_bps"),
        "benchmark_success_claimed": bool(snapshot.get("benchmark_success_claimed")),
        "conclusion": snapshot.get("conclusion"),
        "graph_metrics": normalized,
    }


def trend_metrics(entries: list[dict[str, Any]]) -> dict[str, int]:
    scores = [int(entry["score_bps"]) for entry in entries]
    return {
        "entry_count": len(entries),
        "first_score_bps": scores[0],
        "latest_score_bps": scores[-1],
        "best_score_bps": max(scores),
        "delta_score_bps": scores[-1] - scores[0],
    }


def trend_svg(entries: list[dict[str, Any]]) -> str:
    width = 960
    height = 320
    chart_x = 100
    chart_y = 128
    chart_width = 560
    chart_height = 86
    if len(entries) == 1:
        xs = [chart_x + chart_width // 2]
    else:
        xs = [round(chart_x + index * chart_width / (len(entries) - 1)) for index, _ in enumerate(entries)]
    ys = [round(chart_y + chart_height - (int(entry["score_bps"]) / 10000) * chart_height) for entry in entries]
    points = " ".join(f"{x},{y}" for x, y in zip(xs, ys, strict=True))
    latest = entries[-1]
    metric = trend_metrics(entries)
    circles = "\n  ".join(
        f'<circle cx="{x}" cy="{y}" r="6" fill="#0F766E"/><text x="{x}" y="{max(112, y - 14)}" text-anchor="middle" fill="#0F172A" font-family="Inter, ui-sans-serif, system-ui, sans-serif" font-size="13" font-weight="700">{entry["score_bps"] / 100:.1f}%</text>'
        for x, y, entry in zip(xs, ys, entries, strict=True)
    )
    labels = "\n  ".join(
        f'<text x="{x}" y="238" text-anchor="middle" fill="#64748B" font-family="Inter, ui-sans-serif, system-ui, sans-serif" font-size="13">{entry["label"]}</text>'
        for x, entry in zip(xs, entries, strict=True)
    )
    delta = f"{metric['delta_score_bps'] / 100:+.1f}%"
    return f"""<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="title desc">
  <title id="title">DWM benchmark history trend</title>
  <desc id="desc">Hash-bound trend graph generated from V38 benchmark history ledger.</desc>
  <rect width="{width}" height="{height}" rx="20" fill="#F8FAFC"/>
  <rect x="40" y="40" width="880" height="240" rx="18" fill="#FFFFFF" stroke="#E2E8F0"/>
  <text x="72" y="86" fill="#0F172A" font-family="Inter, ui-sans-serif, system-ui, sans-serif" font-size="27" font-weight="800">DWM benchmark history</text>
  <text x="72" y="116" fill="#64748B" font-family="Inter, ui-sans-serif, system-ui, sans-serif" font-size="15">source: report.json.graph_metrics snapshots / {metric['entry_count']} entries</text>
  <text x="74" y="144" fill="#94A3B8" font-family="Inter, ui-sans-serif, system-ui, sans-serif" font-size="12">100%</text>
  <text x="78" y="218" fill="#94A3B8" font-family="Inter, ui-sans-serif, system-ui, sans-serif" font-size="12">0%</text>
  <line x1="{chart_x}" y1="{chart_y + chart_height}" x2="{chart_x + chart_width}" y2="{chart_y + chart_height}" stroke="#CBD5E1"/>
  <line x1="{chart_x}" y1="{chart_y}" x2="{chart_x}" y2="{chart_y + chart_height}" stroke="#CBD5E1"/>
  <polyline points="{points}" fill="none" stroke="#0F766E" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>
  {circles}
  {labels}
  <rect x="704" y="140" width="150" height="38" rx="8" fill="#ECFDF5" stroke="#A7F3D0"/>
  <text x="720" y="165" fill="#047857" font-family="Inter, ui-sans-serif, system-ui, sans-serif" font-size="18" font-weight="800">{latest['score_bps'] / 100:.1f}% latest</text>
  <rect x="704" y="194" width="150" height="38" rx="8" fill="#F8FAFC" stroke="#E2E8F0"/>
  <text x="720" y="219" fill="#0F172A" font-family="Inter, ui-sans-serif, system-ui, sans-serif" font-size="18" font-weight="800">{delta} delta</text>
</svg>
"""


def build_history(
    report_dirs: list[Path],
    out_dir: Path,
    *,
    history_id: str,
    labels: list[str] | None = None,
    expected_report_hashes: list[str] | None = None,
    source_kinds: list[str] | None = None,
) -> dict[str, Any]:
    if not report_dirs:
        raise BenchmarkHistoryError("ERR_BENCHMARK_HISTORY_ARTIFACT_MISSING", "at least one report is required")
    normalized_labels = normalize_labels(report_dirs, labels)
    expected_hashes = normalize_expected_hashes(report_dirs, expected_report_hashes)
    normalized_source_kinds = normalize_source_kinds(report_dirs, source_kinds)
    entries = [
        history_entry(index, label, report_dir, expected_hash, source_kind)
        for index, (label, report_dir, expected_hash, source_kind) in enumerate(
            zip(normalized_labels, report_dirs, expected_hashes, normalized_source_kinds, strict=True)
        )
    ]
    report_hashes = [entry["report_hash"] for entry in entries]
    if len(set(report_hashes)) != len(report_hashes):
        raise BenchmarkHistoryError("ERR_BENCHMARK_HISTORY_DUPLICATE_REPORT", "history entries must not reuse the same report hash")
    prepare_out_dir(out_dir, history_id, source=report_dirs[0])
    history = {
        "status": "history-recorded",
        "history_id": history_id,
        "source": "report.json.graph_metrics snapshots",
        "entries": entries,
        "trend_metrics": trend_metrics(entries),
        "source_hashes": {"reports": report_hashes},
    }
    write_json_atomic(out_dir / "history.json", history, root=out_dir)
    write_json_atomic(out_dir / "status.json", history, root=out_dir)
    (out_dir / "trend.svg").write_text(trend_svg(entries))
    (out_dir / "README-snippet.md").write_text(f"![DWM benchmark history]({rel(out_dir / 'trend.svg')})\n")
    return history


def build_history_from_snapshots(
    snapshot_dirs: list[Path],
    out_dir: Path,
    *,
    history_id: str,
    expected_snapshot_hashes: list[str] | None = None,
) -> dict[str, Any]:
    if not snapshot_dirs:
        raise BenchmarkHistoryError("ERR_BENCHMARK_HISTORY_ARTIFACT_MISSING", "at least one snapshot is required")
    expected_hashes = normalize_expected_hashes(snapshot_dirs, expected_snapshot_hashes)
    entries = [
        snapshot_history_entry(index, snapshot_dir, expected_hash)
        for index, (snapshot_dir, expected_hash) in enumerate(zip(snapshot_dirs, expected_hashes, strict=True))
    ]
    report_hashes = [entry["report_hash"] for entry in entries]
    if len(set(report_hashes)) != len(report_hashes):
        raise BenchmarkHistoryError("ERR_BENCHMARK_HISTORY_DUPLICATE_REPORT", "history entries must not reuse the same report hash")
    prepare_out_dir(out_dir, history_id, source=snapshot_dirs[0])
    history = {
        "status": "history-recorded",
        "history_id": history_id,
        "source": "benchmark release snapshots",
        "entries": entries,
        "trend_metrics": trend_metrics(entries),
        "source_hashes": {
            "reports": report_hashes,
            "snapshots": [entry["snapshot_hash"] for entry in entries],
        },
    }
    write_json_atomic(out_dir / "history.json", history, root=out_dir)
    write_json_atomic(out_dir / "status.json", history, root=out_dir)
    (out_dir / "trend.svg").write_text(trend_svg(entries))
    (out_dir / "README-snippet.md").write_text(f"![DWM benchmark history]({rel(out_dir / 'trend.svg')})\n")
    return history


def make_report_dir(base_name: str, *, publish_claim: bool = True, failed: bool = False) -> Path:
    review_dir = make_review_dir(f"{base_name}-review-source", failed=failed, claim_success=publish_claim)
    report_dir = REPORT_ROOT / f"{base_name}-report"
    publish_report(review_dir, report_dir, report_id=report_dir.name, publish_claim=publish_claim and not failed)
    return report_dir


def blocked_fixture_status(kind: str, fixture: dict[str, Any], suite_id: str) -> dict[str, Any]:
    try:
        if kind == "stale-report":
            report_dir = make_report_dir(f"{suite_id}-stale")
            build_history(
                [report_dir],
                HISTORY_ROOT / f"{suite_id}-stale",
                history_id=f"{suite_id}-stale",
                labels=["stale"],
                expected_report_hashes=[str(fixture["expected_report_hash"])],
            )
        elif kind == "metrics-invalid":
            report_dir = make_report_dir(f"{suite_id}-metrics-invalid")
            report_path = report_dir / "report.json"
            report = read_json(report_path)
            report["graph_metrics"]["pass_count"] = report["graph_metrics"]["task_count"] + 1
            write_json_atomic(report_path, report, root=report_dir)
            write_json_atomic(report_dir / "status.json", report, root=report_dir)
            build_history([report_dir], HISTORY_ROOT / f"{suite_id}-metrics-invalid", history_id=f"{suite_id}-metrics-invalid")
        elif kind == "duplicate-report":
            report_dir = make_report_dir(f"{suite_id}-duplicate")
            build_history(
                [report_dir, report_dir],
                HISTORY_ROOT / f"{suite_id}-duplicate",
                history_id=f"{suite_id}-duplicate",
                labels=["duplicate-a", "duplicate-b"],
            )
        elif kind == "missing-artifact":
            missing_dir = REPORT_ROOT / f"{suite_id}-missing"
            if missing_dir.exists():
                shutil.rmtree(missing_dir)
            missing_dir.mkdir(parents=True)
            build_history([missing_dir], HISTORY_ROOT / f"{suite_id}-missing", history_id=f"{suite_id}-missing")
        else:
            raise BenchmarkHistoryError("ERR_BENCHMARK_HISTORY_FIXTURE_FAILED", f"unknown blocked fixture kind: {kind}")
    except BenchmarkHistoryError as exc:
        if fixture.get("expected_error") != exc.code:
            raise
        return {"status": "blocked", "error": exc.to_record()}
    raise BenchmarkHistoryError("ERR_BENCHMARK_HISTORY_FIXTURE_FAILED", f"{kind} unexpectedly passed")


def run_fixture(fixture: dict[str, Any], suite_dir: Path) -> dict[str, Any]:
    fixture_id = fixture["id"]
    try:
        kind = fixture["kind"]
        if kind == "history-single-report":
            report_dir = make_report_dir(f"{suite_dir.name}-{fixture_id}", publish_claim=True)
            status = build_history([report_dir], suite_dir / fixture_id, history_id=fixture_id, labels=["v35"], source_kinds=["fixture"])
        elif kind == "history-two-point-trend":
            first = make_report_dir(f"{suite_dir.name}-{fixture_id}-first", publish_claim=False, failed=True)
            second = make_report_dir(f"{suite_dir.name}-{fixture_id}-second", publish_claim=True)
            status = build_history([first, second], suite_dir / fixture_id, history_id=fixture_id, labels=["baseline", "current"], source_kinds=["fixture", "fixture"])
        elif kind in {"stale-report", "metrics-invalid", "duplicate-report", "missing-artifact"}:
            status = blocked_fixture_status(kind, fixture, suite_dir.name)
        else:
            raise BenchmarkHistoryError("ERR_BENCHMARK_HISTORY_FIXTURE_FAILED", f"unknown fixture kind: {kind}")
        expected_status = fixture.get("expected_status")
        if expected_status is not None and status.get("status") != expected_status:
            raise BenchmarkHistoryError("ERR_BENCHMARK_HISTORY_FIXTURE_FAILED", f"expected status {expected_status}, got {status.get('status')}")
        expected_entries = fixture.get("expected_entry_count")
        if expected_entries is not None and status.get("trend_metrics", {}).get("entry_count") != expected_entries:
            raise BenchmarkHistoryError("ERR_BENCHMARK_HISTORY_FIXTURE_FAILED", f"expected entry_count {expected_entries}, got {status.get('trend_metrics', {}).get('entry_count')}")
        expected_error = fixture.get("expected_error")
        actual_error = status.get("error", {}).get("code") if isinstance(status.get("error"), dict) else None
        if expected_error is not None and actual_error != expected_error:
            raise BenchmarkHistoryError("ERR_BENCHMARK_HISTORY_FIXTURE_FAILED", f"expected error {expected_error}, got {actual_error}")
        return {"id": fixture_id, "status": "pass", "observed_status": status.get("status"), "required": fixture.get("required", True)}
    except BenchmarkHistoryError as exc:
        record = exc.to_record()
        record["fixture_id"] = fixture_id
        return {"id": fixture_id, "status": "fail", "required": fixture.get("required", True), "error": record}


def evaluate_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    suite_id = Path(out_dir).name
    suite_dir = resolve_history_out(out_dir)
    if suite_dir.exists():
        sentinel = read_sentinel(suite_dir)
        if sentinel is None or sentinel.get("history_id") != suite_id:
            raise BenchmarkHistoryError("ERR_BENCHMARK_HISTORY_PATH_UNSAFE", "existing benchmark history suite is not history-owned", path=suite_dir)
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
        raise BenchmarkHistoryError("ERR_BENCHMARK_HISTORY_FIXTURE_FAILED", "manifest decision is kill", path=manifest_path)
    return summary


def self_test() -> None:
    HISTORY_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dwm-benchmark-history-self-test-", dir=HISTORY_ROOT) as tmp:
        summary = evaluate_manifest(ROOT / "fixtures" / "v38" / "manifest.json", Path(tmp) / "benchmark-history-self-test")
    if summary["decision"] != "keep":
        raise BenchmarkHistoryError("ERR_BENCHMARK_HISTORY_FIXTURE_FAILED", "benchmark history self-test manifest did not keep")
    print("dwm_benchmark_history self-test: pass")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", choices=["build"])
    parser.add_argument("--expected-report-hash", action="append")
    parser.add_argument("--label", action="append")
    parser.add_argument("--manifest")
    parser.add_argument("--out")
    parser.add_argument("--report", action="append")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--snapshot", action="append")
    parser.add_argument("--source-kind", action="append")
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
        elif args.manifest:
            if not args.out:
                raise BenchmarkHistoryError("ERR_BENCHMARK_HISTORY_PATH_UNSAFE", "--manifest requires --out")
            summary = evaluate_manifest(Path(args.manifest), Path(args.out))
            print(canonical_json_text({key: summary[key] for key in ["suite_id", "fixture_count", "required_fixture_count", "required_passed", "passed", "failed", "skipped", "decision"]}))
        elif args.command == "build":
            if not args.out or (not args.report and not args.snapshot):
                raise BenchmarkHistoryError("ERR_BENCHMARK_HISTORY_PATH_UNSAFE", "build requires --report or --snapshot and --out")
            if args.report and args.snapshot:
                raise BenchmarkHistoryError("ERR_BENCHMARK_HISTORY_PATH_UNSAFE", "build accepts either reports or snapshots, not both")
            if args.snapshot:
                status = build_history_from_snapshots(
                    [Path(snapshot) for snapshot in args.snapshot],
                    resolve_history_out(args.out),
                    history_id=Path(args.out).name,
                    expected_snapshot_hashes=args.expected_report_hash,
                )
            else:
                status = build_history(
                    [Path(report) for report in args.report],
                    resolve_history_out(args.out),
                    history_id=Path(args.out).name,
                    labels=args.label,
                    expected_report_hashes=args.expected_report_hash,
                    source_kinds=args.source_kind,
                )
            print(canonical_json_text(status))
        else:
            parser.error("expected --self-test, --manifest, or build")
    except BenchmarkHistoryError as exc:
        print(canonical_json_text(exc.to_record()), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
