#!/usr/bin/env python3
"""V65 reviewed local dogfood chart renderer."""

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


TOOL = "dwm_dogfood_chart_render.py"
SCHEMA_VERSION = "1.0"
RENDER_VERSION = "65.0.0"
RENDER_ROOT = ROOT / "out" / "dogfood-chart-renders"
SENTINEL = ".dwm_dogfood_chart_render-owned.json"


class DogfoodChartRenderError(ValueError):
    """Structured V65 dogfood chart render failure."""

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
        raise DogfoodChartRenderError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise DogfoodChartRenderError(code, "path contains a symlink", path=current)


def resolve_under(value: str | Path, root: Path, *, code: str, label: str) -> Path:
    raw = Path(value)
    reject_traversal(raw, code=code, message=f"{label} path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = root.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise DogfoodChartRenderError(code, f"{label} must resolve under {root_resolved}", path=value) from exc
    check_components_not_symlink(candidate, code="ERR_DOGFOOD_CHART_RENDER_PATH_SYMLINK")
    return resolved


def resolve_out(value: str | Path) -> Path:
    path = resolve_under(value, RENDER_ROOT, code="ERR_DOGFOOD_CHART_RENDER_PATH_UNSAFE", label="chart render output")
    if path == RENDER_ROOT.resolve(strict=False):
        raise DogfoodChartRenderError("ERR_DOGFOOD_CHART_RENDER_PATH_UNSAFE", "chart render output must name a directory", path=value)
    return path


def chart_candidate_api() -> tuple[Path, Any, Any]:
    from dwm_dogfood_chart_candidate import CHART_ROOT, create_candidate, make_series_dir

    return CHART_ROOT, create_candidate, make_series_dir


def chart_review_api() -> tuple[Path, Any, Any]:
    from dwm_dogfood_chart_review import REVIEW_ROOT, make_receipt, review_candidate

    return REVIEW_ROOT, make_receipt, review_candidate


def resolve_review(value: str | Path) -> Path:
    review_root, _make_receipt, _review_candidate = chart_review_api()
    return resolve_under(value, review_root, code="ERR_DOGFOOD_CHART_RENDER_REVIEW_INVALID", label="chart review")


def read_sentinel(path: Path) -> dict[str, Any] | None:
    sentinel = path / SENTINEL
    if not sentinel.is_file() or sentinel.is_symlink():
        return None
    try:
        data = json.loads(sentinel.read_text())
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def prepare_out_dir(path: Path, render_id: str, *, source: Path) -> None:
    if path.exists():
        if path.is_symlink():
            raise DogfoodChartRenderError("ERR_DOGFOOD_CHART_RENDER_PATH_SYMLINK", "chart render output is a symlink", path=path)
        if not path.is_dir():
            raise DogfoodChartRenderError("ERR_DOGFOOD_CHART_RENDER_PATH_UNSAFE", "chart render output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("render_id") != render_id:
            raise DogfoodChartRenderError("ERR_DOGFOOD_CHART_RENDER_PATH_UNSAFE", "existing chart render output is not render-owned", path=path)
        shutil.rmtree(path)
    RENDER_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(
        path / SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "render_version": RENDER_VERSION,
            "render_id": render_id,
            "source_path": rel(source),
            "created_at": now_utc(),
        },
        root=path,
    )


def read_json_obj(path: Path, *, code: str, message: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise DogfoodChartRenderError(code, message, path=path)
    data = read_json(path)
    if not isinstance(data, dict):
        raise DogfoodChartRenderError(code, f"{path.name} must be a JSON object", path=path)
    return data


def load_review(review_dir: Path) -> dict[str, Any]:
    review_dir = resolve_review(review_dir)
    review = read_json_obj(review_dir / "chart-review.json", code="ERR_DOGFOOD_CHART_RENDER_REVIEW_MISSING", message="chart-review.json is missing")
    status = read_json_obj(review_dir / "status.json", code="ERR_DOGFOOD_CHART_RENDER_REVIEW_MISSING", message="status.json is missing")
    if review != status:
        raise DogfoodChartRenderError("ERR_DOGFOOD_CHART_RENDER_STALE_REVIEW", "chart review status and artifact do not match", path=review_dir)
    if review.get("status") != "dogfood-chart-review-approved":
        raise DogfoodChartRenderError("ERR_DOGFOOD_CHART_RENDER_REVIEW_REJECTED", "chart review is not approved", path=review_dir)
    if review.get("public_readme_ready") is True:
        raise DogfoodChartRenderError("ERR_DOGFOOD_CHART_RENDER_OVERCLAIM", "review must not approve public README readiness", path=review_dir)
    candidate_path = review.get("candidate_path")
    if not isinstance(candidate_path, str) or not candidate_path:
        raise DogfoodChartRenderError("ERR_DOGFOOD_CHART_RENDER_REVIEW_MISSING", "review candidate_path is missing", path=review_dir)
    return review


def load_candidate(review: dict[str, Any]) -> dict[str, Any]:
    candidate_dir = ROOT / review["candidate_path"]
    chart_root, _create_candidate, _make_series_dir = chart_candidate_api()
    resolved = resolve_under(candidate_dir, chart_root, code="ERR_DOGFOOD_CHART_RENDER_CANDIDATE_INVALID", label="chart candidate")
    candidate = read_json_obj(resolved / "chart-candidate.json", code="ERR_DOGFOOD_CHART_RENDER_CANDIDATE_MISSING", message="chart-candidate.json is missing")
    status = read_json_obj(resolved / "status.json", code="ERR_DOGFOOD_CHART_RENDER_CANDIDATE_MISSING", message="status.json is missing")
    if candidate != status:
        raise DogfoodChartRenderError("ERR_DOGFOOD_CHART_RENDER_STALE_CANDIDATE", "chart candidate status and artifact do not match", path=resolved)
    if candidate.get("status") != "dogfood-chart-candidate-recorded":
        raise DogfoodChartRenderError("ERR_DOGFOOD_CHART_RENDER_STALE_CANDIDATE", "chart candidate is not recorded", path=resolved)
    expected_hash = review.get("source_hashes", {}).get("chart_candidate")
    if expected_hash != canonical_hash(candidate):
        raise DogfoodChartRenderError("ERR_DOGFOOD_CHART_RENDER_STALE_CANDIDATE", "review chart candidate hash does not match candidate", path=resolved)
    if candidate.get("public_readme_ready") is True:
        raise DogfoodChartRenderError("ERR_DOGFOOD_CHART_RENDER_OVERCLAIM", "candidate must not pre-claim public README readiness", path=resolved)
    return candidate


def render_svg(candidate: dict[str, Any]) -> str:
    rows = candidate["rows"]
    width = 820
    top = 48
    row_height = 52
    height = top + 72 + row_height * len(rows)
    label_x = 28
    zero_x = 360
    scale = 280
    max_abs = max([abs(float(row["delta_seconds"])) for row in rows] + [0.001])
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="Local dogfood chart">',
        '<rect width="100%" height="100%" fill="#f8fafc"/>',
        '<text x="28" y="30" font-family="Arial, sans-serif" font-size="18" font-weight="700" fill="#0f172a">Local dogfood delta seconds</text>',
        '<text x="28" y="50" font-family="Arial, sans-serif" font-size="12" fill="#475569">DWM minus direct; local evidence only</text>',
        f'<line x1="{zero_x}" y1="{top + 18}" x2="{zero_x}" y2="{height - 42}" stroke="#334155" stroke-width="1"/>',
    ]
    for index, row in enumerate(rows):
        y = top + 42 + index * row_height
        delta = float(row["delta_seconds"])
        bar_width = max(2.0, abs(delta) / max_abs * scale)
        x = zero_x if delta >= 0 else zero_x - bar_width
        fill = "#0f766e" if delta >= 0 else "#b91c1c"
        task = html.escape(str(row["task_id"]))
        lines.extend(
            [
                f'<text x="{label_x}" y="{y + 5}" font-family="Arial, sans-serif" font-size="12" fill="#0f172a">{task}</text>',
                f'<rect x="{x:.2f}" y="{y - 12}" width="{bar_width:.2f}" height="22" rx="2" fill="{fill}"/>',
                f'<text x="{zero_x + scale + 18}" y="{y + 5}" font-family="Arial, sans-serif" font-size="12" fill="#334155">{delta:.3f}s</text>',
            ]
        )
    lines.extend(
        [
            f'<text x="28" y="{height - 18}" font-family="Arial, sans-serif" font-size="11" fill="#64748b">Not a public benchmark. README promotion remains gated.</text>',
            "</svg>",
        ]
    )
    return "\n".join(lines)


def render_doc(record: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# DWM Dogfood Chart Render",
            "",
            f"- render: `{record['render_id']}`",
            f"- chart: `{record['chart_id']}`",
            f"- status: `{record['status']}`",
            f"- svg: `{record['svg_path']}`",
            f"- pair count: `{record['pair_count']}`",
            f"- public README ready: `{record['public_readme_ready']}`",
            "- claim policy: local render only; README promotion remains gated",
            "",
        ]
    )


