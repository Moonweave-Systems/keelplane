#!/usr/bin/env python3
"""V64 dogfood clean pair-root selector."""

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
from dwm_dogfood_pair import PAIR_ROOT  # noqa: E402
from dwm_dogfood_pair_series import PAIR_SERIES_ROOT, build_series, pair_dirs_from_root  # noqa: E402


TOOL = "dwm_dogfood_pair_select.py"
SCHEMA_VERSION = "1.0"
SELECT_VERSION = "64.0.0"
SELECT_ROOT = ROOT / "out" / "dogfood-pair-selections"
SENTINEL = ".dwm_dogfood_pair_select-owned.json"
CLEAN_SENTINEL = ".dwm_dogfood_pair_select-clean-owned.json"


class DogfoodPairSelectError(ValueError):
    """Structured V64 dogfood pair selection failure."""

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
        raise DogfoodPairSelectError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise DogfoodPairSelectError(code, "path contains a symlink", path=current)


def resolve_under(value: str | Path, root: Path, *, code: str, label: str) -> Path:
    raw = Path(value)
    reject_traversal(raw, code=code, message=f"{label} path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = root.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise DogfoodPairSelectError(code, f"{label} must resolve under {root_resolved}", path=value) from exc
    check_components_not_symlink(candidate, code="ERR_DOGFOOD_PAIR_SELECT_PATH_SYMLINK")
    return resolved


def resolve_out(value: str | Path) -> Path:
    path = resolve_under(value, SELECT_ROOT, code="ERR_DOGFOOD_PAIR_SELECT_PATH_UNSAFE", label="pair selection output")
    if path == SELECT_ROOT.resolve(strict=False):
        raise DogfoodPairSelectError("ERR_DOGFOOD_PAIR_SELECT_PATH_UNSAFE", "pair selection output must name a directory", path=value)
    return path


def resolve_pair_root(value: str | Path) -> Path:
    return resolve_under(value, PAIR_ROOT, code="ERR_DOGFOOD_PAIR_SELECT_PAIR_ROOT_INVALID", label="pair root")


def read_sentinel(path: Path, sentinel_name: str = SENTINEL) -> dict[str, Any] | None:
    sentinel = path / sentinel_name
    if not sentinel.is_file() or sentinel.is_symlink():
        return None
    try:
        data = json.loads(sentinel.read_text())
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def prepare_out_dir(path: Path, selection_id: str, *, source: Path) -> None:
    if path.exists():
        if path.is_symlink():
            raise DogfoodPairSelectError("ERR_DOGFOOD_PAIR_SELECT_PATH_SYMLINK", "pair selection output is a symlink", path=path)
        if not path.is_dir():
            raise DogfoodPairSelectError("ERR_DOGFOOD_PAIR_SELECT_PATH_UNSAFE", "pair selection output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("selection_id") != selection_id:
            raise DogfoodPairSelectError("ERR_DOGFOOD_PAIR_SELECT_PATH_UNSAFE", "existing pair selection output is not selection-owned", path=path)
        shutil.rmtree(path)
    SELECT_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(
        path / SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "select_version": SELECT_VERSION,
            "selection_id": selection_id,
            "source_path": rel(source),
            "created_at": now_utc(),
        },
        root=path,
    )


def prepare_clean_root(path: Path, selection_id: str, *, source: Path) -> None:
    path = resolve_pair_root(path)
    if path.exists():
        if path.is_symlink():
            raise DogfoodPairSelectError("ERR_DOGFOOD_PAIR_SELECT_PATH_SYMLINK", "clean pair root is a symlink", path=path)
        if not path.is_dir():
            raise DogfoodPairSelectError("ERR_DOGFOOD_PAIR_SELECT_PAIR_ROOT_INVALID", "clean pair root is not a directory", path=path)
        sentinel = read_sentinel(path, CLEAN_SENTINEL)
        if sentinel is None or sentinel.get("selection_id") != selection_id:
            raise DogfoodPairSelectError("ERR_DOGFOOD_PAIR_SELECT_CLEAN_ROOT_UNSAFE", "existing clean pair root is not selection-owned", path=path)
        shutil.rmtree(path)
    path.mkdir(parents=True)
    write_json_atomic(
        path / CLEAN_SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "select_version": SELECT_VERSION,
            "selection_id": selection_id,
            "source_path": rel(source),
            "created_at": now_utc(),
        },
        root=path,
    )


