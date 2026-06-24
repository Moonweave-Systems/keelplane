#!/usr/bin/env python3
"""V58 dogfood comparison pair series and graph-readiness gate."""

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
from dwm_dogfood_pair import PAIR_ROOT, fixture_receipt, make_pair  # noqa: E402
from dwm_dogfood_measure import MEASURE_ROOT, measure  # noqa: E402


TOOL = "dwm_dogfood_pair_series.py"
SCHEMA_VERSION = "1.0"
PAIR_SERIES_VERSION = "58.0.0"
PAIR_SERIES_ROOT = ROOT / "out" / "dogfood-pair-series"
SENTINEL = ".dwm_dogfood_pair_series-owned.json"
MIN_GRAPH_PAIRS = 3


class DogfoodPairSeriesError(ValueError):
    """Structured V58 dogfood pair series failure."""

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
        raise DogfoodPairSeriesError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise DogfoodPairSeriesError(code, "path contains a symlink", path=current)


def resolve_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_DOGFOOD_PAIR_SERIES_PATH_UNSAFE", message="dogfood pair series output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = PAIR_SERIES_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise DogfoodPairSeriesError("ERR_DOGFOOD_PAIR_SERIES_PATH_UNSAFE", f"dogfood pair series output must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise DogfoodPairSeriesError("ERR_DOGFOOD_PAIR_SERIES_PATH_UNSAFE", "dogfood pair series output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_DOGFOOD_PAIR_SERIES_PATH_SYMLINK")
    return resolved


def resolve_pair_root(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_DOGFOOD_PAIR_SERIES_PAIR_ROOT_INVALID", message="pair root must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = PAIR_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise DogfoodPairSeriesError("ERR_DOGFOOD_PAIR_SERIES_PAIR_ROOT_INVALID", f"pair root must resolve under {root_resolved}", path=value) from exc
    check_components_not_symlink(candidate, code="ERR_DOGFOOD_PAIR_SERIES_PATH_SYMLINK")
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


def prepare_out_dir(path: Path, series_id: str, *, source: Path) -> None:
    if path.exists():
        if path.is_symlink():
            raise DogfoodPairSeriesError("ERR_DOGFOOD_PAIR_SERIES_PATH_SYMLINK", "dogfood pair series output is a symlink", path=path)
        if not path.is_dir():
            raise DogfoodPairSeriesError("ERR_DOGFOOD_PAIR_SERIES_PATH_UNSAFE", "dogfood pair series output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("series_id") != series_id:
            raise DogfoodPairSeriesError("ERR_DOGFOOD_PAIR_SERIES_PATH_UNSAFE", "existing dogfood pair series output is not series-owned", path=path)
        shutil.rmtree(path)
    PAIR_SERIES_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(
        path / SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "pair_series_version": PAIR_SERIES_VERSION,
            "series_id": series_id,
            "source_path": rel(source),
            "created_at": now_utc(),
        },
        root=path,
    )


def pair_dirs_from_root(pair_root: Path) -> list[Path]:
    pair_root = resolve_pair_root(pair_root)
    if not pair_root.is_dir() or pair_root.is_symlink():
        raise DogfoodPairSeriesError("ERR_DOGFOOD_PAIR_SERIES_PAIR_ROOT_INVALID", "pair root is not a directory", path=pair_root)
    dirs = [path for path in sorted(pair_root.iterdir()) if path.is_dir() and not path.is_symlink() and (path / "comparison-pair.json").is_file()]
    if not dirs:
        raise DogfoodPairSeriesError("ERR_DOGFOOD_PAIR_SERIES_INSUFFICIENT_PAIRS", "no dogfood comparison pairs found", path=pair_root)
    return dirs


def load_pair(pair_dir: Path) -> dict[str, Any]:
    pair_path = pair_dir / "comparison-pair.json"
    status_path = pair_dir / "pair-status.json"
    if not pair_path.is_file() or pair_path.is_symlink() or not status_path.is_file() or status_path.is_symlink():
        raise DogfoodPairSeriesError("ERR_DOGFOOD_PAIR_SERIES_ARTIFACT_MISSING", "pair artifacts are missing", path=pair_dir)
    pair = read_json(pair_path)
    status = read_json(status_path)
    if pair != status:
        raise DogfoodPairSeriesError("ERR_DOGFOOD_PAIR_SERIES_STALE_PAIR", "pair status and artifact do not match", path=pair_dir)
    if pair.get("status") != "dogfood-comparison-pair-recorded":
        raise DogfoodPairSeriesError("ERR_DOGFOOD_PAIR_SERIES_STALE_PAIR", "pair is not recorded", path=pair_dir)
    if pair.get("public_graph_ready") is True:
        raise DogfoodPairSeriesError("ERR_DOGFOOD_PAIR_SERIES_OVERCLAIM", "pair must not pre-claim graph readiness", path=pair_dir)
    for key in ["dwm_controlled", "direct_codex"]:
        metrics = pair.get(key, {}).get("metrics", {})
        if metrics.get("verification_passed") is not True:
            raise DogfoodPairSeriesError("ERR_DOGFOOD_PAIR_SERIES_UNVERIFIED_PAIR", "pair verification must pass before series", path=pair_dir)
    return pair


def readiness(pair_count: int, task_ids: list[str], min_pairs: int) -> dict[str, Any]:
    blocked_by: list[str] = []
    if pair_count < min_pairs:
        blocked_by.append("ERR_DOGFOOD_PAIR_SERIES_INSUFFICIENT_PAIRS")
    if len(set(task_ids)) != len(task_ids):
        blocked_by.append("ERR_DOGFOOD_PAIR_SERIES_DUPLICATE_TASK")
    return {
        "graph_ready": not blocked_by,
        "blocked_by": blocked_by,
        "min_pairs": min_pairs,
        "pair_count": pair_count,
        "safe_next_step": "collect more human-gated direct Codex pairs before graph promotion" if blocked_by else "review local pair series before any graph candidate",
    }


def render_series_doc(series: dict[str, Any]) -> str:
    lines = [
        "# DWM Dogfood Pair Series",
        "",
        f"- series: `{series['series_id']}`",
        f"- pair count: `{series['pair_count']}`",
        f"- graph ready: `{series['graph_readiness']['graph_ready']}`",
        f"- blocked by: `{', '.join(series['graph_readiness']['blocked_by']) or 'none'}`",
        "- claim policy: local pair evidence only; not a public benchmark trend",
        "",
        "| Task | DWM seconds | Direct seconds |",
        "| --- | --- | --- |",
    ]
    for pair in series["pairs"]:
        lines.append(
            f"| `{pair['task_id']}` | `{pair['dwm_elapsed_seconds']}` | `{pair['direct_elapsed_seconds']}` |"
        )
    lines.append("")
    return "\n".join(lines)


def build_series(pair_dirs: list[Path], out_dir: Path, *, series_id: str, min_pairs: int = MIN_GRAPH_PAIRS, source: Path | None = None) -> dict[str, Any]:
    if min_pairs < 1:
        raise DogfoodPairSeriesError("ERR_DOGFOOD_PAIR_SERIES_MIN_PAIRS_INVALID", "min_pairs must be positive")
    pairs = [(load_pair(path), path) for path in pair_dirs]
    hashes = [canonical_hash(pair) for pair, _ in pairs]
    if len(set(hashes)) != len(hashes):
        raise DogfoodPairSeriesError("ERR_DOGFOOD_PAIR_SERIES_DUPLICATE_PAIR", "pair hashes must be unique")
    prepare_out_dir(out_dir, series_id, source=source or pair_dirs[0])
    rows = []
    for pair, path in pairs:
        rows.append(
            {
                "pair_id": pair["pair_id"],
                "pair_path": rel(path),
                "task_id": pair["task_id"],
                "dwm_elapsed_seconds": pair["dwm_controlled"]["metrics"]["elapsed_seconds"],
                "direct_elapsed_seconds": pair["direct_codex"]["metrics"]["elapsed_seconds"],
                "dwm_verified": pair["dwm_controlled"]["metrics"]["verification_passed"],
                "direct_verified": pair["direct_codex"]["metrics"]["verification_passed"],
            }
        )
    graph_readiness = readiness(len(rows), [row["task_id"] for row in rows], min_pairs)
    series = {
        "tool": TOOL,
        "schema_version": SCHEMA_VERSION,
        "pair_series_version": PAIR_SERIES_VERSION,
        "status": "dogfood-pair-series-recorded",
        "decision": "graph-ready-local-review" if graph_readiness["graph_ready"] else "graph-blocked-needs-more-pairs",
        "series_id": series_id,
        "pair_count": len(rows),
        "pairs": rows,
        "graph_readiness": graph_readiness,
        "public_graph_ready": False,
        "external_claim_policy": "local pair evidence only; not an external benchmark authority",
        "source_hashes": {
            "pairs": hashes,
        },
    }
    write_json_atomic(out_dir / "pair-series.json", series, root=out_dir)
    write_json_atomic(out_dir / "graph-readiness.json", series["graph_readiness"], root=out_dir)
    write_json_atomic(out_dir / "status.json", series, root=out_dir)
    write_text_atomic(out_dir / "pair-series.md", render_series_doc(series), root=out_dir)
    return series


def make_pair_dir(base_name: str, index: int, suite_dir: Path, *, task_id: str = "release-contract-count-sync") -> Path:
    measure_dir = MEASURE_ROOT / suite_dir.name / f"{base_name}-measure-{index}"
    measure(measure_dir, task_id=task_id)
    evidence = suite_dir / f"{base_name}-direct-evidence-{index}.md"
    evidence.write_text(f"direct receipt fixture evidence {index}\n")
    receipt = fixture_receipt(rel(evidence), task_id=task_id)
    receipt["metrics"]["elapsed_seconds"] = 50.0 + index
    receipt_path = suite_dir / f"{base_name}-direct-receipt-{index}.json"
    write_json_atomic(receipt_path, receipt, root=suite_dir)
    pair_dir = PAIR_ROOT / suite_dir.name / f"{base_name}-pair-{index}"
    make_pair(measure_dir, receipt_path, pair_dir)
    return pair_dir


def blocked_fixture_status(kind: str, fixture: dict[str, Any], suite_dir: Path) -> dict[str, Any]:
    try:
        if kind == "duplicate-pair":
            pair = make_pair_dir(f"{suite_dir.name}-duplicate", 0, suite_dir)
            build_series([pair, pair], suite_dir / kind, series_id=kind)
        elif kind == "stale-pair":
            first = make_pair_dir(f"{suite_dir.name}-stale", 0, suite_dir)
            status = read_json(first / "pair-status.json")
            status["pair_id"] = "stale"
            write_json_atomic(first / "pair-status.json", status, root=first)
            build_series([first], suite_dir / kind, series_id=kind, min_pairs=1)
        elif kind == "overclaim":
            first = make_pair_dir(f"{suite_dir.name}-overclaim", 0, suite_dir)
            pair = read_json(first / "comparison-pair.json")
            pair["public_graph_ready"] = True
            write_json_atomic(first / "comparison-pair.json", pair, root=first)
            write_json_atomic(first / "pair-status.json", pair, root=first)
            build_series([first], suite_dir / kind, series_id=kind, min_pairs=1)
        else:
            raise DogfoodPairSeriesError("ERR_DOGFOOD_PAIR_SERIES_FIXTURE_FAILED", f"unknown blocked fixture kind: {kind}")
    except DogfoodPairSeriesError as exc:
        if fixture.get("expected_error") != exc.code:
            raise
        return {"status": "blocked", "error": exc.to_record()}
    raise DogfoodPairSeriesError("ERR_DOGFOOD_PAIR_SERIES_FIXTURE_FAILED", f"{kind} unexpectedly passed")


def run_fixture(fixture: dict[str, Any], suite_dir: Path) -> dict[str, Any]:
    fixture_id = fixture["id"]
    try:
        kind = fixture["kind"]
        if kind == "series-ready":
            pair_dirs = [make_pair_dir(f"{suite_dir.name}-{fixture_id}", index, suite_dir, task_id=task_id) for index, task_id in enumerate(["v44-candidate-review-gate", "v45-readme-asset-promotion", "v46-workflow-queue"])]
            status = build_series(pair_dirs, suite_dir / fixture_id, series_id=fixture_id)
        elif kind == "series-insufficient":
            pair_dirs = [make_pair_dir(f"{suite_dir.name}-{fixture_id}", 0, suite_dir)]
            status = build_series(pair_dirs, suite_dir / fixture_id, series_id=fixture_id)
        elif kind in {"duplicate-pair", "stale-pair", "overclaim"}:
            status = blocked_fixture_status(kind, fixture, suite_dir)
        else:
            raise DogfoodPairSeriesError("ERR_DOGFOOD_PAIR_SERIES_FIXTURE_FAILED", f"unknown fixture kind: {kind}")
        expected_status = fixture.get("expected_status")
        if expected_status is not None and status.get("status") != expected_status:
            raise DogfoodPairSeriesError("ERR_DOGFOOD_PAIR_SERIES_FIXTURE_FAILED", f"expected status {expected_status}, got {status.get('status')}")
        expected_decision = fixture.get("expected_decision")
        if expected_decision is not None and status.get("decision") != expected_decision:
            raise DogfoodPairSeriesError("ERR_DOGFOOD_PAIR_SERIES_FIXTURE_FAILED", f"expected decision {expected_decision}, got {status.get('decision')}")
        expected_error = fixture.get("expected_error")
        actual_error = status.get("error", {}).get("code") if isinstance(status.get("error"), dict) else None
        if expected_error is not None and actual_error != expected_error:
            raise DogfoodPairSeriesError("ERR_DOGFOOD_PAIR_SERIES_FIXTURE_FAILED", f"expected error {expected_error}, got {actual_error}")
        return {"id": fixture_id, "status": "pass", "observed_status": status.get("status"), "required": fixture.get("required", True)}
    except DogfoodPairSeriesError as exc:
        record = exc.to_record()
        record["fixture_id"] = fixture_id
        return {"id": fixture_id, "status": "fail", "required": fixture.get("required", True), "error": record}


def evaluate_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    suite_id = Path(out_dir).name
    suite_dir = resolve_out(out_dir)
    if suite_dir.exists():
        sentinel = read_sentinel(suite_dir)
        if sentinel is None or sentinel.get("series_id") != suite_id:
            raise DogfoodPairSeriesError("ERR_DOGFOOD_PAIR_SERIES_PATH_UNSAFE", "existing dogfood pair series suite is not series-owned", path=suite_dir)
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
        raise DogfoodPairSeriesError("ERR_DOGFOOD_PAIR_SERIES_FIXTURE_FAILED", "manifest decision is kill", path=manifest_path)
    return summary


def self_test() -> None:
    PAIR_SERIES_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dwm-dogfood-pair-series-self-test-", dir=PAIR_SERIES_ROOT) as tmp:
        summary = evaluate_manifest(ROOT / "fixtures" / "v58" / "manifest.json", Path(tmp) / "dogfood-pair-series-self-test")
    if summary["decision"] != "keep":
        raise DogfoodPairSeriesError("ERR_DOGFOOD_PAIR_SERIES_FIXTURE_FAILED", "dogfood pair series self-test manifest did not keep")
    print("dwm_dogfood_pair_series self-test: pass")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", choices=["build"])
    parser.add_argument("--manifest")
    parser.add_argument("--min-pairs", type=int, default=MIN_GRAPH_PAIRS)
    parser.add_argument("--out")
    parser.add_argument("--pair-root", default="out/dogfood-pairs")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
        elif args.manifest:
            if not args.out:
                raise DogfoodPairSeriesError("ERR_DOGFOOD_PAIR_SERIES_PATH_UNSAFE", "--manifest requires --out")
            summary = evaluate_manifest(Path(args.manifest), Path(args.out))
            print(canonical_json_text({key: summary[key] for key in ["suite_id", "fixture_count", "required_fixture_count", "required_passed", "passed", "failed", "skipped", "decision"]}))
        elif args.command == "build":
            if not args.out:
                raise DogfoodPairSeriesError("ERR_DOGFOOD_PAIR_SERIES_PATH_UNSAFE", "build requires --out")
            pair_dirs = pair_dirs_from_root(Path(args.pair_root))
            print(canonical_json_text(build_series(pair_dirs, resolve_out(args.out), series_id=Path(args.out).name, min_pairs=args.min_pairs, source=Path(args.pair_root))))
        else:
            parser.error("expected --self-test, --manifest, or build")
    except DogfoodPairSeriesError as exc:
        print(canonical_json_text(exc.to_record()), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