def render_review(review_dir: Path, out_dir: Path) -> dict[str, Any]:
    review_dir = resolve_review(review_dir)
    out_dir = resolve_out(out_dir)
    render_id = out_dir.name
    review = load_review(review_dir)
    candidate = load_candidate(review)
    prepare_out_dir(out_dir, render_id, source=review_dir)
    svg_path = out_dir / "chart-render.svg"
    write_text_atomic(svg_path, render_svg(candidate), root=out_dir)
    record = {
        "tool": TOOL,
        "schema_version": SCHEMA_VERSION,
        "render_version": RENDER_VERSION,
        "status": "dogfood-chart-render-recorded",
        "decision": "local-chart-render-ready",
        "render_id": render_id,
        "review_path": rel(review_dir),
        "chart_id": candidate["chart_id"],
        "pair_count": candidate["pair_count"],
        "rows": candidate["rows"],
        "svg_path": rel(svg_path),
        "public_readme_ready": False,
        "safe_next_step": "separate README promotion gate is still required",
        "source_hashes": {
            "chart_review": canonical_hash(review),
            "chart_candidate": canonical_hash(candidate),
            "svg": canonical_hash(svg_path.read_text()),
        },
    }
    write_json_atomic(out_dir / "chart-render.json", record, root=out_dir)
    write_json_atomic(out_dir / "status.json", record, root=out_dir)
    write_text_atomic(out_dir / "chart-render.md", render_doc(record), root=out_dir)
    return record


