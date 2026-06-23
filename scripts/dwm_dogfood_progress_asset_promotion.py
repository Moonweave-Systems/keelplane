#!/usr/bin/env python3
"""V67 README process-progress asset promotion bundle."""

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
from dwm_dogfood_progress import PROGRESS_ROOT, build_progress, make_fixture_roots  # noqa: E402


TOOL = "dwm_dogfood_progress_asset_promotion.py"
SCHEMA_VERSION = "1.0"
PROMOTION_VERSION = "67.0.0"
PROMOTION_ROOT = ROOT / "out" / "dogfood-progress-asset-promotions"
SENTINEL = ".dwm_dogfood_progress_asset_promotion-owned.json"
DEFAULT_ASSET_NAME = "dwm-dogfood-progress.svg"
DEFAULT_META_NAME = "dwm-dogfood-progress.json"
REQUIRED_PROCESS_TEXT = "Process completion, not upward performance claim"
REQUIRED_NON_BENCHMARK_TEXT = "not a public benchmark graph"
BLOCKED_TERMS = [
    "model superiority",
    "external benchmark",
    "public benchmark superiority",
    "beats claude",
    "beats codex",
]


class ProgressAssetPromotionError(ValueError):
    """Structured V67 process-progress asset promotion failure."""

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
        raise ProgressAssetPromotionError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise ProgressAssetPromotionError(code, "path contains a symlink", path=current)