def selection_slug(out_dir: Path, selection_id: str) -> str:
    try:
        return "__".join(out_dir.relative_to(SELECT_ROOT).parts)
    except ValueError:
        return selection_id


def load_pair(pair_dir: Path) -> dict[str, Any]:
    pair_path = pair_dir / "comparison-pair.json"
    status_path = pair_dir / "pair-status.json"
    if not pair_path.is_file() or pair_path.is_symlink() or not status_path.is_file() or status_path.is_symlink():
        raise DogfoodPairSelectError("ERR_DOGFOOD_PAIR_SELECT_STALE_PAIR", "pair artifacts are missing", path=pair_dir)
    pair = read_json(pair_path)
    status = read_json(status_path)
    if pair != status:
        raise DogfoodPairSelectError("ERR_DOGFOOD_PAIR_SELECT_STALE_PAIR", "pair artifact and status differ", path=pair_dir)
    if pair.get("status") != "dogfood-comparison-pair-recorded":
        raise DogfoodPairSelectError("ERR_DOGFOOD_PAIR_SELECT_STALE_PAIR", "pair is not recorded", path=pair_dir)
    task_id = pair.get("task_id")
    if not isinstance(task_id, str) or not task_id:
        raise DogfoodPairSelectError("ERR_DOGFOOD_PAIR_SELECT_STALE_PAIR", "pair task_id is missing", path=pair_dir)
    return pair


def candidate_pair_dirs(pair_root: Path) -> list[Path]:
    pair_root = resolve_pair_root(pair_root)
    if not pair_root.is_dir() or pair_root.is_symlink():
        raise DogfoodPairSelectError("ERR_DOGFOOD_PAIR_SELECT_PAIR_ROOT_INVALID", "pair root is not a directory", path=pair_root)
    return [
        path
        for path in sorted(pair_root.iterdir())
        if path.is_dir() and not path.is_symlink() and not path.name.startswith(".") and (path / "comparison-pair.json").is_file()
    ]


