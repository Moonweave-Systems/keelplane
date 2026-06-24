#!/usr/bin/env python3
"""V35 live benchmark report gate."""

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
from dwm_benchmark import REQUIRED_TASK_IDS  # noqa: E402
from dwm_live_score_review import REVIEW_ROOT, make_aggregate_dir, review_aggregate  # noqa: E402


TOOL = "dwm_live_report.py"
SCHEMA_VERSION = "1.0"
REPORT_VERSION = "35.0.0"
REPORT_ROOT = ROOT / "out" / "live-reports"
SENTINEL = ".dwm_live_report-owned.json"


class LiveReportError(ValueError):
    """Structured V35 live report failure."""

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
        raise LiveReportError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise LiveReportError(code, "path contains a symlink", path=current)


def resolve_report_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_LIVE_REPORT_PATH_UNSAFE", message="live report output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = REPORT_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise LiveReportError("ERR_LIVE_REPORT_PATH_UNSAFE", f"live report output must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise LiveReportError("ERR_LIVE_REPORT_PATH_UNSAFE", "live report output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_LIVE_REPORT_PATH_SYMLINK")
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


def prepare_out_dir(path: Path, report_id: str, *, source: Path) -> None:
    if path.exists():
        if path.is_symlink():
            raise LiveReportError("ERR_LIVE_REPORT_PATH_SYMLINK", "live report output is a symlink", path=path)
        if not path.is_dir():
            raise LiveReportError("ERR_LIVE_REPORT_PATH_UNSAFE", "live report output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("report_id") != report_id:
            raise LiveReportError("ERR_LIVE_REPORT_PATH_UNSAFE", "existing live report output is not report-owned", path=path)
        shutil.rmtree(path)
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(
        path / SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "report_version": REPORT_VERSION,
            "report_id": report_id,
            "source_path": rel(source),
            "created_at": now_utc(),
        },
        root=path,
    )


def load_review(review_dir: Path) -> dict[str, Any]:
    reviewed_path = review_dir / "reviewed-score.json"
    status_path = review_dir / "status.json"
    if not reviewed_path.is_file() or reviewed_path.is_symlink() or not status_path.is_file() or status_path.is_symlink():
        raise LiveReportError("ERR_LIVE_REPORT_ARTIFACT_MISSING", "review artifacts are missing", path=review_dir)
    reviewed = read_json(reviewed_path)
    status = read_json(status_path)
    if reviewed != status:
        raise LiveReportError("ERR_LIVE_REPORT_STALE_REVIEW", "review status and artifact do not match", path=review_dir)
    if reviewed.get("status") != "review-recorded":
        raise LiveReportError("ERR_LIVE_REPORT_STALE_REVIEW", "review is not recorded", path=review_dir)
    return reviewed


def validate_review(reviewed: dict[str, Any], *, review_dir: Path) -> None:
    if reviewed.get("task_count") != len(REQUIRED_TASK_IDS):
        raise LiveReportError("ERR_LIVE_REPORT_REVIEW_NOT_READY", "review task count does not match required task set", path=review_dir)
    if not isinstance(reviewed.get("source_hashes"), dict) or not reviewed["source_hashes"].get("aggregate"):
        raise LiveReportError("ERR_LIVE_REPORT_HASH_MISMATCH", "review source hashes are incomplete", path=review_dir)
    if reviewed.get("review_status") not in {"review-ready", "refuted", "unverified"}:
        raise LiveReportError("ERR_LIVE_REPORT_REVIEW_NOT_READY", "review status is unsupported", path=review_dir)


def report_markdown(report: dict[str, Any]) -> str:
    metrics = report["graph_metrics"]
    return "\n".join(
        [
            "# DWM Live Benchmark Report",
            "",
            f"Conclusion: {report['conclusion']}",
            "",
            f"- task_count: {metrics['task_count']}",
            f"- pass_count: {metrics['pass_count']}",
            f"- refuted_count: {metrics['refuted_count']}",
            f"- unverified_count: {metrics['unverified_count']}",
            f"- benchmark_success_claimed: {str(report['benchmark_success_claimed']).lower()}",
            "",
            "This report is generated from hash-bound DWM live scoring artifacts.",
        ]
    ) + "\n"


def publish_report(
    review_dir: Path,
    out_dir: Path,
    *,
    report_id: str,
    expected_review_hash: str | None = None,
    publish_claim: bool = False,
) -> dict[str, Any]:
    reviewed = load_review(review_dir)
    validate_review(reviewed, review_dir=review_dir)
    review_hash = canonical_hash(reviewed)
    if expected_review_hash is not None and expected_review_hash != review_hash:
        raise LiveReportError("ERR_LIVE_REPORT_STALE_REVIEW", "expected review hash does not match current review", path=review_dir)
    if publish_claim and reviewed.get("review_status") != "review-ready":
        raise LiveReportError("ERR_LIVE_REPORT_UNSUPPORTED_CLAIM", "cannot publish benchmark claim without review-ready status", path=review_dir)
    prepare_out_dir(out_dir, report_id, source=review_dir)
    refuted_count = len(reviewed.get("refuted", []))
    unverified_count = len(reviewed.get("unverified", []))
    conclusion = "benchmark-evidence-accepted" if publish_claim else reviewed["review_status"]
    report = {
        "status": "report-recorded",
        "conclusion": conclusion,
        "publish_claim_requested": publish_claim,
        "benchmark_success_claimed": publish_claim and reviewed["review_status"] == "review-ready",
        "graph_metrics": {
            "task_count": reviewed["task_count"],
            "pass_count": reviewed["pass_count"],
            "failed_task_count": len(reviewed.get("failed_task_ids", [])),
            "refuted_count": refuted_count,
            "unverified_count": unverified_count,
            "claim_value": 1 if publish_claim and reviewed["review_status"] == "review-ready" else 0,
        },
        "confirmed": reviewed.get("confirmed", []),
        "refuted": reviewed.get("refuted", []),
        "unverified": reviewed.get("unverified", []),
        "source_hashes": {
            "review": review_hash,
            **reviewed.get("source_hashes", {}),
        },
    }
    write_json_atomic(out_dir / "report.json", report, root=out_dir)
    write_json_atomic(out_dir / "status.json", report, root=out_dir)
    (out_dir / "report.md").write_text(report_markdown(report))
    return report


def make_review_dir(base_name: str, *, failed: bool = False, claim_success: bool = True) -> Path:
    aggregate_dir = make_aggregate_dir(
        f"{base_name}-aggregate-source",
        failed_task_id=REQUIRED_TASK_IDS[0] if failed else None,
        claim_success=claim_success,
    )
    review_dir = REVIEW_ROOT / f"{base_name}-review"
    review_aggregate(aggregate_dir, review_dir, review_id=review_dir.name)
    return review_dir


def blocked_fixture_status(kind: str, fixture: dict[str, Any], suite_id: str) -> dict[str, Any]:
    try:
        if kind == "unsupported-claim":
            review_dir = make_review_dir(f"{suite_id}-unsupported", failed=True, claim_success=False)
            publish_report(review_dir, REPORT_ROOT / f"{suite_id}-unsupported", report_id=f"{suite_id}-unsupported", publish_claim=True)
        elif kind == "stale-review":
            review_dir = make_review_dir(f"{suite_id}-stale")
            publish_report(
                review_dir,
                REPORT_ROOT / f"{suite_id}-stale",
                report_id=f"{suite_id}-stale",
                expected_review_hash=str(fixture["expected_review_hash"]),
            )
        elif kind == "hash-mismatch":
            review_dir = make_review_dir(f"{suite_id}-hash-mismatch")
            reviewed_path = review_dir / "reviewed-score.json"
            reviewed = read_json(reviewed_path)
            reviewed["source_hashes"].pop("aggregate", None)
            write_json_atomic(reviewed_path, reviewed, root=review_dir)
            write_json_atomic(review_dir / "status.json", reviewed, root=review_dir)
            publish_report(review_dir, REPORT_ROOT / f"{suite_id}-hash-mismatch", report_id=f"{suite_id}-hash-mismatch")
        elif kind == "missing-artifact":
            missing_dir = REVIEW_ROOT / f"{suite_id}-missing"
            if missing_dir.exists():
                shutil.rmtree(missing_dir)
            missing_dir.mkdir(parents=True)
            publish_report(missing_dir, REPORT_ROOT / f"{suite_id}-missing", report_id=f"{suite_id}-missing")
        else:
            raise LiveReportError("ERR_LIVE_REPORT_FIXTURE_FAILED", f"unknown blocked fixture kind: {kind}")
    except LiveReportError as exc:
        if fixture.get("expected_error") != exc.code:
            raise
        return {"status": "blocked", "error": exc.to_record()}
    raise LiveReportError("ERR_LIVE_REPORT_FIXTURE_FAILED", f"{kind} unexpectedly passed")


def run_fixture(fixture: dict[str, Any], suite_dir: Path) -> dict[str, Any]:
    fixture_id = fixture["id"]
    try:
        kind = fixture["kind"]
        if kind == "publish-review-ready":
            review_dir = make_review_dir(f"{suite_dir.name}-{fixture_id}", claim_success=True)
            status = publish_report(review_dir, suite_dir / fixture_id, report_id=fixture_id, publish_claim=True)
        elif kind == "record-refuted":
            review_dir = make_review_dir(f"{suite_dir.name}-{fixture_id}", failed=True, claim_success=False)
            status = publish_report(review_dir, suite_dir / fixture_id, report_id=fixture_id)
        elif kind == "record-unverified":
            review_dir = make_review_dir(f"{suite_dir.name}-{fixture_id}", claim_success=False)
            status = publish_report(review_dir, suite_dir / fixture_id, report_id=fixture_id)
        elif kind in {"unsupported-claim", "stale-review", "hash-mismatch", "missing-artifact"}:
            status = blocked_fixture_status(kind, fixture, suite_dir.name)
        else:
            raise LiveReportError("ERR_LIVE_REPORT_FIXTURE_FAILED", f"unknown fixture kind: {kind}")
        expected_status = fixture.get("expected_status")
        if expected_status is not None and status.get("status") != expected_status:
            raise LiveReportError("ERR_LIVE_REPORT_FIXTURE_FAILED", f"expected status {expected_status}, got {status.get('status')}")
        expected_claim = fixture.get("expected_benchmark_success_claimed")
        if expected_claim is not None and status.get("benchmark_success_claimed") != expected_claim:
            raise LiveReportError("ERR_LIVE_REPORT_FIXTURE_FAILED", f"expected benchmark_success_claimed {expected_claim}, got {status.get('benchmark_success_claimed')}")
        expected_error = fixture.get("expected_error")
        actual_error = status.get("error", {}).get("code") if isinstance(status.get("error"), dict) else None
        if expected_error is not None and actual_error != expected_error:
            raise LiveReportError("ERR_LIVE_REPORT_FIXTURE_FAILED", f"expected error {expected_error}, got {actual_error}")
        return {"id": fixture_id, "status": "pass", "observed_status": status.get("status"), "required": fixture.get("required", True)}
    except LiveReportError as exc:
        record = exc.to_record()
        record["fixture_id"] = fixture_id
        return {"id": fixture_id, "status": "fail", "required": fixture.get("required", True), "error": record}


def evaluate_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    suite_id = Path(out_dir).name
    suite_dir = resolve_report_out(out_dir)
    if suite_dir.exists():
        sentinel = read_sentinel(suite_dir)
        if sentinel is None or sentinel.get("report_id") != suite_id:
            raise LiveReportError("ERR_LIVE_REPORT_PATH_UNSAFE", "existing live report suite is not report-owned", path=suite_dir)
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
        raise LiveReportError("ERR_LIVE_REPORT_FIXTURE_FAILED", "manifest decision is kill", path=manifest_path)
    return summary


def self_test() -> None:
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dwm-live-report-self-test-", dir=REPORT_ROOT) as tmp:
        summary = evaluate_manifest(ROOT / "fixtures" / "v35" / "manifest.json", Path(tmp) / "live-report-self-test")
    if summary["decision"] != "keep":
        raise LiveReportError("ERR_LIVE_REPORT_FIXTURE_FAILED", "live report self-test manifest did not keep")
    print("dwm_live_report self-test: pass")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", choices=["publish"])
    parser.add_argument("--expected-review-hash")
    parser.add_argument("--manifest")
    parser.add_argument("--out")
    parser.add_argument("--publish-claim", action="store_true")
    parser.add_argument("--review")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
        elif args.manifest:
            if not args.out:
                raise LiveReportError("ERR_LIVE_REPORT_PATH_UNSAFE", "--manifest requires --out")
            summary = evaluate_manifest(Path(args.manifest), Path(args.out))
            print(canonical_json_text({key: summary[key] for key in ["suite_id", "fixture_count", "required_fixture_count", "required_passed", "passed", "failed", "skipped", "decision"]}))
        elif args.command == "publish":
            if not args.out or not args.review:
                raise LiveReportError("ERR_LIVE_REPORT_PATH_UNSAFE", "publish requires --review and --out")
            status = publish_report(
                Path(args.review),
                resolve_report_out(args.out),
                report_id=Path(args.out).name,
                expected_review_hash=args.expected_review_hash,
                publish_claim=args.publish_claim,
            )
            print(canonical_json_text(status))
        else:
            parser.error("expected --self-test, --manifest, or publish")
    except LiveReportError as exc:
        print(canonical_json_text(exc.to_record()), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