def resolve_promotion_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_DOGFOOD_PROGRESS_ASSET_PROMOTION_PATH_UNSAFE", message="promotion output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = PROMOTION_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ProgressAssetPromotionError("ERR_DOGFOOD_PROGRESS_ASSET_PROMOTION_PATH_UNSAFE", f"promotion output must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise ProgressAssetPromotionError("ERR_DOGFOOD_PROGRESS_ASSET_PROMOTION_PATH_UNSAFE", "promotion output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_DOGFOOD_PROGRESS_ASSET_PROMOTION_PATH_SYMLINK")
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
            raise ProgressAssetPromotionError("ERR_DOGFOOD_PROGRESS_ASSET_PROMOTION_PATH_SYMLINK", "promotion output is a symlink", path=path)
        if not path.is_dir():
            raise ProgressAssetPromotionError("ERR_DOGFOOD_PROGRESS_ASSET_PROMOTION_PATH_UNSAFE", "promotion output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("promotion_id") != promotion_id:
            raise ProgressAssetPromotionError("ERR_DOGFOOD_PROGRESS_ASSET_PROMOTION_PATH_UNSAFE", "existing promotion output is not promotion-owned", path=path)
        shutil.rmtree(path)
    PROMOTION_ROOT.mkdir(parents=True, exist_ok=True)
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
        raise ProgressAssetPromotionError(code, message, path=path)
    data = read_json(path)
    if not isinstance(data, dict):
        raise ProgressAssetPromotionError(code, f"{path.name} is not an object", path=path)
    return data


def resolve_progress_dir(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_DOGFOOD_PROGRESS_ASSET_PROMOTION_PROGRESS_UNSAFE", message="progress path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(PROGRESS_ROOT.resolve(strict=False))
    except ValueError as exc:
        raise ProgressAssetPromotionError("ERR_DOGFOOD_PROGRESS_ASSET_PROMOTION_PROGRESS_UNSAFE", "progress path must resolve under out/dogfood-progress", path=value) from exc
    check_components_not_symlink(candidate, code="ERR_DOGFOOD_PROGRESS_ASSET_PROMOTION_PATH_SYMLINK")
    return resolved


def load_progress(progress_dir: Path) -> dict[str, Any]:
    progress = require_json(progress_dir / "dogfood-progress.json", code="ERR_DOGFOOD_PROGRESS_ASSET_PROMOTION_ARTIFACT_MISSING", message="dogfood-progress.json is missing")
    status = require_json(progress_dir / "status.json", code="ERR_DOGFOOD_PROGRESS_ASSET_PROMOTION_ARTIFACT_MISSING", message="status.json is missing")
    if progress != status:
        raise ProgressAssetPromotionError("ERR_DOGFOOD_PROGRESS_ASSET_PROMOTION_STALE_PROGRESS", "progress status and artifact do not match", path=progress_dir)
    if progress.get("status") != "dogfood-progress-recorded":
        raise ProgressAssetPromotionError("ERR_DOGFOOD_PROGRESS_ASSET_PROMOTION_PROGRESS_NOT_READY", "progress artifact is not recorded", path=progress_dir)
    if progress.get("decision") != "process-progress-recorded":
        raise ProgressAssetPromotionError("ERR_DOGFOOD_PROGRESS_ASSET_PROMOTION_PROGRESS_NOT_READY", "progress decision is not process-progress-recorded", path=progress_dir)
    return progress


def verify_progress(progress: dict[str, Any], progress_dir: Path) -> Path:
    stages = progress.get("stages")
    source_hashes = progress.get("source_hashes")
    if not isinstance(stages, list) or not isinstance(source_hashes, dict):
        raise ProgressAssetPromotionError("ERR_DOGFOOD_PROGRESS_ASSET_PROMOTION_HASH_MISMATCH", "progress source hashes are missing", path=progress_dir)
    if source_hashes.get("stages") != canonical_hash(stages):
        raise ProgressAssetPromotionError("ERR_DOGFOOD_PROGRESS_ASSET_PROMOTION_HASH_MISMATCH", "progress stage hash does not match", path=progress_dir)
    completed = progress.get("completed_stage_count")
    stage_count = progress.get("stage_count")
    if not isinstance(completed, int) or not isinstance(stage_count, int) or completed < 0 or stage_count < completed:
        raise ProgressAssetPromotionError("ERR_DOGFOOD_PROGRESS_ASSET_PROMOTION_PROGRESS_NOT_READY", "progress counts are invalid", path=progress_dir)
    svg_path_value = progress.get("svg_path")
    if not isinstance(svg_path_value, str) or not svg_path_value:
        raise ProgressAssetPromotionError("ERR_DOGFOOD_PROGRESS_ASSET_PROMOTION_ASSET_MISSING", "progress svg_path is missing", path=progress_dir)
    svg_path = ROOT / svg_path_value
    if svg_path.resolve(strict=False).parent != progress_dir.resolve(strict=False):
        raise ProgressAssetPromotionError("ERR_DOGFOOD_PROGRESS_ASSET_PROMOTION_ASSET_MISSING", "progress svg_path must point inside the progress directory", path=svg_path)
    if not svg_path.is_file() or svg_path.is_symlink():
        raise ProgressAssetPromotionError("ERR_DOGFOOD_PROGRESS_ASSET_PROMOTION_ASSET_MISSING", "dogfood-progress.svg is missing", path=progress_dir)
    svg_text = svg_path.read_text()
    if source_hashes.get("svg") != canonical_hash(svg_text):
        raise ProgressAssetPromotionError("ERR_DOGFOOD_PROGRESS_ASSET_PROMOTION_HASH_MISMATCH", "progress SVG hash does not match", path=svg_path)
    lower_svg = svg_text.lower()
    if REQUIRED_PROCESS_TEXT not in svg_text or REQUIRED_NON_BENCHMARK_TEXT not in svg_text:
        raise ProgressAssetPromotionError("ERR_DOGFOOD_PROGRESS_ASSET_PROMOTION_OVERCLAIM", "SVG is missing process/non-benchmark claim text", path=svg_path)
    if any(term in lower_svg for term in BLOCKED_TERMS):
        raise ProgressAssetPromotionError("ERR_DOGFOOD_PROGRESS_ASSET_PROMOTION_OVERCLAIM", "SVG contains blocked benchmark claim text", path=svg_path)
    return svg_path


def promote_progress(progress_dir: Path, out_dir: Path, *, promotion_id: str, asset_name: str = DEFAULT_ASSET_NAME, meta_name: str = DEFAULT_META_NAME) -> dict[str, Any]:
    progress_dir = resolve_progress_dir(progress_dir)
    progress = load_progress(progress_dir)
    source_svg = verify_progress(progress, progress_dir)
    out_dir = resolve_promotion_out(out_dir)
    prepare_out_dir(out_dir, promotion_id, source=progress_dir)
    promoted_svg = out_dir / asset_name
    shutil.copyfile(source_svg, promoted_svg)
    asset_hash = canonical_hash({"svg_sha256": promoted_svg.read_text()})
    metadata = {
        "status": "process-asset-promotion-ready",
        "promotion_id": promotion_id,
        "progress_path": rel(progress_dir),
        "source_svg": rel(source_svg),
        "proposed_asset": f"assets/{asset_name}",
        "proposed_metadata": f"assets/{meta_name}",
        "readme_embed": f"![DWM dogfood evidence progress](assets/{asset_name})",
        "claim_policy": "process progress only; not an upward benchmark claim",
        "benchmark_readme_ready": False,
        "process_readme_asset_ready": True,
        "source_hashes": {
            "progress": canonical_hash(progress),
            "asset": asset_hash,
            **progress.get("source_hashes", {}),
        },
    }
    write_json_atomic(out_dir / meta_name, metadata, root=out_dir)
    write_json_atomic(out_dir / "asset-promotion.json", metadata, root=out_dir)
    write_json_atomic(out_dir / "status.json", metadata, root=out_dir)
    (out_dir / "README-snippet.md").write_text(metadata["readme_embed"] + "\n")
    (out_dir / "asset-diff.md").write_text(
        "\n".join(
            [
                "# Dogfood Progress Asset Promotion Diff",
                "",
                f"- source progress: `{metadata['progress_path']}`",
                f"- source SVG: `{metadata['source_svg']}`",
                f"- proposed tracked SVG: `{metadata['proposed_asset']}`",
                f"- proposed metadata: `{metadata['proposed_metadata']}`",
                "- README change: add or replace the process-progress image after human review.",
                "- claim policy: process progress only; do not present it as an upward benchmark trend.",
                "",
            ]
        )
    )
    return metadata


def make_progress_dir(base_name: str, *, stale: bool = False, missing_svg: bool = False, hash_drift: bool = False, overclaim: bool = False, not_ready: bool = False) -> Path:
    progress_dir = PROGRESS_ROOT / f"{base_name}-progress-output"
    source_suite = PROGRESS_ROOT / f"{base_name}-progress-sources"
    build_progress(progress_dir, overrides=make_fixture_roots(source_suite, "full"))
    progress = read_json(progress_dir / "dogfood-progress.json")
    if stale:
        status = read_json(progress_dir / "status.json")
        status["completed_stage_count"] = 0
        write_json_atomic(progress_dir / "status.json", status, root=progress_dir)
    if missing_svg:
        (progress_dir / "dogfood-progress.svg").unlink(missing_ok=True)
    if hash_drift:
        progress["source_hashes"]["svg"] = "drifted"
        write_json_atomic(progress_dir / "dogfood-progress.json", progress, root=progress_dir)
        write_json_atomic(progress_dir / "status.json", progress, root=progress_dir)
    if overclaim:
        svg_path = progress_dir / "dogfood-progress.svg"
        svg_path.write_text(svg_path.read_text() + "\n<!-- external benchmark model superiority -->\n")
        progress["source_hashes"]["svg"] = canonical_hash(svg_path.read_text())
        write_json_atomic(progress_dir / "dogfood-progress.json", progress, root=progress_dir)
        write_json_atomic(progress_dir / "status.json", progress, root=progress_dir)
    if not_ready:
        progress["decision"] = "blocked"
        write_json_atomic(progress_dir / "dogfood-progress.json", progress, root=progress_dir)
        write_json_atomic(progress_dir / "status.json", progress, root=progress_dir)
    return progress_dir


def blocked_fixture_status(kind: str, fixture: dict[str, Any], suite_id: str) -> dict[str, Any]:
    try:
        if kind == "stale-progress":
            promote_progress(make_progress_dir(f"{suite_id}-stale", stale=True), PROMOTION_ROOT / f"{suite_id}-stale", promotion_id=f"{suite_id}-stale")
        elif kind == "missing-svg":
            promote_progress(make_progress_dir(f"{suite_id}-missing-svg", missing_svg=True), PROMOTION_ROOT / f"{suite_id}-missing-svg", promotion_id=f"{suite_id}-missing-svg")
        elif kind == "hash-drift":
            promote_progress(make_progress_dir(f"{suite_id}-hash-drift", hash_drift=True), PROMOTION_ROOT / f"{suite_id}-hash-drift", promotion_id=f"{suite_id}-hash-drift")
        elif kind == "overclaim":
            promote_progress(make_progress_dir(f"{suite_id}-overclaim", overclaim=True), PROMOTION_ROOT / f"{suite_id}-overclaim", promotion_id=f"{suite_id}-overclaim")
        elif kind == "not-ready":
            promote_progress(make_progress_dir(f"{suite_id}-not-ready", not_ready=True), PROMOTION_ROOT / f"{suite_id}-not-ready", promotion_id=f"{suite_id}-not-ready")
        else:
            raise ProgressAssetPromotionError("ERR_DOGFOOD_PROGRESS_ASSET_PROMOTION_FIXTURE_FAILED", f"unknown blocked fixture kind: {kind}")
    except ProgressAssetPromotionError as exc:
        if fixture.get("expected_error") != exc.code:
            raise
        return {"status": "blocked", "error": exc.to_record()}
    raise ProgressAssetPromotionError("ERR_DOGFOOD_PROGRESS_ASSET_PROMOTION_FIXTURE_FAILED", f"{kind} unexpectedly passed")


def run_fixture(fixture: dict[str, Any], suite_dir: Path) -> dict[str, Any]:
    fixture_id = fixture["id"]
    try:
        kind = fixture["kind"]
        if kind == "promotion-ready":
            status = promote_progress(make_progress_dir(f"{suite_dir.name}-{fixture_id}"), suite_dir / fixture_id, promotion_id=fixture_id)
        elif kind in {"stale-progress", "missing-svg", "hash-drift", "overclaim", "not-ready"}:
            status = blocked_fixture_status(kind, fixture, suite_dir.name)
        else:
            raise ProgressAssetPromotionError("ERR_DOGFOOD_PROGRESS_ASSET_PROMOTION_FIXTURE_FAILED", f"unknown fixture kind: {kind}")
        expected_status = fixture.get("expected_status")
        if expected_status is not None and status.get("status") != expected_status:
            raise ProgressAssetPromotionError("ERR_DOGFOOD_PROGRESS_ASSET_PROMOTION_FIXTURE_FAILED", f"expected status {expected_status}, got {status.get('status')}")
        expected_error = fixture.get("expected_error")
        actual_error = status.get("error", {}).get("code") if isinstance(status.get("error"), dict) else None
        if expected_error is not None and actual_error != expected_error:
            raise ProgressAssetPromotionError("ERR_DOGFOOD_PROGRESS_ASSET_PROMOTION_FIXTURE_FAILED", f"expected error {expected_error}, got {actual_error}")
        return {"id": fixture_id, "status": "pass", "observed_status": status.get("status"), "required": fixture.get("required", True)}
    except ProgressAssetPromotionError as exc:
        record = exc.to_record()
        record["fixture_id"] = fixture_id
        return {"id": fixture_id, "status": "fail", "required": fixture.get("required", True), "error": record}


def evaluate_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    suite_id = Path(out_dir).name
    suite_dir = resolve_promotion_out(out_dir)
    if suite_dir.exists():
        sentinel = read_sentinel(suite_dir)
        if sentinel is None or sentinel.get("promotion_id") != suite_id:
            raise ProgressAssetPromotionError("ERR_DOGFOOD_PROGRESS_ASSET_PROMOTION_PATH_UNSAFE", "existing promotion suite is not promotion-owned", path=suite_dir)
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
        raise ProgressAssetPromotionError("ERR_DOGFOOD_PROGRESS_ASSET_PROMOTION_FIXTURE_FAILED", "manifest decision is kill", path=manifest_path)
    return summary


def self_test() -> None:
    PROMOTION_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dwm-dogfood-progress-asset-promotion-self-test-", dir=PROMOTION_ROOT) as tmp:
        summary = evaluate_manifest(ROOT / "fixtures" / "v67" / "manifest.json", Path(tmp) / "asset-promotion-self-test")
    if summary["decision"] != "keep":
        raise ProgressAssetPromotionError("ERR_DOGFOOD_PROGRESS_ASSET_PROMOTION_FIXTURE_FAILED", "asset promotion self-test manifest did not keep")
    print("dwm_dogfood_progress_asset_promotion self-test: pass")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", choices=["promote"])
    parser.add_argument("--manifest")
    parser.add_argument("--out")
    parser.add_argument("--progress")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
        elif args.manifest:
            if not args.out:
                raise ProgressAssetPromotionError("ERR_DOGFOOD_PROGRESS_ASSET_PROMOTION_PATH_UNSAFE", "--manifest requires --out")
            summary = evaluate_manifest(Path(args.manifest), Path(args.out))
            print(canonical_json_text({key: summary[key] for key in ["suite_id", "fixture_count", "required_fixture_count", "required_passed", "passed", "failed", "skipped", "decision"]}))
        elif args.command == "promote":
            if not args.out or not args.progress:
                raise ProgressAssetPromotionError("ERR_DOGFOOD_PROGRESS_ASSET_PROMOTION_PATH_UNSAFE", "promote requires --progress and --out")
            status = promote_progress(Path(args.progress), Path(args.out), promotion_id=Path(args.out).name)
            print(canonical_json_text(status))
        else:
            parser.error("expected --self-test, --manifest, or promote")
    except ProgressAssetPromotionError as exc:
        print(canonical_json_text(exc.to_record()), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
