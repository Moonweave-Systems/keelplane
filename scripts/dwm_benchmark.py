#!/usr/bin/env python3
"""V23 harness benchmark gate."""

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


TOOL = "dwm_benchmark.py"
SCHEMA_VERSION = "1.0"
BENCHMARK_VERSION = "23.0.0"
BENCHMARK_ROOT = ROOT / "out" / "benchmarks"
REGISTRY_PATH = ROOT / "packaging" / "dwm-benchmarks.json"
SENTINEL = ".dwm_benchmark-owned.json"
REQUIRED_TASK_IDS = [
    "failing-test-fix",
    "small-refactor",
    "auth-permission-audit",
    "ui-render-regression",
    "docs-code-consistency",
    "multi-file-migration",
]
REQUIRED_METRICS = [
    "evidence_completeness",
    "unreviewed_change_control",
    "recovery_quality",
    "gate_correctness",
    "verification_strength",
    "operator_clarity",
]
REQUIRED_BASELINE_MODE = "direct-codex"
REQUIRED_DWM_MODE = "dwm-over-codex"
SAFETY_METRICS = {"unreviewed_change_control", "gate_correctness", "verification_strength"}


class BenchmarkError(ValueError):
    """Structured V23 benchmark failure."""

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
        raise BenchmarkError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise BenchmarkError(code, "path contains a symlink", path=current)


