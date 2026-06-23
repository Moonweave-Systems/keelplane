#!/usr/bin/env python3
"""V24 live benchmark evidence capture."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from compile_workflow import canonical_hash, canonical_json_text, read_json, write_json_atomic  # noqa: E402
from dwm_benchmark import REGISTRY_PATH, corpus_summary, validate_corpus  # noqa: E402


TOOL = "dwm_live_benchmark.py"
SCHEMA_VERSION = "1.0"
LIVE_BENCHMARK_VERSION = "24.0.0"
LIVE_ROOT = ROOT / "out" / "benchmarks-live"
SENTINEL = ".dwm_live_benchmark-owned.json"
SAFE_CAPTURE_MODES = {"fixture-control"}
SAFE_ADAPTER_MODES = {"codex-cli"}


class LiveBenchmarkError(ValueError):
    """Structured V24 live benchmark failure."""

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
        raise LiveBenchmarkError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise LiveBenchmarkError(code, "path contains a symlink", path=current)


def resolve_live_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_LIVE_BENCHMARK_PATH_UNSAFE", message="live benchmark output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = LIVE_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise LiveBenchmarkError("ERR_LIVE_BENCHMARK_PATH_UNSAFE", f"live benchmark output must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise LiveBenchmarkError("ERR_LIVE_BENCHMARK_PATH_UNSAFE", "live benchmark output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_LIVE_BENCHMARK_PATH_SYMLINK")
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


def prepare_out_dir(path: Path, capture_id: str, *, source: Path) -> None:
    if path.exists():
        if path.is_symlink():
            raise LiveBenchmarkError("ERR_LIVE_BENCHMARK_PATH_SYMLINK", "live benchmark output is a symlink", path=path)
        if not path.is_dir():
            raise LiveBenchmarkError("ERR_LIVE_BENCHMARK_PATH_UNSAFE", "live benchmark output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("capture_id") != capture_id:
            raise LiveBenchmarkError("ERR_LIVE_BENCHMARK_PATH_UNSAFE", "existing live benchmark output is not live-benchmark-owned", path=path)
        shutil.rmtree(path)
    LIVE_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(
        path / SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "live_benchmark_version": LIVE_BENCHMARK_VERSION,
            "capture_id": capture_id,
            "source_path": rel(source),
            "created_at": now_utc(),
        },
        root=path,
    )


def load_corpus(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise LiveBenchmarkError("ERR_LIVE_BENCHMARK_CORPUS_MISSING", "benchmark corpus is missing or symlinked", path=path)
    try:
        return validate_corpus(read_json(path), path=path)
    except FileNotFoundError as exc:
        raise LiveBenchmarkError("ERR_LIVE_BENCHMARK_CORPUS_MISSING", "benchmark corpus is missing", path=path) from exc


def require_fresh_corpus(corpus: dict[str, Any], expected_hash: str | None) -> str:
    actual_hash = canonical_hash(corpus)
    if expected_hash is not None and expected_hash != actual_hash:
        raise LiveBenchmarkError("ERR_LIVE_BENCHMARK_STALE_SCORE", "expected corpus hash does not match current corpus")
    return actual_hash


def write_capture_artifacts(
    out_dir: Path,
    *,
    capture_id: str,
    mode: str,
    corpus: dict[str, Any],
    corpus_hash: str,
    source_path: Path,
) -> dict[str, Any]:
    evaluation = corpus_summary() if source_path == REGISTRY_PATH else {
        **__import__("dwm_benchmark").evaluate_corpus(corpus),
    }
    run_record = {
        "schema_version": SCHEMA_VERSION,
        "live_benchmark_version": LIVE_BENCHMARK_VERSION,
        "capture_id": capture_id,
        "mode": mode,
        "status": "captured",
        "started_at": now_utc(),
        "completed_at": now_utc(),
        "source_hashes": {
            "corpus": corpus_hash,
        },
    }
    commands = {
        "mode": mode,
        "executed": [],
        "blocked": [],
        "note": "fixture-control captures benchmark corpus evidence without live model execution",
    }
    evidence = {
        "status": "captured",
        "task_count": evaluation["task_count"],
        "metric_count": evaluation["metric_count"],
        "mode_count": evaluation["mode_count"],
        "corpus_hash": corpus_hash,
    }
    score = {
        "status": "captured",
        "baseline_total": evaluation["baseline_total"],
        "candidate_total": evaluation["candidate_total"],
        "margin": evaluation["margin"],
        "task_summaries": evaluation["task_summaries"],
    }
    status = {
        "status": "captured",
        "mode": mode,
        "task_count": evaluation["task_count"],
        "source_hashes": run_record["source_hashes"],
    }
    write_json_atomic(out_dir / "run.json", run_record, root=out_dir)
    write_json_atomic(out_dir / "commands.json", commands, root=out_dir)
    write_json_atomic(out_dir / "evidence.json", evidence, root=out_dir)
    write_json_atomic(out_dir / "score.json", score, root=out_dir)
    write_json_atomic(out_dir / "status.json", status, root=out_dir)
    return status


def capture_fixture_control(
    *,
    out_dir: Path,
    capture_id: str,
    corpus_path: Path = REGISTRY_PATH,
    expected_corpus_hash: str | None = None,
) -> dict[str, Any]:
    corpus = load_corpus(corpus_path)
    corpus_hash = require_fresh_corpus(corpus, expected_corpus_hash)
    prepare_out_dir(out_dir, capture_id, source=corpus_path)
    return write_capture_artifacts(
        out_dir,
        capture_id=capture_id,
        mode="fixture-control",
        corpus=corpus,
        corpus_hash=corpus_hash,
        source_path=corpus_path,
    )


def check_adapter_availability(command: str, mode: str) -> dict[str, Any]:
    if mode not in SAFE_ADAPTER_MODES:
        raise LiveBenchmarkError("ERR_LIVE_BENCHMARK_UNSAFE_MODE", f"{mode} is not a V24 safe adapter mode")
    executable = command.split()[0]
    if shutil.which(executable) is None:
        return {
            "status": "skipped",
            "mode": mode,
            "error": {
                "code": "ERR_LIVE_BENCHMARK_ADAPTER_UNAVAILABLE",
                "message": f"adapter command not found: {executable}",
            },
        }
    completed = subprocess.run([executable, "--version"], cwd=ROOT, check=False, capture_output=True, text=True, timeout=10)
    if completed.returncode != 0:
        return {
            "status": "skipped",
            "mode": mode,
            "error": {
                "code": "ERR_LIVE_BENCHMARK_ADAPTER_UNAVAILABLE",
                "message": f"adapter version check failed: {executable}",
            },
        }
    return {
        "status": "captured",
        "mode": mode,
        "adapter": executable,
        "version_output_hash": canonical_hash({"stdout": completed.stdout.strip(), "stderr": completed.stderr.strip()}),
    }


def blocked_fixture_status(kind: str, fixture: dict[str, Any]) -> dict[str, Any]:
    try:
        if kind == "missing-corpus":
            capture_fixture_control(
                out_dir=LIVE_ROOT / "fixture-missing-corpus",
                capture_id="fixture-missing-corpus",
                corpus_path=ROOT / str(fixture["corpus"]),
            )
        elif kind == "unsafe-mode":
            mode = str(fixture["mode"])
            if mode not in SAFE_CAPTURE_MODES:
                raise LiveBenchmarkError("ERR_LIVE_BENCHMARK_UNSAFE_MODE", f"{mode} is not allowed for V24 live capture")
        elif kind == "stale-score":
            capture_fixture_control(
                out_dir=LIVE_ROOT / "fixture-stale-score",
                capture_id="fixture-stale-score",
                expected_corpus_hash=str(fixture["expected_corpus_hash"]),
            )
        else:
            raise LiveBenchmarkError("ERR_LIVE_BENCHMARK_FIXTURE_FAILED", f"unknown blocked fixture kind: {kind}")
    except LiveBenchmarkError as exc:
        if fixture.get("expected_error") != exc.code:
            raise
        return {"status": "blocked", "error": exc.to_record()}
    raise LiveBenchmarkError("ERR_LIVE_BENCHMARK_FIXTURE_FAILED", f"{kind} unexpectedly passed")


def run_fixture(fixture: dict[str, Any], suite_dir: Path) -> dict[str, Any]:
    fixture_id = fixture["id"]
    try:
        kind = fixture["kind"]
        if kind == "fixture-control":
            status = capture_fixture_control(out_dir=suite_dir / fixture_id, capture_id=fixture_id)
        elif kind in {"missing-corpus", "unsafe-mode", "stale-score"}:
            status = blocked_fixture_status(kind, fixture)
        elif kind == "adapter-availability":
            status = check_adapter_availability(str(fixture["adapter_command"]), str(fixture["mode"]))
        else:
            raise LiveBenchmarkError("ERR_LIVE_BENCHMARK_FIXTURE_FAILED", f"unknown fixture kind: {kind}")
        expected_status = fixture.get("expected_status")
        if expected_status is not None and status.get("status") != expected_status:
            raise LiveBenchmarkError("ERR_LIVE_BENCHMARK_FIXTURE_FAILED", f"expected status {expected_status}, got {status.get('status')}")
        expected_task_count = fixture.get("expected_task_count")
        if expected_task_count is not None and status.get("task_count") != expected_task_count:
            raise LiveBenchmarkError("ERR_LIVE_BENCHMARK_FIXTURE_FAILED", f"expected task_count {expected_task_count}, got {status.get('task_count')}")
        expected_error = fixture.get("expected_error")
        actual_error = status.get("error", {}).get("code") if isinstance(status.get("error"), dict) else None
        if expected_error is not None and actual_error != expected_error:
            raise LiveBenchmarkError("ERR_LIVE_BENCHMARK_FIXTURE_FAILED", f"expected error {expected_error}, got {actual_error}")
        return {
            "id": fixture_id,
            "status": "pass",
            "observed_status": status.get("status"),
            "required": fixture.get("required", True),
        }
    except LiveBenchmarkError as exc:
        record = exc.to_record()
        record["fixture_id"] = fixture_id
        return {"id": fixture_id, "status": "fail", "required": fixture.get("required", True), "error": record}


def evaluate_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    suite_id = Path(out_dir).name
    suite_dir = resolve_live_out(out_dir)
    if suite_dir.exists():
        sentinel = read_sentinel(suite_dir)
        if sentinel is None or sentinel.get("capture_id") != suite_id:
            raise LiveBenchmarkError("ERR_LIVE_BENCHMARK_PATH_UNSAFE", "existing live benchmark suite is not live-benchmark-owned", path=suite_dir)
        shutil.rmtree(suite_dir)
    prepare_out_dir(suite_dir, suite_id, source=manifest_path)
    fixtures = manifest["fixtures"]
    required_ids = set(manifest["required_fixture_ids"])
    results = [run_fixture(fixture, suite_dir) for fixture in fixtures]
    passed = sum(1 for item in results if item["status"] == "pass")
    failures = [item["error"] for item in results if item["status"] == "fail"]
    skipped = sum(1 for item in results if item.get("observed_status") == "skipped")
    required_passed = sum(1 for item in results if item["id"] in required_ids and item["status"] == "pass")
    required_failed = [item for item in results if item["id"] in required_ids and item["status"] == "fail"]
    summary = {
        "suite_id": suite_id,
        "fixture_count": len(fixtures),
        "required_fixture_count": len(required_ids),
        "required_passed": required_passed,
        "passed": passed,
        "failed": len(failures),
        "skipped": skipped,
        "decision": "keep" if not required_failed and required_ids <= {item["id"] for item in results} else "kill",
        "failures": failures,
        "fixtures": results,
        "source_hashes": {
            "manifest": canonical_hash(manifest),
            "corpus": canonical_hash(load_corpus(REGISTRY_PATH)),
        },
    }
    write_json_atomic(suite_dir / "summary.json", summary, root=suite_dir)
    if summary["decision"] != "keep":
        raise LiveBenchmarkError("ERR_LIVE_BENCHMARK_FIXTURE_FAILED", "manifest decision is kill", path=manifest_path)
    return summary


def self_test() -> None:
    LIVE_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dwm-live-benchmark-self-test-", dir=LIVE_ROOT) as tmp:
        summary = evaluate_manifest(ROOT / "fixtures" / "v24" / "manifest.json", Path(tmp) / "live-benchmark-self-test")
    if summary["decision"] != "keep":
        raise LiveBenchmarkError("ERR_LIVE_BENCHMARK_FIXTURE_FAILED", "live benchmark self-test manifest did not keep")
    print("dwm_live_benchmark self-test: pass")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", choices=["capture", "adapter-check"])
    parser.add_argument("--adapter-command", default="codex")
    parser.add_argument("--corpus", default=str(REGISTRY_PATH))
    parser.add_argument("--expected-corpus-hash")
    parser.add_argument("--manifest")
    parser.add_argument("--mode", default="fixture-control")
    parser.add_argument("--out")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
        elif args.manifest:
            if not args.out:
                raise LiveBenchmarkError("ERR_LIVE_BENCHMARK_PATH_UNSAFE", "--manifest requires --out")
            summary = evaluate_manifest(Path(args.manifest), Path(args.out))
            print(canonical_json_text({key: summary[key] for key in ["suite_id", "fixture_count", "required_fixture_count", "required_passed", "passed", "failed", "skipped", "decision"]}))
        elif args.command == "capture":
            if args.mode not in SAFE_CAPTURE_MODES:
                raise LiveBenchmarkError("ERR_LIVE_BENCHMARK_UNSAFE_MODE", f"{args.mode} is not allowed for V24 live capture")
            if not args.out:
                raise LiveBenchmarkError("ERR_LIVE_BENCHMARK_PATH_UNSAFE", "capture requires --out")
            status = capture_fixture_control(
                out_dir=resolve_live_out(args.out),
                capture_id=Path(args.out).name,
                corpus_path=Path(args.corpus),
                expected_corpus_hash=args.expected_corpus_hash,
            )
            print(canonical_json_text(status))
        elif args.command == "adapter-check":
            print(canonical_json_text(check_adapter_availability(args.adapter_command, args.mode)))
        else:
            parser.error("expected --self-test, --manifest, capture, or adapter-check")
    except LiveBenchmarkError as exc:
        print(canonical_json_text(exc.to_record()), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
