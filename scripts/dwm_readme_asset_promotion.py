#!/usr/bin/env python3
"""V45 README benchmark asset promotion bundle."""

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
from dwm_benchmark_candidate_review import REVIEW_ROOT, make_candidate_dir, review_candidate  # noqa: E402


TOOL = "dwm_readme_asset_promotion.py"
SCHEMA_VERSION = "1.0"
PROMOTION_VERSION = "45.0.0"
ASSET_PROMOTION_ROOT = ROOT / "out" / "readme-asset-promotions"
SENTINEL = ".dwm_readme_asset_promotion-owned.json"
DEFAULT_ASSET_NAME = "dwm-benchmark-trend.svg"
DEFAULT_META_NAME = "dwm-benchmark-trend.json"


class ReadmeAssetPromotionError(ValueError):
    """Structured V45 README asset promotion failure."""

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
        raise ReadmeAssetPromotionError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise ReadmeAssetPromotionError(code, "path contains a symlink", path=current)


def resolve_asset_promotion_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_README_ASSET_PROMOTION_PATH_UNSAFE", message="asset promotion output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = ASSET_PROMOTION_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ReadmeAssetPromotionError("ERR_README_ASSET_PROMOTION_PATH_UNSAFE", f"asset promotion output must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise ReadmeAssetPromotionError("ERR_README_ASSET_PROMOTION_PATH_UNSAFE", "asset promotion output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_README_ASSET_PROMOTION_PATH_SYMLINK")
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


def prepare_out_dir(path: Path, promotion_id: str, *, source: Path) -> None:
    if path.exists():
        if path.is_symlink():
            raise ReadmeAssetPromotionError("ERR_README_ASSET_PROMOTION_PATH_SYMLINK", "asset promotion output is a symlink", path=path)
        if not path.is_dir():
            raise ReadmeAssetPromotionError("ERR_README_ASSET_PROMOTION_PATH_UNSAFE", "asset promotion output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("promotion_id") != promotion_id:
            raise ReadmeAssetPromotionError("ERR_README_ASSET_PROMOTION_PATH_UNSAFE", "existing asset promotion output is not promotion-owned", path=path)
        shutil.rmtree(path)
    ASSET_PROMOTION_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(
        path / SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "promotion_version": PROMOTION_VERSION,
            "promotion_id": promotion_id,
            "source_path": rel(source),
            "created_at": now_utc(),
        },
        root=path,
    )


def require_json(path: Path, *, code: str, message: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise ReadmeAssetPromotionError(code, message, path=path)
    data = read_json(path)
    if not isinstance(data, dict):
        raise ReadmeAssetPromotionError(code, f"{path.name} is not an object", path=path)
    return data


def load_review(review_dir: Path) -> dict[str, Any]:
    review = require_json(review_dir / "candidate-review.json", code="ERR_README_ASSET_PROMOTION_ARTIFACT_MISSING", message="candidate-review.json is missing")
    status = require_json(review_dir / "status.json", code="ERR_README_ASSET_PROMOTION_ARTIFACT_MISSING", message="status.json is missing")
    if review != status:
        raise ReadmeAssetPromotionError("ERR_README_ASSET_PROMOTION_STALE_REVIEW", "review status and artifact do not match", path=review_dir)
    if review.get("status") != "review-approved":
        raise ReadmeAssetPromotionError("ERR_README_ASSET_PROMOTION_REVIEW_NOT_APPROVED", "review is not approved", path=review_dir)
    if review.get("blocked_claim_terms"):
        raise ReadmeAssetPromotionError("ERR_README_ASSET_PROMOTION_OVERCLAIM", "review contains blocked claim terms", path=review_dir)
    return review


def verify_review_sources(review: dict[str, Any], review_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    source_hashes = review.get("source_hashes")
    if not isinstance(source_hashes, dict):
        raise ReadmeAssetPromotionError("ERR_README_ASSET_PROMOTION_HASH_MISMATCH", "review source_hashes are missing", path=review_dir)
    candidate_path = review.get("candidate_path")
    promotion_path = review.get("promotion_path")
    if not isinstance(candidate_path, str) or not candidate_path:
        raise ReadmeAssetPromotionError("ERR_README_ASSET_PROMOTION_CANDIDATE_MISSING", "candidate_path is missing", path=review_dir)
    if not isinstance(promotion_path, str) or not promotion_path:
        raise ReadmeAssetPromotionError("ERR_README_ASSET_PROMOTION_PROMOTION_MISSING", "promotion_path is missing", path=review_dir)
    candidate = require_json(ROOT / candidate_path / "candidate.json", code="ERR_README_ASSET_PROMOTION_CANDIDATE_MISSING", message="candidate.json is missing")
    promotion = require_json(ROOT / promotion_path / "promotion.json", code="ERR_README_ASSET_PROMOTION_PROMOTION_MISSING", message="promotion.json is missing")
    expected_candidate = canonical_hash(candidate)
    expected_promotion = canonical_hash(promotion)
    if source_hashes.get("candidate") != expected_candidate or source_hashes.get("promotion") != expected_promotion:
        raise ReadmeAssetPromotionError("ERR_README_ASSET_PROMOTION_HASH_MISMATCH", "review source hashes no longer match candidate or promotion", path=review_dir)
    if candidate.get("readme_embed") != review.get("readme_embed") or promotion.get("readme_embed") != review.get("readme_embed"):
        raise ReadmeAssetPromotionError("ERR_README_ASSET_PROMOTION_HASH_MISMATCH", "review README embed no longer matches source artifacts", path=review_dir)
    return candidate, promotion


def source_svg_from_promotion(promotion: dict[str, Any], promotion_dir: Path) -> Path:
    readme_embed = promotion.get("readme_embed")
    if not isinstance(readme_embed, str) or "promoted-trend.svg" not in readme_embed:
        raise ReadmeAssetPromotionError("ERR_README_ASSET_PROMOTION_ASSET_MISSING", "promotion README embed does not name promoted-trend.svg", path=promotion_dir)
    source_svg = promotion_dir / "promoted-trend.svg"
    if not source_svg.is_file() or source_svg.is_symlink():
        raise ReadmeAssetPromotionError("ERR_README_ASSET_PROMOTION_ASSET_MISSING", "promoted-trend.svg is missing", path=promotion_dir)
    return source_svg


def promote_review(review_dir: Path, out_dir: Path, *, promotion_id: str, asset_name: str = DEFAULT_ASSET_NAME, meta_name: str = DEFAULT_META_NAME) -> dict[str, Any]:
    review = load_review(review_dir)
    _candidate, promotion = verify_review_sources(review, review_dir)
    promotion_dir = ROOT / str(review["promotion_path"])
    source_svg = source_svg_from_promotion(promotion, promotion_dir)
    prepare_out_dir(out_dir, promotion_id, source=review_dir)
    promoted_svg = out_dir / asset_name
    shutil.copyfile(source_svg, promoted_svg)
    asset_hash = canonical_hash({"svg_sha256": promoted_svg.read_text()})
    metadata = {
        "status": "asset-promotion-ready",
        "promotion_id": promotion_id,
        "review_path": rel(review_dir),
        "source_svg": rel(source_svg),
        "proposed_asset": f"assets/{asset_name}",
        "proposed_metadata": f"assets/{meta_name}",
        "readme_embed": f"![DWM benchmark history](assets/{asset_name})",
        "source_hashes": {
            "review": canonical_hash(review),
            "promotion": canonical_hash(promotion),
            "asset": asset_hash,
            **review.get("source_hashes", {}),
        },
    }
    write_json_atomic(out_dir / meta_name, metadata, root=out_dir)
    write_json_atomic(out_dir / "asset-promotion.json", metadata, root=out_dir)
    write_json_atomic(out_dir / "status.json", metadata, root=out_dir)
    (out_dir / "README-snippet.md").write_text(metadata["readme_embed"] + "\n")
    (out_dir / "asset-diff.md").write_text(
        "\n".join(
            [
                "# README Asset Promotion Diff",
                "",
                f"- source review: `{metadata['review_path']}`",
                f"- source SVG: `{metadata['source_svg']}`",
                f"- proposed tracked SVG: `{metadata['proposed_asset']}`",
                f"- proposed metadata: `{metadata['proposed_metadata']}`",
                "- README change: replace the benchmark history image with the generated README snippet after human review.",
                "- public claim policy: do not add external benchmark or model-superiority claims.",
                "",
            ]
        )
    )
    return metadata


def make_review_dir(base_name: str, *, stale: bool = False, missing_asset: bool = False, hash_drift: bool = False, not_approved: bool = False, overclaim: bool = False) -> Path:
    candidate_dir = make_candidate_dir(base_name)
    review_dir = REVIEW_ROOT / f"{base_name}-review"
    review_candidate(candidate_dir, review_dir, review_id=review_dir.name)
    review = read_json(review_dir / "candidate-review.json")
    if stale:
        status = read_json(review_dir / "status.json")
        status["release_ids"] = list(reversed(status["release_ids"]))
        write_json_atomic(review_dir / "status.json", status, root=review_dir)
    if missing_asset:
        source_svg = ROOT / str(review["promotion_path"]) / "promoted-trend.svg"
        source_svg.unlink(missing_ok=True)
    if hash_drift:
        review["source_hashes"]["promotion"] = "drifted"
        write_json_atomic(review_dir / "candidate-review.json", review, root=review_dir)
        write_json_atomic(review_dir / "status.json", review, root=review_dir)
    if not_approved:
        review["status"] = "blocked"
        write_json_atomic(review_dir / "candidate-review.json", review, root=review_dir)
        write_json_atomic(review_dir / "status.json", review, root=review_dir)
    if overclaim:
        review["blocked_claim_terms"] = ["external benchmark"]
        write_json_atomic(review_dir / "candidate-review.json", review, root=review_dir)
        write_json_atomic(review_dir / "status.json", review, root=review_dir)
    return review_dir


def blocked_fixture_status(kind: str, fixture: dict[str, Any], suite_id: str) -> dict[str, Any]:
    try:
        if kind == "stale-review":
            promote_review(make_review_dir(f"{suite_id}-stale", stale=True), ASSET_PROMOTION_ROOT / f"{suite_id}-stale", promotion_id=f"{suite_id}-stale")
        elif kind == "missing-asset":
            promote_review(make_review_dir(f"{suite_id}-missing-asset", missing_asset=True), ASSET_PROMOTION_ROOT / f"{suite_id}-missing-asset", promotion_id=f"{suite_id}-missing-asset")
        elif kind == "hash-drift":
            promote_review(make_review_dir(f"{suite_id}-hash-drift", hash_drift=True), ASSET_PROMOTION_ROOT / f"{suite_id}-hash-drift", promotion_id=f"{suite_id}-hash-drift")
        elif kind == "not-approved":
            promote_review(make_review_dir(f"{suite_id}-not-approved", not_approved=True), ASSET_PROMOTION_ROOT / f"{suite_id}-not-approved", promotion_id=f"{suite_id}-not-approved")
        elif kind == "overclaim":
            promote_review(make_review_dir(f"{suite_id}-overclaim", overclaim=True), ASSET_PROMOTION_ROOT / f"{suite_id}-overclaim", promotion_id=f"{suite_id}-overclaim")
        else:
            raise ReadmeAssetPromotionError("ERR_README_ASSET_PROMOTION_FIXTURE_FAILED", f"unknown blocked fixture kind: {kind}")
    except ReadmeAssetPromotionError as exc:
        if fixture.get("expected_error") != exc.code:
            raise
        return {"status": "blocked", "error": exc.to_record()}
    raise ReadmeAssetPromotionError("ERR_README_ASSET_PROMOTION_FIXTURE_FAILED", f"{kind} unexpectedly passed")


def run_fixture(fixture: dict[str, Any], suite_dir: Path) -> dict[str, Any]:
    fixture_id = fixture["id"]
    try:
        kind = fixture["kind"]
        if kind == "promotion-ready":
            status = promote_review(make_review_dir(f"{suite_dir.name}-{fixture_id}"), suite_dir / fixture_id, promotion_id=fixture_id)
        elif kind in {"stale-review", "missing-asset", "hash-drift", "not-approved", "overclaim"}:
            status = blocked_fixture_status(kind, fixture, suite_dir.name)
        else:
            raise ReadmeAssetPromotionError("ERR_README_ASSET_PROMOTION_FIXTURE_FAILED", f"unknown fixture kind: {kind}")
        expected_status = fixture.get("expected_status")
        if expected_status is not None and status.get("status") != expected_status:
            raise ReadmeAssetPromotionError("ERR_README_ASSET_PROMOTION_FIXTURE_FAILED", f"expected status {expected_status}, got {status.get('status')}")
        expected_error = fixture.get("expected_error")
        actual_error = status.get("error", {}).get("code") if isinstance(status.get("error"), dict) else None
        if expected_error is not None and actual_error != expected_error:
            raise ReadmeAssetPromotionError("ERR_README_ASSET_PROMOTION_FIXTURE_FAILED", f"expected error {expected_error}, got {actual_error}")
        return {"id": fixture_id, "status": "pass", "observed_status": status.get("status"), "required": fixture.get("required", True)}
    except ReadmeAssetPromotionError as exc:
        record = exc.to_record()
        record["fixture_id"] = fixture_id
        return {"id": fixture_id, "status": "fail", "required": fixture.get("required", True), "error": record}


def evaluate_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    suite_id = Path(out_dir).name
    suite_dir = resolve_asset_promotion_out(out_dir)
    if suite_dir.exists():
        sentinel = read_sentinel(suite_dir)
        if sentinel is None or sentinel.get("promotion_id") != suite_id:
            raise ReadmeAssetPromotionError("ERR_README_ASSET_PROMOTION_PATH_UNSAFE", "existing asset promotion suite is not promotion-owned", path=suite_dir)
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
        raise ReadmeAssetPromotionError("ERR_README_ASSET_PROMOTION_FIXTURE_FAILED", "manifest decision is kill", path=manifest_path)
    return summary


def self_test() -> None:
    ASSET_PROMOTION_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dwm-readme-asset-promotion-self-test-", dir=ASSET_PROMOTION_ROOT) as tmp:
        summary = evaluate_manifest(ROOT / "fixtures" / "v45" / "manifest.json", Path(tmp) / "asset-promotion-self-test")
    if summary["decision"] != "keep":
        raise ReadmeAssetPromotionError("ERR_README_ASSET_PROMOTION_FIXTURE_FAILED", "asset promotion self-test manifest did not keep")
    print("dwm_readme_asset_promotion self-test: pass")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", choices=["promote"])
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
                raise ReadmeAssetPromotionError("ERR_README_ASSET_PROMOTION_PATH_UNSAFE", "--manifest requires --out")
            summary = evaluate_manifest(Path(args.manifest), Path(args.out))
            print(canonical_json_text({key: summary[key] for key in ["suite_id", "fixture_count", "required_fixture_count", "required_passed", "passed", "failed", "skipped", "decision"]}))
        elif args.command == "promote":
            if not args.out or not args.review:
                raise ReadmeAssetPromotionError("ERR_README_ASSET_PROMOTION_PATH_UNSAFE", "promote requires --review and --out")
            status = promote_review(Path(args.review), resolve_asset_promotion_out(args.out), promotion_id=Path(args.out).name)
            print(canonical_json_text(status))
        else:
            parser.error("expected --self-test, --manifest, or promote")
    except ReadmeAssetPromotionError as exc:
        print(canonical_json_text(exc.to_record()), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