def make_review_dir(base_name: str, suite_dir: Path) -> Path:
    chart_root, create_candidate, make_series_dir = chart_candidate_api()
    review_root, make_receipt, review_candidate = chart_review_api()
    series_dir = make_series_dir(base_name, suite_dir, ready=True)
    candidate_dir = chart_root / suite_dir.name / f"{base_name}-candidate"
    create_candidate(series_dir, candidate_dir, chart_id=candidate_dir.name)
    receipt = make_receipt(candidate_dir, suite_dir, base_name)
    review_dir = review_root / suite_dir.name / f"{base_name}-review"
    review_candidate(candidate_dir, receipt, review_dir, review_id=review_dir.name)
    return review_dir


def blocked_fixture_status(kind: str, fixture: dict[str, Any], suite_dir: Path) -> dict[str, Any]:
    try:
        if kind == "stale-review":
            review_dir = make_review_dir(kind, suite_dir)
            status = read_json(review_dir / "status.json")
            status["review_id"] = "stale"
            write_json_atomic(review_dir / "status.json", status, root=review_dir)
            render_review(review_dir, suite_dir / kind)
        elif kind == "overclaim-review":
            review_dir = make_review_dir(kind, suite_dir)
            review = read_json(review_dir / "chart-review.json")
            review["public_readme_ready"] = True
            write_json_atomic(review_dir / "chart-review.json", review, root=review_dir)
            write_json_atomic(review_dir / "status.json", review, root=review_dir)
            render_review(review_dir, suite_dir / kind)
        elif kind == "stale-candidate":
            review_dir = make_review_dir(kind, suite_dir)
            review = read_json(review_dir / "chart-review.json")
            candidate_dir = ROOT / review["candidate_path"]
            candidate = read_json(candidate_dir / "chart-candidate.json")
            candidate["pair_count"] = 99
            write_json_atomic(candidate_dir / "chart-candidate.json", candidate, root=candidate_dir)
            write_json_atomic(candidate_dir / "status.json", candidate, root=candidate_dir)
            render_review(review_dir, suite_dir / kind)
        else:
            raise DogfoodChartRenderError("ERR_DOGFOOD_CHART_RENDER_FIXTURE_FAILED", f"unknown blocked fixture kind: {kind}")
    except DogfoodChartRenderError as exc:
        if fixture.get("expected_error") != exc.code:
            raise
        return {"status": "blocked", "error": exc.to_record()}
    raise DogfoodChartRenderError("ERR_DOGFOOD_CHART_RENDER_FIXTURE_FAILED", f"{kind} unexpectedly passed")