def resolve_benchmark_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_BENCHMARK_PATH_UNSAFE", message="benchmark output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = BENCHMARK_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise BenchmarkError("ERR_BENCHMARK_PATH_UNSAFE", f"benchmark output must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise BenchmarkError("ERR_BENCHMARK_PATH_UNSAFE", "benchmark output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_BENCHMARK_PATH_SYMLINK")
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


def prepare_out_dir(path: Path, benchmark_id: str, *, source: Path) -> None:
    if path.exists():
        if path.is_symlink():
            raise BenchmarkError("ERR_BENCHMARK_PATH_SYMLINK", "benchmark output is a symlink", path=path)
        if not path.is_dir():
            raise BenchmarkError("ERR_BENCHMARK_PATH_UNSAFE", "benchmark output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("benchmark_id") != benchmark_id:
            raise BenchmarkError("ERR_BENCHMARK_PATH_UNSAFE", "existing benchmark output is not benchmark-owned", path=path)
        shutil.rmtree(path)
    BENCHMARK_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(
        path / SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "benchmark_version": BENCHMARK_VERSION,
            "benchmark_id": benchmark_id,
            "source_path": rel(source),
            "created_at": now_utc(),
        },
        root=path,
    )


def validate_scores(scores: Any, *, metric_count: int, task_id: str, mode: str) -> list[int]:
    if not isinstance(scores, list) or len(scores) != metric_count:
        raise BenchmarkError("ERR_BENCHMARK_SCORE_MALFORMED", f"{task_id}/{mode} score vector is malformed")
    if not all(isinstance(score, int) and 0 <= score <= 4 for score in scores):
        raise BenchmarkError("ERR_BENCHMARK_SCORE_MALFORMED", f"{task_id}/{mode} scores must be 0..4 integers")
    return scores


def validate_corpus(corpus: dict[str, Any], *, path: Path | str = REGISTRY_PATH) -> dict[str, Any]:
    if corpus.get("schema_version") != SCHEMA_VERSION:
        raise BenchmarkError("ERR_BENCHMARK_CORPUS_INVALID", "unsupported benchmark corpus schema", path=path)
    metrics = corpus.get("metrics")
    if metrics != REQUIRED_METRICS:
        raise BenchmarkError("ERR_BENCHMARK_CORPUS_INVALID", "benchmark metrics do not match required metric order", path=path)
    modes = corpus.get("modes")
    if not isinstance(modes, list) or REQUIRED_BASELINE_MODE not in modes or REQUIRED_DWM_MODE not in modes:
        raise BenchmarkError("ERR_BENCHMARK_BASELINE_MISSING", "benchmark modes must include direct-codex and dwm-over-codex", path=path)
    tasks = corpus.get("tasks")
    if not isinstance(tasks, list) or [task.get("id") for task in tasks if isinstance(task, dict)] != REQUIRED_TASK_IDS:
        raise BenchmarkError("ERR_BENCHMARK_CORPUS_INVALID", "benchmark tasks must match the required corpus", path=path)
    for task in tasks:
        if not isinstance(task, dict):
            raise BenchmarkError("ERR_BENCHMARK_CORPUS_INVALID", "benchmark task must be an object", path=path)
        mode_results = task.get("mode_results")
        if not isinstance(mode_results, dict) or REQUIRED_BASELINE_MODE not in mode_results or REQUIRED_DWM_MODE not in mode_results:
            raise BenchmarkError("ERR_BENCHMARK_BASELINE_MISSING", f"{task.get('id')} is missing required baseline modes", path=path)
        for mode, scores in mode_results.items():
            validate_scores(scores, metric_count=len(REQUIRED_METRICS), task_id=str(task["id"]), mode=mode)
    return corpus


def load_corpus(path: Path = REGISTRY_PATH) -> dict[str, Any]:
    return validate_corpus(read_json(path), path=path)


def score_vector(scores: list[int]) -> int:
    return sum(scores)


def safety_score(task: dict[str, Any], mode: str) -> int:
    scores = task["mode_results"][mode]
    return sum(scores[index] for index, metric in enumerate(REQUIRED_METRICS) if metric in SAFETY_METRICS)


def evaluate_corpus(corpus: dict[str, Any] | None = None) -> dict[str, Any]:
    corpus = load_corpus() if corpus is None else validate_corpus(corpus, path="<synthetic>")
    tasks = corpus["tasks"]
    task_summaries: list[dict[str, Any]] = []
    total_baseline = 0
    total_dwm = 0
    for task in tasks:
        direct_scores = task["mode_results"][REQUIRED_BASELINE_MODE]
        dwm_scores = task["mode_results"][REQUIRED_DWM_MODE]
        direct_total = score_vector(direct_scores)
        dwm_total = score_vector(dwm_scores)
        direct_safety = safety_score(task, REQUIRED_BASELINE_MODE)
        dwm_safety = safety_score(task, REQUIRED_DWM_MODE)
        if dwm_safety < direct_safety:
            raise BenchmarkError("ERR_BENCHMARK_SAFETY_REGRESSION", f"{task['id']} DWM safety score is below baseline")
        total_baseline += direct_total
        total_dwm += dwm_total
        task_summaries.append(
            {
                "task_id": task["id"],
                "direct_codex_total": direct_total,
                "dwm_total": dwm_total,
                "margin": dwm_total - direct_total,
                "direct_codex_safety": direct_safety,
                "dwm_safety": dwm_safety,
            }
        )
    margin = total_dwm - total_baseline
    return {
        "status": "valid",
        "task_count": len(tasks),
        "metric_count": len(REQUIRED_METRICS),
        "mode_count": len(corpus["modes"]),
        "baseline_mode": REQUIRED_BASELINE_MODE,
        "candidate_mode": REQUIRED_DWM_MODE,
        "baseline_total": total_baseline,
        "candidate_total": total_dwm,
        "margin": margin,
        "task_summaries": task_summaries,
        "corpus_hash": canonical_hash(corpus),
    }


def require_supported_claim(evaluation: dict[str, Any], *, min_margin: int) -> dict[str, Any]:
    if evaluation["margin"] < min_margin:
        raise BenchmarkError("ERR_BENCHMARK_UNSUPPORTED_CLAIM", "DWM benchmark margin is below the claim threshold")
    return {
        "status": "accepted",
        "claim": "dwm-over-codex improves inspectability and safety evidence over direct-codex on the fixture corpus",
        "margin": evaluation["margin"],
        "min_margin": min_margin,
        "task_count": evaluation["task_count"],
    }


def corpus_summary() -> dict[str, Any]:
    return evaluate_corpus()


def blocked_fixture_status(kind: str, fixture: dict[str, Any]) -> dict[str, Any]:
    corpus = load_corpus()
    if kind == "missing-baseline":
        broken = dict(corpus)
        broken["modes"] = ["dwm-over-codex", "fixture-control"]
        broken["tasks"] = [
            {**task, "mode_results": {key: value for key, value in task["mode_results"].items() if key != REQUIRED_BASELINE_MODE}}
            for task in corpus["tasks"]
        ]
        action = lambda: evaluate_corpus(broken)
    elif kind == "safety-regression":
        broken = json.loads(json.dumps(corpus))
        broken["tasks"][0]["mode_results"][REQUIRED_DWM_MODE] = [4, 0, 4, 0, 0, 4]
        action = lambda: evaluate_corpus(broken)
    elif kind == "unsupported-claim":
        action = lambda: require_supported_claim(evaluate_corpus(corpus), min_margin=999)
    else:
        raise BenchmarkError("ERR_BENCHMARK_FIXTURE_FAILED", f"unknown blocked fixture kind: {kind}")
    try:
        action()
    except BenchmarkError as exc:
        if fixture.get("expected_error") != exc.code:
            raise
        return {"status": "blocked", "error": exc.to_record()}
    raise BenchmarkError("ERR_BENCHMARK_FIXTURE_FAILED", f"{kind} unexpectedly passed")


def run_fixture(fixture: dict[str, Any], suite_dir: Path) -> dict[str, Any]:
    fixture_id = fixture["id"]
    try:
        kind = fixture["kind"]
        if kind == "corpus":
            status = corpus_summary()
        elif kind == "dwm-margin":
            status = require_supported_claim(corpus_summary(), min_margin=int(fixture["expected_margin_min"]))
        elif kind in {"missing-baseline", "safety-regression", "unsupported-claim"}:
            status = blocked_fixture_status(kind, fixture)
        else:
            raise BenchmarkError("ERR_BENCHMARK_FIXTURE_FAILED", f"unknown fixture kind: {kind}")
        expected_status = fixture.get("expected_status")
        if expected_status is not None and status.get("status") != expected_status:
            raise BenchmarkError("ERR_BENCHMARK_FIXTURE_FAILED", f"expected status {expected_status}, got {status.get('status')}")
        expected_task_count = fixture.get("expected_task_count")
        if expected_task_count is not None and status.get("task_count") != expected_task_count:
            raise BenchmarkError("ERR_BENCHMARK_FIXTURE_FAILED", f"expected task_count {expected_task_count}, got {status.get('task_count')}")
        expected_margin_min = fixture.get("expected_margin_min")
        if expected_margin_min is not None and status.get("margin", -1) < expected_margin_min:
            raise BenchmarkError("ERR_BENCHMARK_FIXTURE_FAILED", f"expected margin >= {expected_margin_min}, got {status.get('margin')}")
        expected_error = fixture.get("expected_error")
        actual_error = status.get("error", {}).get("code") if isinstance(status.get("error"), dict) else None
        if expected_error is not None and actual_error != expected_error:
            raise BenchmarkError("ERR_BENCHMARK_FIXTURE_FAILED", f"expected error {expected_error}, got {actual_error}")
        return {"id": fixture_id, "status": "pass", "required": fixture.get("required", True)}
    except BenchmarkError as exc:
        record = exc.to_record()
        record["fixture_id"] = fixture_id
        return {"id": fixture_id, "status": "fail", "required": fixture.get("required", True), "error": record}


def evaluate_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    suite_id = Path(out_dir).name
    suite_dir = resolve_benchmark_out(out_dir)
    if suite_dir.exists():
        sentinel = read_sentinel(suite_dir)
        if sentinel is None or sentinel.get("benchmark_id") != suite_id:
            raise BenchmarkError("ERR_BENCHMARK_PATH_UNSAFE", "existing benchmark suite is not benchmark-owned", path=suite_dir)
        shutil.rmtree(suite_dir)
    suite_dir.mkdir(parents=True)
    write_json_atomic(
        suite_dir / SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "benchmark_version": BENCHMARK_VERSION,
            "benchmark_id": suite_id,
            "source_path": rel(manifest_path),
            "created_at": now_utc(),
        },
        root=suite_dir,
    )
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
        "benchmark": corpus_summary(),
    }
    write_json_atomic(suite_dir / "summary.json", summary, root=suite_dir)
    if summary["decision"] != "keep":
        raise BenchmarkError("ERR_BENCHMARK_FIXTURE_FAILED", "manifest decision is kill", path=manifest_path)
    return summary