def select_pairs(pair_root: Path, *, policy: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if policy != "lexicographic-last":
        raise DogfoodPairSelectError("ERR_DOGFOOD_PAIR_SELECT_POLICY_UNSUPPORTED", "only lexicographic-last selection is supported", path=policy)
    grouped: dict[str, list[tuple[Path, dict[str, Any]]]] = {}
    for pair_dir in candidate_pair_dirs(pair_root):
        pair = load_pair(pair_dir)
        grouped.setdefault(pair["task_id"], []).append((pair_dir, pair))
    if not grouped:
        raise DogfoodPairSelectError("ERR_DOGFOOD_PAIR_SELECT_INSUFFICIENT_PAIRS", "no comparison pairs found", path=pair_root)
    selected = []
    rejected = []
    for task_id in sorted(grouped):
        candidates = sorted(grouped[task_id], key=lambda item: item[0].name)
        selected_dir, selected_pair = candidates[-1]
        selected.append(
            {
                "task_id": task_id,
                "pair_path": rel(selected_dir),
                "pair_dir_name": selected_dir.name,
                "source_hash": canonical_hash(selected_pair),
            }
        )
        for rejected_dir, rejected_pair in candidates[:-1]:
            rejected.append(
                {
                    "task_id": task_id,
                    "pair_path": rel(rejected_dir),
                    "pair_dir_name": rejected_dir.name,
                    "source_hash": canonical_hash(rejected_pair),
                    "reason": "duplicate-task-lower-lexicographic-name",
                }
            )
    return selected, rejected


def render_selection(record: dict[str, Any]) -> str:
    lines = [
        "# DWM Dogfood Pair Selection",
        "",
        f"- selection: `{record['selection_id']}`",
        f"- decision: `{record['decision']}`",
        f"- clean pair root: `{record['clean_pair_root']}`",
        f"- selected pairs: `{record['selected_pair_count']}`",
        f"- rejected duplicates: `{len(record['rejected_pairs'])}`",
        f"- series graph ready: `{record.get('series_graph_ready')}`",
        "- claim policy: local pair selection only; no public benchmark promotion",
        "",
    ]
    for item in record["selected_pairs"]:
        lines.append(f"- selected `{item['task_id']}` from `{item['pair_path']}`")
    lines.append("")
    return "\n".join(lines)


def select_clean_root(
    out_dir: Path,
    *,
    pair_root: Path,
    clean_pair_root: Path | None,
    min_pairs: int,
    policy: str,
) -> dict[str, Any]:
    if min_pairs < 1:
        raise DogfoodPairSelectError("ERR_DOGFOOD_PAIR_SELECT_MIN_PAIRS_INVALID", "min_pairs must be positive")
    out_dir = resolve_out(out_dir)
    selection_id = out_dir.name
    slug = selection_slug(out_dir, selection_id)
    source_pair_root = resolve_pair_root(pair_root)
    clean_root = clean_pair_root or (PAIR_ROOT / f"{slug}-clean")
    clean_root = resolve_pair_root(clean_root)
    if clean_root == source_pair_root:
        raise DogfoodPairSelectError("ERR_DOGFOOD_PAIR_SELECT_CLEAN_ROOT_UNSAFE", "clean pair root must differ from source pair root", path=clean_root)
    selected, rejected = select_pairs(source_pair_root, policy=policy)
    prepare_out_dir(out_dir, selection_id, source=source_pair_root)
    prepare_clean_root(clean_root, selection_id, source=source_pair_root)
    copied_dirs = []
    for item in selected:
        source_dir = ROOT / item["pair_path"]
        target_dir = clean_root / item["pair_dir_name"]
        shutil.copytree(source_dir, target_dir)
        copied_dirs.append(target_dir)
    series_dir = PAIR_SERIES_ROOT / f"{slug}-series"
    series = build_series(pair_dirs_from_root(clean_root), series_dir, series_id=series_dir.name, min_pairs=min_pairs, source=clean_root)
    record = {
        "tool": TOOL,
        "schema_version": SCHEMA_VERSION,
        "select_version": SELECT_VERSION,
        "status": "dogfood-pair-selection-recorded",
        "decision": "clean-pair-root-ready" if series["graph_readiness"]["graph_ready"] else "clean-pair-root-blocked",
        "selection_id": selection_id,
        "policy": policy,
        "source_pair_root": rel(source_pair_root),
        "clean_pair_root": rel(clean_root),
        "series_path": rel(series_dir),
        "series_graph_ready": series["graph_readiness"]["graph_ready"],
        "series_blocked_by": series["graph_readiness"]["blocked_by"],
        "selected_pair_count": len(selected),
        "selected_pairs": selected,
        "rejected_pairs": rejected,
        "public_readme_ready": False,
        "source_hashes": {
            "selected_pairs": canonical_hash(selected),
            "rejected_pairs": canonical_hash(rejected),
            "series": canonical_hash(series),
        },
    }
    write_json_atomic(out_dir / "pair-selection.json", record, root=out_dir)
    write_json_atomic(out_dir / "status.json", record, root=out_dir)
    write_text_atomic(out_dir / "pair-selection.md", render_selection(record), root=out_dir)
    return record


def make_pair(pair_root: Path, pair_id: str, task_id: str) -> Path:
    pair_dir = pair_root / pair_id
    pair_dir.mkdir(parents=True, exist_ok=True)
    pair = {
        "status": "dogfood-comparison-pair-recorded",
        "pair_id": pair_id,
        "task_id": task_id,
        "public_graph_ready": False,
        "dwm_controlled": {"metrics": {"verification_passed": True, "elapsed_seconds": 1.0, "interruptions": 0}},
        "direct_codex": {"metrics": {"verification_passed": True, "elapsed_seconds": 2.0, "interruptions": 0}},
    }
    write_json_atomic(pair_dir / "comparison-pair.json", pair, root=pair_dir)
    write_json_atomic(pair_dir / "pair-status.json", pair, root=pair_dir)
    return pair_dir


def blocked_fixture_status(kind: str, fixture: dict[str, Any], suite_dir: Path) -> dict[str, Any]:
    try:
        if kind == "stale-pair":
            pair_root = PAIR_ROOT / suite_dir.name / kind
            make_pair(pair_root, "stale-pair", "v44-candidate-review-gate")
            status_path = pair_root / "stale-pair" / "pair-status.json"
            status = read_json(status_path)
            status["pair_id"] = "different"
            write_json_atomic(status_path, status, root=status_path.parent)
            select_clean_root(suite_dir / kind, pair_root=pair_root, clean_pair_root=PAIR_ROOT / suite_dir.name / f"{kind}-clean", min_pairs=3, policy="lexicographic-last")
        elif kind == "unsafe-clean-root":
            pair_root = PAIR_ROOT / suite_dir.name / kind
            make_pair(pair_root, "pair-a", "v44-candidate-review-gate")
            select_clean_root(suite_dir / kind, pair_root=pair_root, clean_pair_root=pair_root, min_pairs=3, policy="lexicographic-last")
        else:
            raise DogfoodPairSelectError("ERR_DOGFOOD_PAIR_SELECT_FIXTURE_FAILED", f"unknown blocked fixture kind: {kind}")
    except DogfoodPairSelectError as exc:
        if fixture.get("expected_error") != exc.code:
            raise
        return {"status": "blocked", "error": exc.to_record()}
    raise DogfoodPairSelectError("ERR_DOGFOOD_PAIR_SELECT_FIXTURE_FAILED", f"{kind} unexpectedly passed")


def run_fixture(fixture: dict[str, Any], suite_dir: Path) -> dict[str, Any]:
    fixture_id = fixture["id"]
    try:
        kind = fixture["kind"]
        pair_root = PAIR_ROOT / suite_dir.name / fixture_id
        clean_root = PAIR_ROOT / suite_dir.name / f"{fixture_id}-clean"
        if pair_root.exists():
            shutil.rmtree(pair_root)
        if clean_root.exists():
            shutil.rmtree(clean_root)
        if kind == "select-duplicates":
            for pair_id, task_id in [
                ("release-a", "release-contract-count-sync"),
                ("release-z", "release-contract-count-sync"),
                ("v44-a", "v44-candidate-review-gate"),
                ("v45-a", "v45-readme-asset-promotion"),
            ]:
                make_pair(pair_root, pair_id, task_id)
            status = select_clean_root(suite_dir / fixture_id, pair_root=pair_root, clean_pair_root=clean_root, min_pairs=3, policy="lexicographic-last")
        elif kind == "insufficient-unique":
            make_pair(pair_root, "release-a", "release-contract-count-sync")
            make_pair(pair_root, "v44-a", "v44-candidate-review-gate")
            status = select_clean_root(suite_dir / fixture_id, pair_root=pair_root, clean_pair_root=clean_root, min_pairs=3, policy="lexicographic-last")
        elif kind in {"stale-pair", "unsafe-clean-root"}:
            status = blocked_fixture_status(kind, fixture, suite_dir)
        else:
            raise DogfoodPairSelectError("ERR_DOGFOOD_PAIR_SELECT_FIXTURE_FAILED", f"unknown fixture kind: {kind}")
        expected_decision = fixture.get("expected_decision")
        if expected_decision is not None and status.get("decision") != expected_decision:
            raise DogfoodPairSelectError("ERR_DOGFOOD_PAIR_SELECT_FIXTURE_FAILED", f"expected decision {expected_decision}, got {status.get('decision')}")
        expected_graph_ready = fixture.get("expected_graph_ready")
        if expected_graph_ready is not None and status.get("series_graph_ready") is not expected_graph_ready:
            raise DogfoodPairSelectError("ERR_DOGFOOD_PAIR_SELECT_FIXTURE_FAILED", f"expected graph ready {expected_graph_ready}, got {status.get('series_graph_ready')}")
        expected_error = fixture.get("expected_error")
        actual_error = status.get("error", {}).get("code") if isinstance(status.get("error"), dict) else None
        if expected_error is not None and actual_error != expected_error:
            raise DogfoodPairSelectError("ERR_DOGFOOD_PAIR_SELECT_FIXTURE_FAILED", f"expected error {expected_error}, got {actual_error}")
        return {"id": fixture_id, "status": "pass", "observed_status": status.get("decision", status.get("status")), "required": fixture.get("required", True)}
    except DogfoodPairSelectError as exc:
        record = exc.to_record()
        record["fixture_id"] = fixture_id
        return {"id": fixture_id, "status": "fail", "required": fixture.get("required", True), "error": record}


def evaluate_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    suite_id = Path(out_dir).name
    suite_dir = resolve_out(out_dir)
    if suite_dir.exists():
        sentinel = read_sentinel(suite_dir)
        if sentinel is None or sentinel.get("selection_id") != suite_id:
            raise DogfoodPairSelectError("ERR_DOGFOOD_PAIR_SELECT_PATH_UNSAFE", "existing selection suite is not selection-owned", path=suite_dir)
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
        raise DogfoodPairSelectError("ERR_DOGFOOD_PAIR_SELECT_FIXTURE_FAILED", "manifest decision is kill", path=manifest_path)
    return summary


def self_test() -> None:
    SELECT_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dwm-dogfood-pair-select-self-test-", dir=SELECT_ROOT) as tmp:
        summary = evaluate_manifest(ROOT / "fixtures" / "v64" / "manifest.json", Path(tmp) / "dogfood-pair-select-self-test")
    if summary["decision"] != "keep":
        raise DogfoodPairSelectError("ERR_DOGFOOD_PAIR_SELECT_FIXTURE_FAILED", "dogfood pair select self-test manifest did not keep")
    print("dwm_dogfood_pair_select self-test: pass")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", choices=["select"])
    parser.add_argument("--clean-pair-root")
    parser.add_argument("--manifest")
    parser.add_argument("--min-pairs", type=int, default=3)
    parser.add_argument("--out")
    parser.add_argument("--pair-root", default="out/dogfood-pairs")
    parser.add_argument("--policy", default="lexicographic-last")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
        elif args.manifest:
            if not args.out:
                raise DogfoodPairSelectError("ERR_DOGFOOD_PAIR_SELECT_PATH_UNSAFE", "--manifest requires --out")
            summary = evaluate_manifest(Path(args.manifest), Path(args.out))
            print(canonical_json_text({key: summary[key] for key in ["suite_id", "fixture_count", "required_fixture_count", "required_passed", "passed", "failed", "skipped", "decision"]}))
        elif args.command == "select":
            if not args.out:
                raise DogfoodPairSelectError("ERR_DOGFOOD_PAIR_SELECT_PATH_UNSAFE", "select requires --out")
            status = select_clean_root(
                Path(args.out),
                pair_root=Path(args.pair_root),
                clean_pair_root=Path(args.clean_pair_root) if args.clean_pair_root else None,
                min_pairs=args.min_pairs,
                policy=args.policy,
            )
            print(canonical_json_text(status))
        else:
            parser.error("expected --self-test, --manifest, or select")
    except DogfoodPairSelectError as exc:
        print(canonical_json_text(exc.to_record()), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
