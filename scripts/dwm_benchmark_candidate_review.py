#!/usr/bin/env python3
"""V44 benchmark candidate review gate."""

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
from dwm_benchmark_candidate import CANDIDATE_ROOT, make_candidate, make_series_dir  # noqa: E402


TOOL = "dwm_benchmark_candidate_review.py"
SCHEMA_VERSION = "1.0"
REVIEW_VERSION = "44.0.0"
REVIEW_ROOT = ROOT / "out" / "benchmark-candidate-reviews"
SENTINEL = ".dwm_benchmark_candidate_review-owned.json"
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
]


class BenchmarkCandidateReviewError(ValueError):
    """Structured V44 candidate review failure."""

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
        raise BenchmarkCandidateReviewError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise BenchmarkCandidateReviewError(code, "path contains a symlink", path=current)


def resolve_review_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_BENCHMARK_CANDIDATE_REVIEW_PATH_UNSAFE", message="candidate review output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = REVIEW_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise BenchmarkCandidateReviewError("ERR_BENCHMARK_CANDIDATE_REVIEW_PATH_UNSAFE", f"candidate review output must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise BenchmarkCandidateReviewError("ERR_BENCHMARK_CANDIDATE_REVIEW_PATH_UNSAFE", "candidate review output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_BENCHMARK_CANDIDATE_REVIEW_PATH_SYMLINK")
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


def prepare_out_dir(path: Path, review_id: str, *, source: Path) -> None:
    if path.exists():
        if path.is_symlink():
            raise BenchmarkCandidateReviewError("ERR_BENCHMARK_CANDIDATE_REVIEW_PATH_SYMLINK", "candidate review output is a symlink", path=path)
        if not path.is_dir():
            raise BenchmarkCandidateReviewError("ERR_BENCHMARK_CANDIDATE_REVIEW_PATH_UNSAFE", "candidate review output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("review_id") != review_id:
            raise BenchmarkCandidateReviewError("ERR_BENCHMARK_CANDIDATE_REVIEW_PATH_UNSAFE", "existing candidate review output is not review-owned", path=path)
        shutil.rmtree(path)
    REVIEW_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(
        path / SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "review_version": REVIEW_VERSION,
            "review_id": review_id,
            "source_path": rel(source),
            "created_at": now_utc(),
        },
        root=path,
    )


def require_json(path: Path, *, code: str, message: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise BenchmarkCandidateReviewError(code, message, path=path)
    data = read_json(path)
    if not isinstance(data, dict):
        raise BenchmarkCandidateReviewError(code, f"{path.name} is not an object", path=path)
    return data


def load_candidate(candidate_dir: Path) -> dict[str, Any]:
    candidate = require_json(candidate_dir / "candidate.json", code="ERR_BENCHMARK_CANDIDATE_REVIEW_ARTIFACT_MISSING", message="candidate.json is missing")
    status = require_json(candidate_dir / "status.json", code="ERR_BENCHMARK_CANDIDATE_REVIEW_ARTIFACT_MISSING", message="status.json is missing")
    if candidate != status:
        raise BenchmarkCandidateReviewError("ERR_BENCHMARK_CANDIDATE_REVIEW_STALE_CANDIDATE", "candidate status and artifact do not match", path=candidate_dir)
    if candidate.get("status") != "candidate-ready":
        raise BenchmarkCandidateReviewError("ERR_BENCHMARK_CANDIDATE_REVIEW_STALE_CANDIDATE", "candidate is not ready", path=candidate_dir)
    return candidate


def load_linked_json(record: dict[str, Any], key: str, filename: str, code: str, candidate_dir: Path) -> tuple[Path, dict[str, Any]]:
    value = record.get(key)
    if not isinstance(value, str) or not value:
        raise BenchmarkCandidateReviewError(code, f"{key} is missing", path=candidate_dir)
    artifact_dir = ROOT / value
    return artifact_dir, require_json(artifact_dir / filename, code=code, message=f"{filename} is missing")


def detect_forbidden_claims(text: str) -> list[str]:
    normalized = " ".join(text.lower().split())
    return [term for term in FORBIDDEN_CLAIM_TERMS if term in normalized]


def verify_hashes(candidate: dict[str, Any], candidate_dir: Path) -> dict[str, str]:
    source_hashes = candidate.get("source_hashes")
    if not isinstance(source_hashes, dict):
        raise BenchmarkCandidateReviewError("ERR_BENCHMARK_CANDIDATE_REVIEW_HASH_MISMATCH", "candidate source_hashes are missing", path=candidate_dir)
    promotion_dir, promotion = load_linked_json(candidate, "promotion_path", "promotion.json", "ERR_BENCHMARK_CANDIDATE_REVIEW_PROMOTION_MISSING", candidate_dir)
    _, series = load_linked_json(candidate, "series_path", "series.json", "ERR_BENCHMARK_CANDIDATE_REVIEW_SERIES_MISSING", candidate_dir)
    _, history = load_linked_json(candidate, "history_path", "history.json", "ERR_BENCHMARK_CANDIDATE_REVIEW_HISTORY_MISSING", candidate_dir)
    expected = {
        "candidate": canonical_hash(candidate),
        "promotion": canonical_hash(promotion),
        "series": canonical_hash(series),
        "history": canonical_hash(history),
    }
    for key in ["promotion", "series", "history"]:
        if source_hashes.get(key) != expected[key]:
            raise BenchmarkCandidateReviewError("ERR_BENCHMARK_CANDIDATE_REVIEW_HASH_MISMATCH", f"{key} hash does not match candidate source_hashes", path=candidate_dir)
    if promotion.get("status") != "promotion-ready":
        raise BenchmarkCandidateReviewError("ERR_BENCHMARK_CANDIDATE_REVIEW_PROMOTION_MISSING", "promotion is not ready", path=promotion_dir)
    if series.get("status") != "series-recorded":
        raise BenchmarkCandidateReviewError("ERR_BENCHMARK_CANDIDATE_REVIEW_SERIES_MISSING", "series is not recorded", path=candidate_dir)
    if history.get("status") != "history-recorded":
        raise BenchmarkCandidateReviewError("ERR_BENCHMARK_CANDIDATE_REVIEW_HISTORY_MISSING", "history is not recorded", path=candidate_dir)
    if promotion.get("readme_embed") != candidate.get("readme_embed"):
        raise BenchmarkCandidateReviewError("ERR_BENCHMARK_CANDIDATE_REVIEW_HASH_MISMATCH", "candidate README embed does not match promotion", path=candidate_dir)
    return expected


def review_candidate(candidate_dir: Path, out_dir: Path, *, review_id: str, proposed_readme: str = "") -> dict[str, Any]:
    candidate = load_candidate(candidate_dir)
    hashes = verify_hashes(candidate, candidate_dir)
    proposed_text = proposed_readme or candidate.get("readme_embed", "")
    if not isinstance(proposed_text, str):
        raise BenchmarkCandidateReviewError("ERR_BENCHMARK_CANDIDATE_REVIEW_OVERCLAIM", "proposed README text must be a string", path=candidate_dir)
    forbidden_terms = detect_forbidden_claims(proposed_text)
    if forbidden_terms:
        raise BenchmarkCandidateReviewError("ERR_BENCHMARK_CANDIDATE_REVIEW_OVERCLAIM", f"proposed README text contains unsupported claims: {', '.join(forbidden_terms)}", path=candidate_dir)
    prepare_out_dir(out_dir, review_id, source=candidate_dir)
    checklist = [
        f"candidate status: {candidate['status']}",
        "review status: approved",
        f"series path: {candidate['series_path']}",
        f"promotion path: {candidate['promotion_path']}",
        f"history path: {candidate['history_path']}",
        f"release ids: {', '.join(candidate.get('release_ids', []))}",
        f"candidate hash: {hashes['candidate']}",
        f"promotion hash: {hashes['promotion']}",
        "external benchmark or model superiority claims: blocked",
        "tracked README asset changes: require V45 promotion gate",
    ]
    review = {
        "status": "review-approved",
        "review_id": review_id,
        "candidate_path": rel(candidate_dir),
        "promotion_path": candidate["promotion_path"],
        "series_path": candidate["series_path"],
        "history_path": candidate["history_path"],
        "release_ids": candidate.get("release_ids", []),
        "readme_embed": candidate["readme_embed"],
        "publish_checklist": checklist,
        "blocked_claim_terms": forbidden_terms,
        "source_hashes": hashes,
        "safe_next_step": "V45 README asset promotion may consume this review, but must not make external benchmark claims.",
    }
    write_json_atomic(out_dir / "candidate-review.json", review, root=out_dir)
    write_json_atomic(out_dir / "status.json", review, root=out_dir)
    (out_dir / "publish-checklist.md").write_text("\n".join(f"- {item}" for item in checklist) + "\n")
    return review


def make_candidate_dir(base_name: str, *, stale: bool = False, missing_promotion: bool = False, hash_drift: bool = False) -> Path:
    series_dir = make_series_dir(base_name, scores=[False, False, True])
    candidate_dir = CANDIDATE_ROOT / f"{base_name}-candidate"
    make_candidate(series_dir, candidate_dir, candidate_id=candidate_dir.name)
    if stale:
        status = read_json(candidate_dir / "status.json")
        status["release_ids"] = list(reversed(status["release_ids"]))
        write_json_atomic(candidate_dir / "status.json", status, root=candidate_dir)
    if missing_promotion:
        candidate = read_json(candidate_dir / "candidate.json")
        shutil.rmtree(ROOT / str(candidate["promotion_path"]), ignore_errors=True)
    if hash_drift:
        candidate = read_json(candidate_dir / "candidate.json")
        candidate["source_hashes"]["promotion"] = "drifted"
        write_json_atomic(candidate_dir / "candidate.json", candidate, root=candidate_dir)
        write_json_atomic(candidate_dir / "status.json", candidate, root=candidate_dir)
    return candidate_dir


def blocked_fixture_status(kind: str, fixture: dict[str, Any], suite_id: str) -> dict[str, Any]:
    try:
        if kind == "stale-candidate":
            review_candidate(make_candidate_dir(f"{suite_id}-stale", stale=True), REVIEW_ROOT / f"{suite_id}-stale", review_id=f"{suite_id}-stale")
        elif kind == "missing-promotion":
            review_candidate(make_candidate_dir(f"{suite_id}-missing-promotion", missing_promotion=True), REVIEW_ROOT / f"{suite_id}-missing-promotion", review_id=f"{suite_id}-missing-promotion")
        elif kind == "hash-drift":
            review_candidate(make_candidate_dir(f"{suite_id}-hash-drift", hash_drift=True), REVIEW_ROOT / f"{suite_id}-hash-drift", review_id=f"{suite_id}-hash-drift")
        elif kind == "overclaim":
            review_candidate(make_candidate_dir(f"{suite_id}-overclaim"), REVIEW_ROOT / f"{suite_id}-overclaim", review_id=f"{suite_id}-overclaim", proposed_readme="DWM beats Codex on an external benchmark.")
        else:
            raise BenchmarkCandidateReviewError("ERR_BENCHMARK_CANDIDATE_REVIEW_FIXTURE_FAILED", f"unknown blocked fixture kind: {kind}")
    except BenchmarkCandidateReviewError as exc:
        if fixture.get("expected_error") != exc.code:
            raise
        return {"status": "blocked", "error": exc.to_record()}
    raise BenchmarkCandidateReviewError("ERR_BENCHMARK_CANDIDATE_REVIEW_FIXTURE_FAILED", f"{kind} unexpectedly passed")


def run_fixture(fixture: dict[str, Any], suite_dir: Path) -> dict[str, Any]:
    fixture_id = fixture["id"]
    try:
        kind = fixture["kind"]
        if kind == "review-ready":
            status = review_candidate(make_candidate_dir(f"{suite_dir.name}-{fixture_id}"), suite_dir / fixture_id, review_id=fixture_id)
        elif kind in {"stale-candidate", "missing-promotion", "hash-drift", "overclaim"}:
            status = blocked_fixture_status(kind, fixture, suite_dir.name)
        else:
            raise BenchmarkCandidateReviewError("ERR_BENCHMARK_CANDIDATE_REVIEW_FIXTURE_FAILED", f"unknown fixture kind: {kind}")
        expected_status = fixture.get("expected_status")
        if expected_status is not None and status.get("status") != expected_status:
            raise BenchmarkCandidateReviewError("ERR_BENCHMARK_CANDIDATE_REVIEW_FIXTURE_FAILED", f"expected status {expected_status}, got {status.get('status')}")
        expected_error = fixture.get("expected_error")
        actual_error = status.get("error", {}).get("code") if isinstance(status.get("error"), dict) else None
        if expected_error is not None and actual_error != expected_error:
            raise BenchmarkCandidateReviewError("ERR_BENCHMARK_CANDIDATE_REVIEW_FIXTURE_FAILED", f"expected error {expected_error}, got {actual_error}")
        return {"id": fixture_id, "status": "pass", "observed_status": status.get("status"), "required": fixture.get("required", True)}
    except BenchmarkCandidateReviewError as exc:
        record = exc.to_record()
        record["fixture_id"] = fixture_id
        return {"id": fixture_id, "status": "fail", "required": fixture.get("required", True), "error": record}


def evaluate_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    suite_id = Path(out_dir).name
    suite_dir = resolve_review_out(out_dir)
    if suite_dir.exists():
        sentinel = read_sentinel(suite_dir)
        if sentinel is None or sentinel.get("review_id") != suite_id:
            raise BenchmarkCandidateReviewError("ERR_BENCHMARK_CANDIDATE_REVIEW_PATH_UNSAFE", "existing candidate review suite is not review-owned", path=suite_dir)
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
        raise BenchmarkCandidateReviewError("ERR_BENCHMARK_CANDIDATE_REVIEW_FIXTURE_FAILED", "manifest decision is kill", path=manifest_path)
    return summary


def self_test() -> None:
    REVIEW_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dwm-benchmark-candidate-review-self-test-", dir=REVIEW_ROOT) as tmp:
        summary = evaluate_manifest(ROOT / "fixtures" / "v44" / "manifest.json", Path(tmp) / "candidate-review-self-test")
    if summary["decision"] != "keep":
        raise BenchmarkCandidateReviewError("ERR_BENCHMARK_CANDIDATE_REVIEW_FIXTURE_FAILED", "candidate review self-test manifest did not keep")
    print("dwm_benchmark_candidate_review self-test: pass")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", choices=["review"])
    parser.add_argument("--candidate")
    parser.add_argument("--manifest")
    parser.add_argument("--out")
    parser.add_argument("--proposed-readme")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
        elif args.manifest:
            if not args.out:
                raise BenchmarkCandidateReviewError("ERR_BENCHMARK_CANDIDATE_REVIEW_PATH_UNSAFE", "--manifest requires --out")
            summary = evaluate_manifest(Path(args.manifest), Path(args.out))
            print(canonical_json_text({key: summary[key] for key in ["suite_id", "fixture_count", "required_fixture_count", "required_passed", "passed", "failed", "skipped", "decision"]}))
        elif args.command == "review":
            if not args.out or not args.candidate:
                raise BenchmarkCandidateReviewError("ERR_BENCHMARK_CANDIDATE_REVIEW_PATH_UNSAFE", "review requires --candidate and --out")
            proposed_readme = Path(args.proposed_readme).read_text() if args.proposed_readme else ""
            status = review_candidate(Path(args.candidate), resolve_review_out(args.out), review_id=Path(args.out).name, proposed_readme=proposed_readme)
            print(canonical_json_text(status))
        else:
            parser.error("expected --self-test, --manifest, or review")
    except BenchmarkCandidateReviewError as exc:
        print(canonical_json_text(exc.to_record()), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