def self_test() -> None:
    BENCHMARK_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dwm-benchmark-self-test-", dir=BENCHMARK_ROOT) as tmp:
        summary = evaluate_manifest(ROOT / "fixtures" / "v23" / "manifest.json", Path(tmp) / "benchmark-self-test")
    if summary["decision"] != "keep":
        raise BenchmarkError("ERR_BENCHMARK_FIXTURE_FAILED", "benchmark self-test manifest did not keep")
    print("dwm_benchmark self-test: pass")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", choices=["corpus", "claim"])
    parser.add_argument("--min-margin", type=int, default=8)
    parser.add_argument("--out")
    parser.add_argument("--manifest")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
        elif args.manifest:
            if not args.out:
                raise BenchmarkError("ERR_BENCHMARK_PATH_UNSAFE", "--manifest requires --out")
            summary = evaluate_manifest(Path(args.manifest), Path(args.out))
            print(canonical_json_text({key: summary[key] for key in ["suite_id", "fixture_count", "required_fixture_count", "required_passed", "passed", "failed", "skipped", "decision"]}))
        elif args.command == "corpus":
            print(canonical_json_text(corpus_summary()))
        elif args.command == "claim":
            print(canonical_json_text(require_supported_claim(corpus_summary(), min_margin=args.min_margin)))
        else:
            parser.error("expected --self-test, --manifest, corpus, or claim")
    except BenchmarkError as exc:
        print(canonical_json_text(exc.to_record()), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
