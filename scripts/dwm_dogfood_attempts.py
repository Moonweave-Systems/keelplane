#!/usr/bin/env python3
"""V54 measured dogfood comparison ledger."""

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
from dwm_dogfood_corpus import DOGFOOD_ROOT, REQUIRED_MODES, build_corpus, default_tasks  # noqa: E402


TOOL = "dwm_dogfood_attempts.py"
SCHEMA_VERSION = "1.0"
DOGFOOD_ATTEMPTS_VERSION = "54.0.0"
ATTEMPT_ROOT = ROOT / "out" / "dogfood-attempts"
SENTINEL = ".dwm_dogfood_attempts-owned.json"
FORBIDDEN_CLAIM_TERMS = [
    "beats codex",
    "better than codex",
    "external benchmark",
    "superior to",
    "state of the art",
]


class DogfoodAttemptsError(ValueError):
    """Structured V54 dogfood attempt failure."""

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
        raise DogfoodAttemptsError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise DogfoodAttemptsError(code, "path contains a symlink", path=current)


def resolve_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_DOGFOOD_ATTEMPTS_PATH_UNSAFE", message="dogfood attempt output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = ATTEMPT_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise DogfoodAttemptsError("ERR_DOGFOOD_ATTEMPTS_PATH_UNSAFE", f"dogfood attempt output must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise DogfoodAttemptsError("ERR_DOGFOOD_ATTEMPTS_PATH_UNSAFE", "dogfood attempt output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_DOGFOOD_ATTEMPTS_PATH_SYMLINK")
    return resolved


def resolve_corpus(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_DOGFOOD_ATTEMPTS_CORPUS_INVALID", message="corpus path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = DOGFOOD_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise DogfoodAttemptsError("ERR_DOGFOOD_ATTEMPTS_CORPUS_INVALID", f"corpus must resolve under {root_resolved}", path=value) from exc
    check_components_not_symlink(candidate, code="ERR_DOGFOOD_ATTEMPTS_PATH_SYMLINK")
    return resolved


def safe_repo_file(value: str) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_DOGFOOD_ATTEMPTS_EVIDENCE_MISSING", message="evidence path must not contain parent traversal")
    if raw.is_absolute():
        raise DogfoodAttemptsError("ERR_DOGFOOD_ATTEMPTS_EVIDENCE_MISSING", "evidence path must be repo-relative", path=value)
    path = ROOT / raw
    resolved = path.resolve(strict=False)
    try:
        resolved.relative_to(ROOT.resolve(strict=False))
    except ValueError as exc:
        raise DogfoodAttemptsError("ERR_DOGFOOD_ATTEMPTS_EVIDENCE_MISSING", "evidence path must stay in repo", path=value) from exc
    check_components_not_symlink(path, code="ERR_DOGFOOD_ATTEMPTS_PATH_SYMLINK")
    if not path.is_file():
        raise DogfoodAttemptsError("ERR_DOGFOOD_ATTEMPTS_EVIDENCE_MISSING", "evidence file is missing", path=value)
    return path


def read_sentinel(path: Path) -> dict[str, Any] | None:
    sentinel = path / SENTINEL
    if not sentinel.is_file() or sentinel.is_symlink():
        return None
    try:
        data = json.loads(sentinel.read_text())
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def prepare_out_dir(path: Path, attempt_id: str, *, source: Path) -> None:
    if path.exists():
        if path.is_symlink():
            raise DogfoodAttemptsError("ERR_DOGFOOD_ATTEMPTS_PATH_SYMLINK", "dogfood attempt output is a symlink", path=path)
        if not path.is_dir():
            raise DogfoodAttemptsError("ERR_DOGFOOD_ATTEMPTS_PATH_UNSAFE", "dogfood attempt output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("attempt_id") != attempt_id:
            raise DogfoodAttemptsError("ERR_DOGFOOD_ATTEMPTS_PATH_UNSAFE", "existing dogfood attempt output is not attempt-owned", path=path)
        shutil.rmtree(path)
    ATTEMPT_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(
        path / SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "dogfood_attempts_version": DOGFOOD_ATTEMPTS_VERSION,
            "attempt_id": attempt_id,
            "source_path": rel(source),
            "created_at": now_utc(),
        },
        root=path,
    )


def load_corpus(path: Path) -> dict[str, Any]:
    data_path = path / "dogfood-corpus.json"
    if not data_path.is_file() or data_path.is_symlink():
        raise DogfoodAttemptsError("ERR_DOGFOOD_ATTEMPTS_CORPUS_INVALID", "dogfood corpus is missing", path=path)
    corpus = read_json(data_path)
    if corpus.get("status") != "dogfood-corpus-recorded":
        raise DogfoodAttemptsError("ERR_DOGFOOD_ATTEMPTS_CORPUS_INVALID", "dogfood corpus status is invalid", path=data_path)
    tasks = corpus.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise DogfoodAttemptsError("ERR_DOGFOOD_ATTEMPTS_CORPUS_INVALID", "dogfood corpus tasks are missing", path=data_path)
    return corpus


def validate_metrics(metrics: Any, *, attempt_id: str) -> dict[str, Any]:
    if not isinstance(metrics, dict):
        raise DogfoodAttemptsError("ERR_DOGFOOD_ATTEMPTS_METRIC_INVALID", f"{attempt_id} metrics are missing")
    elapsed = metrics.get("elapsed_seconds")
    interruptions = metrics.get("interruptions")
    verification_passed = metrics.get("verification_passed")
    command_count = metrics.get("command_count")
    if not isinstance(elapsed, (int, float)) or elapsed < 0:
        raise DogfoodAttemptsError("ERR_DOGFOOD_ATTEMPTS_METRIC_INVALID", f"{attempt_id} elapsed_seconds is invalid")
    if not isinstance(interruptions, int) or interruptions < 0:
        raise DogfoodAttemptsError("ERR_DOGFOOD_ATTEMPTS_METRIC_INVALID", f"{attempt_id} interruptions is invalid")
    if not isinstance(verification_passed, bool):
        raise DogfoodAttemptsError("ERR_DOGFOOD_ATTEMPTS_METRIC_INVALID", f"{attempt_id} verification_passed is invalid")
    if not isinstance(command_count, int) or command_count < 1:
        raise DogfoodAttemptsError("ERR_DOGFOOD_ATTEMPTS_METRIC_INVALID", f"{attempt_id} command_count is invalid")
    return {
        "elapsed_seconds": elapsed,
        "interruptions": interruptions,
        "verification_passed": verification_passed,
        "command_count": command_count,
    }


def validate_attempts(raw: Any, corpus: dict[str, Any]) -> list[dict[str, Any]]:
    attempts = raw.get("attempts") if isinstance(raw, dict) else raw
    if not isinstance(attempts, list) or not attempts:
        raise DogfoodAttemptsError("ERR_DOGFOOD_ATTEMPTS_SCHEMA_INVALID", "attempts must be a non-empty list")
    tasks_by_id = {task["id"]: task for task in corpus["tasks"]}
    seen: set[tuple[str, str]] = set()
    normalized: list[dict[str, Any]] = []
    for attempt in attempts:
        if not isinstance(attempt, dict):
            raise DogfoodAttemptsError("ERR_DOGFOOD_ATTEMPTS_SCHEMA_INVALID", "attempt must be an object")
        task_id = attempt.get("task_id")
        mode = attempt.get("mode")
        if task_id not in tasks_by_id:
            raise DogfoodAttemptsError("ERR_DOGFOOD_ATTEMPTS_UNKNOWN_TASK", "attempt task is not in the dogfood corpus", path=str(task_id))
        if mode not in REQUIRED_MODES:
            raise DogfoodAttemptsError("ERR_DOGFOOD_ATTEMPTS_MODE_INVALID", "attempt mode is not supported", path=str(mode))
        key = (task_id, mode)
        if key in seen:
            raise DogfoodAttemptsError("ERR_DOGFOOD_ATTEMPTS_SCHEMA_INVALID", f"duplicate attempt for {task_id}/{mode}")
        seen.add(key)
        claim_text = " ".join(str(attempt.get(key_name, "")) for key_name in ["summary", "claim", "notes"]).lower()
        if attempt.get("public_claim") is True or any(term in claim_text for term in FORBIDDEN_CLAIM_TERMS):
            raise DogfoodAttemptsError("ERR_DOGFOOD_ATTEMPTS_OVERCLAIM", "dogfood attempt includes unsupported public claim", path=f"{task_id}/{mode}")
        evidence_path = attempt.get("evidence_path")
        if not isinstance(evidence_path, str) or not evidence_path:
            raise DogfoodAttemptsError("ERR_DOGFOOD_ATTEMPTS_EVIDENCE_MISSING", "evidence_path is missing", path=f"{task_id}/{mode}")
        evidence_file = safe_repo_file(evidence_path)
        normalized.append(
            {
                "task_id": task_id,
                "mode": mode,
                "status": "measured",
                "metrics": validate_metrics(attempt.get("metrics"), attempt_id=f"{task_id}/{mode}"),
                "evidence_path": evidence_path,
                "evidence_hash": canonical_hash(evidence_file.read_text()),
                "summary": str(attempt.get("summary", "")),
                "recorded_at": str(attempt.get("recorded_at") or now_utc()),
            }
        )
    return normalized


def build_mode_summary(attempts: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for mode in REQUIRED_MODES:
        mode_attempts = [attempt for attempt in attempts if attempt["mode"] == mode]
        verified = [attempt for attempt in mode_attempts if attempt["metrics"]["verification_passed"]]
        summary[mode] = {
            "attempt_count": len(mode_attempts),
            "verified_count": len(verified),
            "elapsed_seconds_total": sum(attempt["metrics"]["elapsed_seconds"] for attempt in mode_attempts),
            "interruptions_total": sum(attempt["metrics"]["interruptions"] for attempt in mode_attempts),
            "status": "measured" if mode_attempts else "not-run",
        }
    return summary


def render_readme(record: dict[str, Any]) -> str:
    lines = [
        "# DWM Dogfood Attempts",
        "",
        f"- attempt: `{record['attempt_id']}`",
        f"- corpus: `{record['corpus_path']}`",
        f"- decision: `{record['decision']}`",
        "- claim policy: local dogfood evidence only; not an external benchmark authority",
        "",
        "## Mode Summary",
        "",
    ]
    for mode, summary in record["mode_summary"].items():
        lines.append(f"- `{mode}`: {summary['attempt_count']} measured, {summary['verified_count']} verified")
    lines.extend(["", "## Attempts", ""])
    for attempt in record["attempts"]:
        metrics = attempt["metrics"]
        lines.append(f"- `{attempt['task_id']}` / `{attempt['mode']}`: verification={metrics['verification_passed']} elapsed={metrics['elapsed_seconds']}")
    lines.append("")
    return "\n".join(lines)


def record_attempts(corpus_dir: Path, attempts_path: Path, out_dir: Path) -> dict[str, Any]:
    corpus_dir = resolve_corpus(corpus_dir)
    out_dir = resolve_out(out_dir)
    attempt_id = out_dir.name
    corpus = load_corpus(corpus_dir)
    raw_attempts = read_json(attempts_path)
    attempts = validate_attempts(raw_attempts, corpus)
    prepare_out_dir(out_dir, attempt_id, source=attempts_path)
    mode_summary = build_mode_summary(attempts)
    record = {
        "tool": TOOL,
        "schema_version": SCHEMA_VERSION,
        "dogfood_attempts_version": DOGFOOD_ATTEMPTS_VERSION,
        "status": "dogfood-attempts-recorded",
        "decision": "measured-local-evidence",
        "attempt_id": attempt_id,
        "corpus_id": corpus["corpus_id"],
        "corpus_path": rel(corpus_dir),
        "attempt_count": len(attempts),
        "attempts": attempts,
        "mode_summary": mode_summary,
        "external_claim_policy": "local dogfood evidence only; not an external benchmark authority",
        "source_hashes": {
            "corpus": canonical_hash(corpus),
            "attempts": canonical_hash(raw_attempts),
        },
    }
    write_json_atomic(out_dir / "dogfood-attempts.json", record, root=out_dir)
    write_json_atomic(out_dir / "comparison-ledger.json", record, root=out_dir)
    write_json_atomic(out_dir / "status.json", record, root=out_dir)
    (out_dir / "README.md").write_text(render_readme(record))
    return record


def fixture_attempts(evidence_path: str, *, task_id: str = "v44-candidate-review-gate", mode: str = "dwm-controlled") -> dict[str, Any]:
    return {
        "attempts": [
            {
                "task_id": task_id,
                "mode": mode,
                "evidence_path": evidence_path,
                "metrics": {
                    "elapsed_seconds": 42.0,
                    "interruptions": 0,
                    "verification_passed": True,
                    "command_count": 3,
                },
                "summary": "local measured attempt fixture",
            }
        ]
    }


def blocked_fixture_status(kind: str, fixture: dict[str, Any], suite_dir: Path) -> dict[str, Any]:
    try:
        corpus_dir = DOGFOOD_ROOT / f"{suite_dir.name}-{kind}-corpus"
        build_corpus(default_tasks(), corpus_dir, corpus_id=corpus_dir.name, source=Path("fixture"))
        evidence_dir = suite_dir / "evidence"
        evidence_dir.mkdir(parents=True, exist_ok=True)
        evidence = evidence_dir / f"{kind}.txt"
        evidence.write_text("fixture evidence\n")
        attempts = fixture_attempts(rel(evidence))
        if kind == "unknown-task":
            attempts = fixture_attempts(rel(evidence), task_id="unknown-task")
        elif kind == "missing-evidence":
            attempts = fixture_attempts("out/dogfood-attempts/missing-evidence.txt")
        elif kind == "invalid-metric":
            attempts = fixture_attempts(rel(evidence))
            attempts["attempts"][0]["metrics"]["elapsed_seconds"] = -1
        elif kind == "overclaim":
            attempts = fixture_attempts(rel(evidence))
            attempts["attempts"][0]["summary"] = "DWM beats Codex on an external benchmark."
        else:
            raise DogfoodAttemptsError("ERR_DOGFOOD_ATTEMPTS_FIXTURE_FAILED", f"unknown blocked fixture kind: {kind}")
        attempts_path = suite_dir / f"{kind}-attempts.json"
        write_json_atomic(attempts_path, attempts, root=suite_dir)
        record_attempts(corpus_dir, attempts_path, ATTEMPT_ROOT / f"{suite_dir.name}-{kind}")
    except DogfoodAttemptsError as exc:
        if fixture.get("expected_error") != exc.code:
            raise
        return {"status": "blocked", "error": exc.to_record()}
    raise DogfoodAttemptsError("ERR_DOGFOOD_ATTEMPTS_FIXTURE_FAILED", f"{kind} unexpectedly passed")


def run_fixture(fixture: dict[str, Any], suite_dir: Path) -> dict[str, Any]:
    fixture_id = fixture["id"]
    try:
        kind = fixture["kind"]
        if kind == "measured-attempt":
            corpus_dir = DOGFOOD_ROOT / f"{suite_dir.name}-{fixture_id}-corpus"
            build_corpus(default_tasks(), corpus_dir, corpus_id=corpus_dir.name, source=Path("fixture"))
            evidence_dir = suite_dir / "evidence"
            evidence_dir.mkdir(parents=True, exist_ok=True)
            evidence = evidence_dir / "measured-attempt.txt"
            evidence.write_text("fixture evidence\n")
            attempts_path = suite_dir / "measured-attempts.json"
            write_json_atomic(attempts_path, fixture_attempts(rel(evidence)), root=suite_dir)
            status = record_attempts(corpus_dir, attempts_path, suite_dir / fixture_id)
        elif kind in {"unknown-task", "missing-evidence", "invalid-metric", "overclaim"}:
            status = blocked_fixture_status(kind, fixture, suite_dir)
        else:
            raise DogfoodAttemptsError("ERR_DOGFOOD_ATTEMPTS_FIXTURE_FAILED", f"unknown fixture kind: {kind}")
        expected_status = fixture.get("expected_status")
        if expected_status is not None and status.get("status") != expected_status:
            raise DogfoodAttemptsError("ERR_DOGFOOD_ATTEMPTS_FIXTURE_FAILED", f"expected status {expected_status}, got {status.get('status')}")
        expected_error = fixture.get("expected_error")
        actual_error = status.get("error", {}).get("code") if isinstance(status.get("error"), dict) else None
        if expected_error is not None and actual_error != expected_error:
            raise DogfoodAttemptsError("ERR_DOGFOOD_ATTEMPTS_FIXTURE_FAILED", f"expected error {expected_error}, got {actual_error}")
        return {"id": fixture_id, "status": "pass", "observed_status": status.get("status"), "required": fixture.get("required", True)}
    except DogfoodAttemptsError as exc:
        record = exc.to_record()
        record["fixture_id"] = fixture_id
        return {"id": fixture_id, "status": "fail", "required": fixture.get("required", True), "error": record}


def evaluate_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    suite_id = Path(out_dir).name
    suite_dir = resolve_out(out_dir)
    if suite_dir.exists():
        sentinel = read_sentinel(suite_dir)
        if sentinel is None or sentinel.get("attempt_id") != suite_id:
            raise DogfoodAttemptsError("ERR_DOGFOOD_ATTEMPTS_PATH_UNSAFE", "existing dogfood attempts suite is not attempt-owned", path=suite_dir)
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
        raise DogfoodAttemptsError("ERR_DOGFOOD_ATTEMPTS_FIXTURE_FAILED", "manifest decision is kill", path=manifest_path)
    return summary


def self_test() -> None:
    ATTEMPT_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dwm-dogfood-attempts-self-test-", dir=ATTEMPT_ROOT) as tmp:
        summary = evaluate_manifest(ROOT / "fixtures" / "v54" / "manifest.json", Path(tmp) / "dogfood-attempts-self-test")
    if summary["decision"] != "keep":
        raise DogfoodAttemptsError("ERR_DOGFOOD_ATTEMPTS_FIXTURE_FAILED", "dogfood attempts self-test manifest did not keep")
    print("dwm_dogfood_attempts self-test: pass")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", choices=["record"])
    parser.add_argument("--attempts")
    parser.add_argument("--corpus")
    parser.add_argument("--manifest")
    parser.add_argument("--out")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
        elif args.manifest:
            if not args.out:
                raise DogfoodAttemptsError("ERR_DOGFOOD_ATTEMPTS_PATH_UNSAFE", "--manifest requires --out")
            summary = evaluate_manifest(Path(args.manifest), Path(args.out))
            print(canonical_json_text({key: summary[key] for key in ["suite_id", "fixture_count", "required_fixture_count", "required_passed", "passed", "failed", "skipped", "decision"]}))
        elif args.command == "record":
            if not args.out or not args.corpus or not args.attempts:
                raise DogfoodAttemptsError("ERR_DOGFOOD_ATTEMPTS_SCHEMA_INVALID", "record requires --corpus, --attempts, and --out")
            print(canonical_json_text(record_attempts(Path(args.corpus), Path(args.attempts), Path(args.out))))
        else:
            parser.error("expected --self-test, --manifest, or record")
    except DogfoodAttemptsError as exc:
        print(canonical_json_text(exc.to_record()), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