def run_fixture(fixture: dict[str, Any], suite_dir: Path) -> dict[str, Any]:
    fixture_id = fixture["id"]
    try:
        kind = fixture["kind"]
        if kind == "render-approved":
            status = render_review(make_review_dir(fixture_id, suite_dir), suite_dir / fixture_id)
        elif kind in {"stale-review", "overclaim-review", "stale-candidate"}:
            status = blocked_fixture_status(kind, fixture, suite_dir)
        else:
            raise DogfoodChartRenderError("ERR_DOGFOOD_CHART_RENDER_FIXTURE_FAILED", f"unknown fixture kind: {kind}")
        expected_status = fixture.get("expected_status")
        observed_status = status.get("status")
        if expected_status is not None and observed_status != expected_status:
            raise DogfoodChartRenderError("ERR_DOGFOOD_CHART_RENDER_FIXTURE_FAILED", f"expected status {expected_status}, got {observed_status}")
        expected_error = fixture.get("expected_error")
        actual_error = status.get("error", {}).get("code") if isinstance(status.get("error"), dict) else None
        if expected_error is not None and actual_error != expected_error:
            raise DogfoodChartRenderError("ERR_DOGFOOD_CHART_RENDER_FIXTURE_FAILED", f"expected error {expected_error}, got {actual_error}")
        return {"id": fixture_id, "status": "pass", "observed_status": observed_status, "required": fixture.get("required", True)}
    except DogfoodChartRenderError as exc:
        record = exc.to_record()
        record["fixture_id"] = fixture_id
        return {"id": fixture_id, "status": "fail", "required": fixture.get("required", True), "error": record}


def evaluate_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    suite_id = Path(out_dir).name
    suite_dir = resolve_out(out_dir)
    if suite_dir.exists():
        sentinel = read_sentinel(suite_dir)
        if sentinel is None or sentinel.get("render_id") != suite_id:
            raise DogfoodChartRenderError("ERR_DOGFOOD_CHART_RENDER_PATH_UNSAFE", "existing render suite is not render-owned", path=suite_dir)
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
        raise DogfoodChartRenderError("ERR_DOGFOOD_CHART_RENDER_FIXTURE_FAILED", "manifest decision is kill", path=manifest_path)
    return summary


def self_test() -> None:
    RENDER_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dwm-dogfood-chart-render-self-test-", dir=RENDER_ROOT) as tmp:
        summary = evaluate_manifest(ROOT / "fixtures" / "v65" / "manifest.json", Path(tmp) / "dogfood-chart-render-self-test")
    if summary["decision"] != "keep":
        raise DogfoodChartRenderError("ERR_DOGFOOD_CHART_RENDER_FIXTURE_FAILED", "dogfood chart render self-test manifest did not keep")
    print("dwm_dogfood_chart_render self-test: pass")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", choices=["render"])
    parser.add_argument("--manifest")
    parser.add_argument("--out")
    parser.add_argument("--review")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
        elif args.manifest:
            if not args.out:
                raise DogfoodChartRenderError("ERR_DOGFOOD_CHART_RENDER_PATH_UNSAFE", "--manifest requires --out")
            summary = evaluate_manifest(Path(args.manifest), Path(args.out))
            print(canonical_json_text({key: summary[key] for key in ["suite_id", "fixture_count", "required_fixture_count", "required_passed", "passed", "failed", "skipped", "decision"]}))
        elif args.command == "render":
            if not args.review or not args.out:
                raise DogfoodChartRenderError("ERR_DOGFOOD_CHART_RENDER_PATH_UNSAFE", "render requires --review and --out")
            print(canonical_json_text(render_review(Path(args.review), Path(args.out))))
        else:
            parser.error("expected --self-test, --manifest, or render")
    except DogfoodChartRenderError as exc:
        print(canonical_json_text(exc.to_record()), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
