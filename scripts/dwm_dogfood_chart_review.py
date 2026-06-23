#!/usr/bin/env python3
"""V60 local dogfood chart candidate review gate."""

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
from dwm_dogfood_chart_candidate import CHART_ROOT, create_candidate, make_series_dir  # noqa: E402


TOOL = "dwm_dogfood_chart_review.py"
SCHEMA_VERSION = "1.0"
CHART_REVIEW_VERSION = "60.0.0"
REVIEW_ROOT = ROOT / "out" / "dogfood-chart-reviews"
SENTINEL = ".dwm_dogfood_chart_review-owned.json"
FORBIDDEN_CLAIM_TERMS = [
    "beats codex",
    "beats claude",
    "better than codex",
    "better than claude",
    "state of the art",
    "sota",
    "industry leading",
    "external benchmark",
    "model superiority",
    "public benchmark",
]


class DogfoodChartReviewError(ValueError):
    """Structured V60 dogfood chart review failure."""

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
        raise DogfoodChartReviewError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise DogfoodChartReviewError(code, "path contains a symlink", path=current)


def resolve_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_DOGFOOD_CHART_REVIEW_PATH_UNSAFE", message="chart review output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = REVIEW_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise DogfoodChartReviewError("ERR_DOGFOOD_CHART_REVIEW_PATH_UNSAFE", f"chart review output must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise DogfoodChartReviewError("ERR_DOGFOOD_CHART_REVIEW_PATH_UNSAFE", "chart review output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_DOGFOOD_CHART_REVIEW_PATH_SYMLINK")
    return resolved


def resolve_candidate(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_DOGFOOD_CHART_REVIEW_CANDIDATE_INVALID", message="candidate path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = CHART_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise DogfoodChartReviewError("ERR_DOGFOOD_CHART_REVIEW_CANDIDATE_INVALID", f"candidate must resolve under {root_resolved}", path=value) from exc
    check_components_not_symlink(candidate, code="ERR_DOGFOOD_CHART_REVIEW_PATH_SYMLINK")
    return resolved


def safe_repo_file(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_DOGFOOD_CHART_REVIEW_RECEIPT_MISSING", message="review receipt path must not contain parent traversal")
    if raw.is_absolute():
        candidate = raw
    else:
        candidate = ROOT / raw
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(ROOT.resolve(strict=False))
    except ValueError as exc:
        raise DogfoodChartReviewError("ERR_DOGFOOD_CHART_REVIEW_RECEIPT_MISSING", "review receipt must stay in repo", path=value) from exc
    check_components_not_symlink(candidate, code="ERR_DOGFOOD_CHART_REVIEW_PATH_SYMLINK")
    if not candidate.is_file() or candidate.is_symlink():
        raise DogfoodChartReviewError("ERR_DOGFOOD_CHART_REVIEW_RECEIPT_MISSING", "review receipt is missing", path=value)
    return candidate


def read_sentinel(path: Path) -> dict[str, Any] | None:
    sentinel = path / SENTINEL
    if not sentinel.is_file() or sentinel.is_symlink():
        return None
    try:
        data = json.loads(sentinel.read_text())
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def prepare_out_dir(path: Path, review_id: str, *, source: Path) -> None:
    if path.exists():
        if path.is_symlink():
            raise DogfoodChartReviewError("ERR_DOGFOOD_CHART_REVIEW_PATH_SYMLINK", "chart review output is a symlink", path=path)
        if not path.is_dir():
            raise DogfoodChartReviewError("ERR_DOGFOOD_CHART_REVIEW_PATH_UNSAFE", "chart review output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("review_id") != review_id:
            raise DogfoodChartReviewError("ERR_DOGFOOD_CHART_REVIEW_PATH_UNSAFE", "existing chart review output is not review-owned", path=path)
        shutil.rmtree(path)
    REVIEW_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(
        path / SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "chart_review_version": CHART_REVIEW_VERSION,
            "review_id": review_id,
            "source_path": rel(source),
            "created_at": now_utc(),
        },
        root=path,
    )


def read_json_obj(path: Path, *, code: str, message: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise DogfoodChartReviewError(code, message, path=path)
    data = read_json(path)
    if not isinstance(data, dict):
        raise DogfoodChartReviewError(code, f"{path.name} must be a JSON object", path=path)
    return data


def load_candidate(candidate_dir: Path) -> dict[str, Any]:
    candidate_dir = resolve_candidate(candidate_dir)
    chart = read_json_obj(candidate_dir / "chart-candidate.json", code="ERR_DOGFOOD_CHART_REVIEW_CANDIDATE_MISSING", message="chart-candidate.json is missing")
    status = read_json_obj(candidate_dir / "status.json", code="ERR_DOGFOOD_CHART_REVIEW_CANDIDATE_MISSING", message="status.json is missing")
    if chart != status:
        raise DogfoodChartReviewError("ERR_DOGFOOD_CHART_REVIEW_STALE_CANDIDATE", "candidate status and artifact do not match", path=candidate_dir)
    if chart.get("status") != "dogfood-chart-candidate-recorded":
        raise DogfoodChartReviewError("ERR_DOGFOOD_CHART_REVIEW_STALE_CANDIDATE", "candidate is not recorded", path=candidate_dir)
    if chart.get("public_readme_ready") is True:
        raise DogfoodChartReviewError("ERR_DOGFOOD_CHART_REVIEW_OVERCLAIM", "candidate must not pre-claim public README readiness", path=candidate_dir)
    return chart


def detect_forbidden_claims(text: str) -> list[str]:
    normalized = " ".join(text.lower().split())
    return [term for term in FORBIDDEN_CLAIM_TERMS if term in normalized]


def validate_receipt(receipt: dict[str, Any], chart: dict[str, Any], *, receipt_path: Path) -> None:
    if receipt.get("approved") is not True:
        raise DogfoodChartReviewError("ERR_DOGFOOD_CHART_REVIEW_REJECTED", "review receipt is not approved", path=receipt_path)
    if receipt.get("chart_id") != chart.get("chart_id"):
        raise DogfoodChartReviewError("ERR_DOGFOOD_CHART_REVIEW_STALE_RECEIPT", "review receipt chart_id does not match candidate", path=receipt_path)
    expected_hash = canonical_hash(chart)
    source_hashes = receipt.get("source_hashes")
    if not isinstance(source_hashes, dict) or source_hashes.get("chart_candidate") != expected_hash:
        raise DogfoodChartReviewError("ERR_DOGFOOD_CHART_REVIEW_STALE_RECEIPT", "review receipt chart hash does not match candidate", path=receipt_path)
    if receipt.get("public_readme_ready") is True:
        raise DogfoodChartReviewError("ERR_DOGFOOD_CHART_REVIEW_OVERCLAIM", "review receipt must not approve public README readiness", path=receipt_path)
    claim_text = receipt.get("claim_text", "")
    if not isinstance(claim_text, str):
        raise DogfoodChartReviewError("ERR_DOGFOOD_CHART_REVIEW_OVERCLAIM", "claim_text must be a string", path=receipt_path)
    forbidden_terms = detect_forbidden_claims(claim_text)
    if forbidden_terms:
        raise DogfoodChartReviewError("ERR_DOGFOOD_CHART_REVIEW_OVERCLAIM", f"review receipt contains unsupported claims: {', '.join(forbidden_terms)}", path=receipt_path)


def render_review_doc(review: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# DWM Dogfood Chart Review",
            "",
            f"- review: `{review['review_id']}`",
            f"- chart: `{review['chart_id']}`",
            f"- status: `{review['status']}`",
            f"- decision: `{review['decision']}`",
            f"- pair count: `{review['pair_count']}`",
            f"- public README ready: `{review['public_readme_ready']}`",
            "- next step: render only in a later local artifact slice; do not publish README graph yet",
            "",
        ]
    )


def review_candidate(candidate_dir: Path, receipt_path: Path, out_dir: Path, *, review_id: str) -> dict[str, Any]:
    candidate_dir = resolve_candidate(candidate_dir)
    chart = load_candidate(candidate_dir)
    receipt_file = safe_repo_file(receipt_path)
    receipt = read_json_obj(receipt_file, code="ERR_DOGFOOD_CHART_REVIEW_RECEIPT_MISSING", message="review receipt is missing")
    validate_receipt(receipt, chart, receipt_path=receipt_file)
    prepare_out_dir(out_dir, review_id, source=receipt_file)
    review = {
        "tool": TOOL,
        "schema_version": SCHEMA_VERSION,
        "chart_review_version": CHART_REVIEW_VERSION,
        "status": "dogfood-chart-review-approved",
        "decision": "local-chart-review-approved",
        "review_id": review_id,
        "chart_id": chart["chart_id"],
        "candidate_path": rel(candidate_dir),
        "receipt_path": rel(receipt_file),
        "pair_count": chart["pair_count"],
        "public_readme_ready": False,
        "safe_next_step": "local render candidate may be generated, but README promotion still requires a later gate",
        "source_hashes": {
            "chart_candidate": canonical_hash(chart),
            "review_receipt": canonical_hash(receipt),
        },
    }
    write_json_atomic(out_dir / "chart-review.json", review, root=out_dir)
    write_json_atomic(out_dir / "status.json", review, root=out_dir)
    write_text_atomic(out_dir / "chart-review.md", render_review_doc(review), root=out_dir)
    return review


def make_candidate_dir(base_name: str, suite_dir: Path) -> Path:
    series_dir = make_series_dir(base_name, suite_dir, ready=True)
    candidate_dir = CHART_ROOT / suite_dir.name / f"{base_name}-candidate"
    create_candidate(series_dir, candidate_dir, chart_id=candidate_dir.name)
    return candidate_dir


def make_receipt(candidate_dir: Path, suite_dir: Path, fixture_id: str, *, approved: bool = True, stale: bool = False, overclaim: bool = False) -> Path:
    chart = load_candidate(candidate_dir)
    receipt = {
        "reviewer": "fixture-human-review",
        "approved": approved,
        "chart_id": chart["chart_id"],
        "public_readme_ready": False,
        "claim_text": "local chart candidate only; no public README benchmark graph promotion",
        "source_hashes": {
            "chart_candidate": canonical_hash(chart),
        },
    }
    if stale:
        receipt["source_hashes"]["chart_candidate"] = "stale"
    if overclaim:
        receipt["public_readme_ready"] = True
        receipt["claim_text"] = "public benchmark shows DWM beats Codex"
    receipt_path = suite_dir / f"{fixture_id}-receipt.json"
    write_json_atomic(receipt_path, receipt, root=suite_dir)
    return receipt_path


def blocked_fixture_status(kind: str, fixture: dict[str, Any], suite_dir: Path) -> dict[str, Any]:
    try:
        candidate_dir = make_candidate_dir(f"{suite_dir.name}-{kind}", suite_dir)
        if kind == "missing-receipt":
            receipt = suite_dir / "missing-receipt.json"
        elif kind == "rejected":
            receipt = make_receipt(candidate_dir, suite_dir, kind, approved=False)
        elif kind == "stale-receipt":
            receipt = make_receipt(candidate_dir, suite_dir, kind, stale=True)
        elif kind == "overclaim":
            receipt = make_receipt(candidate_dir, suite_dir, kind, overclaim=True)
        else:
            raise DogfoodChartReviewError("ERR_DOGFOOD_CHART_REVIEW_FIXTURE_FAILED", f"unknown blocked fixture kind: {kind}")
        review_candidate(candidate_dir, receipt, suite_dir / kind, review_id=kind)
    except DogfoodChartReviewError as exc:
        if fixture.get("expected_error") != exc.code:
            raise
        return {"status": "blocked", "error": exc.to_record()}
    raise DogfoodChartReviewError("ERR_DOGFOOD_CHART_REVIEW_FIXTURE_FAILED", f"{kind} unexpectedly passed")


def run_fixture(fixture: dict[str, Any], suite_dir: Path) -> dict[str, Any]:
    fixture_id = fixture["id"]
    try:
        kind = fixture["kind"]
        if kind == "review-approved":
            candidate_dir = make_candidate_dir(f"{suite_dir.name}-{fixture_id}", suite_dir)
            receipt = make_receipt(candidate_dir, suite_dir, fixture_id)
            status = review_candidate(candidate_dir, receipt, suite_dir / fixture_id, review_id=fixture_id)
        elif kind in {"missing-receipt", "rejected", "stale-receipt", "overclaim"}:
            status = blocked_fixture_status(kind, fixture, suite_dir)
        else:
            raise DogfoodChartReviewError("ERR_DOGFOOD_CHART_REVIEW_FIXTURE_FAILED", f"unknown fixture kind: {kind}")
        expected_status = fixture.get("expected_status")
        if expected_status is not None and status.get("status") != expected_status:
            raise DogfoodChartReviewError("ERR_DOGFOOD_CHART_REVIEW_FIXTURE_FAILED", f"expected status {expected_status}, got {status.get('status')}")
        expected_decision = fixture.get("expected_decision")
        if expected_decision is not None and status.get("decision") != expected_decision:
            raise DogfoodChartReviewError("ERR_DOGFOOD_CHART_REVIEW_FIXTURE_FAILED", f"expected decision {expected_decision}, got {status.get('decision')}")
        expected_error = fixture.get("expected_error")
        actual_error = status.get("error", {}).get("code") if isinstance(status.get("error"), dict) else None
        if expected_error is not None and actual_error != expected_error:
            raise DogfoodChartReviewError("ERR_DOGFOOD_CHART_REVIEW_FIXTURE_FAILED", f"expected error {expected_error}, got {actual_error}")
        return {"id": fixture_id, "status": "pass", "observed_status": status.get("status"), "required": fixture.get("required", True)}
    except DogfoodChartReviewError as exc:
        record = exc.to_record()
        record["fixture_id"] = fixture_id
        return {"id": fixture_id, "status": "fail", "required": fixture.get("required", True), "error": record}


def evaluate_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    suite_id = Path(out_dir).name
    suite_dir = resolve_out(out_dir)
    if suite_dir.exists():
        sentinel = read_sentinel(suite_dir)
        if sentinel is None or sentinel.get("review_id") != suite_id:
            raise DogfoodChartReviewError("ERR_DOGFOOD_CHART_REVIEW_PATH_UNSAFE", "existing chart review suite is not review-owned", path=suite_dir)
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
        raise DogfoodChartReviewError("ERR_DOGFOOD_CHART_REVIEW_FIXTURE_FAILED", "manifest decision is kill", path=manifest_path)
    return summary


def self_test() -> None:
    REVIEW_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dwm-dogfood-chart-review-self-test-", dir=REVIEW_ROOT) as tmp:
        summary = evaluate_manifest(ROOT / "fixtures" / "v60" / "manifest.json", Path(tmp) / "dogfood-chart-review-self-test")
    if summary["decision"] != "keep":
        raise DogfoodChartReviewError("ERR_DOGFOOD_CHART_REVIEW_FIXTURE_FAILED", "dogfood chart review self-test manifest did not keep")
    print("dwm_dogfood_chart_review self-test: pass")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", choices=["review"])
    parser.add_argument("--candidate")
    parser.add_argument("--manifest")
    parser.add_argument("--out")
    parser.add_argument("--receipt")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
        elif args.manifest:
            if not args.out:
                raise DogfoodChartReviewError("ERR_DOGFOOD_CHART_REVIEW_PATH_UNSAFE", "--manifest requires --out")
            summary = evaluate_manifest(Path(args.manifest), Path(args.out))
            print(canonical_json_text({key: summary[key] for key in ["suite_id", "fixture_count", "required_fixture_count", "required_passed", "passed", "failed", "skipped", "decision"]}))
        elif args.command == "review":
            if not args.candidate or not args.receipt or not args.out:
                raise DogfoodChartReviewError("ERR_DOGFOOD_CHART_REVIEW_PATH_UNSAFE", "review requires --candidate, --receipt, and --out")
            print(canonical_json_text(review_candidate(Path(args.candidate), Path(args.receipt), resolve_out(args.out), review_id=Path(args.out).name)))
        else:
            parser.error("expected --self-test, --manifest, or review")
    except DogfoodChartReviewError as exc:
        print(canonical_json_text(exc.to_record()), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
