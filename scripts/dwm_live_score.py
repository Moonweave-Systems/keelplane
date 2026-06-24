#!/usr/bin/env python3
"""V32 live score verifier bridge."""

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
from dwm_live_receipt import RECEIPT_ROOT, ingest_receipt, load_preflight, make_preflight_dir, synthetic_receipt_for  # noqa: E402
from dwm_live_receipt_judge import JUDGMENT_ROOT, judge_receipt  # noqa: E402


TOOL = "dwm_live_score.py"
SCHEMA_VERSION = "1.0"
SCORE_VERSION = "32.0.0"
SCORE_ROOT = ROOT / "out" / "live-scores"
SENTINEL = ".dwm_live_score-owned.json"


class LiveScoreError(ValueError):
    """Structured V32 live score failure."""

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
        raise LiveScoreError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise LiveScoreError(code, "path contains a symlink", path=current)


def resolve_score_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_LIVE_SCORE_PATH_UNSAFE", message="live score output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = SCORE_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise LiveScoreError("ERR_LIVE_SCORE_PATH_UNSAFE", f"live score output must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise LiveScoreError("ERR_LIVE_SCORE_PATH_UNSAFE", "live score output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_LIVE_SCORE_PATH_SYMLINK")
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


def prepare_out_dir(path: Path, score_id: str, *, source: Path) -> None:
    if path.exists():
        if path.is_symlink():
            raise LiveScoreError("ERR_LIVE_SCORE_PATH_SYMLINK", "live score output is a symlink", path=path)
        if not path.is_dir():
            raise LiveScoreError("ERR_LIVE_SCORE_PATH_UNSAFE", "live score output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("score_id") != score_id:
            raise LiveScoreError("ERR_LIVE_SCORE_PATH_UNSAFE", "existing live score output is not score-owned", path=path)
        shutil.rmtree(path)
    SCORE_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(
        path / SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "score_version": SCORE_VERSION,
            "score_id": score_id,
            "source_path": rel(source),
            "created_at": now_utc(),
        },
        root=path,
    )


def load_judgment(judgment_dir: Path) -> dict[str, Any]:
    judgment_path = judgment_dir / "judgment.json"
    status_path = judgment_dir / "status.json"
    if not judgment_path.is_file() or judgment_path.is_symlink() or not status_path.is_file() or status_path.is_symlink():
        raise LiveScoreError("ERR_LIVE_SCORE_ARTIFACT_MISSING", "judgment artifacts are missing", path=judgment_dir)
    judgment = read_json(judgment_path)
    status = read_json(status_path)
    if judgment != status:
        raise LiveScoreError("ERR_LIVE_SCORE_STALE_JUDGMENT", "judgment status and artifact do not match", path=judgment_dir)
    if judgment.get("status") != "judgment-recorded":
        raise LiveScoreError("ERR_LIVE_SCORE_JUDGMENT_NOT_READY", "judgment is not ready for scoring", path=judgment_dir)
    return judgment


def load_receipt(receipt_dir: Path) -> dict[str, Any]:
    receipt_path = receipt_dir / "receipt.json"
    ledger_path = receipt_dir / "receipt-ledger.json"
    if not receipt_path.is_file() or receipt_path.is_symlink() or not ledger_path.is_file() or ledger_path.is_symlink():
        raise LiveScoreError("ERR_LIVE_SCORE_ARTIFACT_MISSING", "receipt artifacts are missing", path=receipt_dir)
    receipt = read_json(receipt_path)
    ledger = read_json(ledger_path)
    if ledger.get("source_hashes", {}).get("receipt") != canonical_hash(receipt):
        raise LiveScoreError("ERR_LIVE_SCORE_HASH_MISMATCH", "receipt hash does not match receipt ledger", path=receipt_dir)
    return receipt


def validate_verification_spec(spec: dict[str, Any], *, path: Path | str) -> dict[str, Any]:
    if spec.get("schema_version") != SCHEMA_VERSION:
        raise LiveScoreError("ERR_LIVE_SCORE_VERIFICATION_INVALID", "verification spec schema is unsupported", path=path)
    required = ["task_id", "adapter", "expected_returncode", "expected_stdout_hash", "expected_stderr_hash"]
    missing = [key for key in required if key not in spec]
    if missing:
        raise LiveScoreError("ERR_LIVE_SCORE_VERIFICATION_INVALID", f"verification spec missing fields: {missing}", path=path)
    if not isinstance(spec["expected_returncode"], int):
        raise LiveScoreError("ERR_LIVE_SCORE_VERIFICATION_INVALID", "expected_returncode must be an integer", path=path)
    for key in ["task_id", "adapter", "expected_stdout_hash", "expected_stderr_hash"]:
        if not isinstance(spec[key], str) or not spec[key]:
            raise LiveScoreError("ERR_LIVE_SCORE_VERIFICATION_INVALID", f"{key} must be non-empty text", path=path)
    return spec


def score_live_judgment(
    judgment_dir: Path,
    receipt_dir: Path,
    verification_spec: dict[str, Any],
    out_dir: Path,
    *,
    score_id: str,
    expected_judgment_hash: str | None = None,
) -> dict[str, Any]:
    judgment = load_judgment(judgment_dir)
    receipt = load_receipt(receipt_dir)
    verification_spec = validate_verification_spec(verification_spec, path="<synthetic>")
    judgment_hash = canonical_hash(judgment)
    if expected_judgment_hash is not None and expected_judgment_hash != judgment_hash:
        raise LiveScoreError("ERR_LIVE_SCORE_STALE_JUDGMENT", "expected judgment hash does not match current judgment", path=judgment_dir)
    if judgment.get("source_hashes", {}).get("receipt") != canonical_hash(receipt):
        raise LiveScoreError("ERR_LIVE_SCORE_HASH_MISMATCH", "judgment receipt hash does not match receipt artifact", path=judgment_dir)
    if verification_spec["task_id"] != judgment.get("task_id") or verification_spec["adapter"] != judgment.get("adapter"):
        raise LiveScoreError("ERR_LIVE_SCORE_TASK_MISMATCH", "verification spec task or adapter does not match judgment", path=judgment_dir)
    prepare_out_dir(out_dir, score_id, source=judgment_dir)
    checks = {
        "returncode": receipt.get("returncode") == verification_spec["expected_returncode"],
        "stdout_hash": receipt.get("stdout_hash") == verification_spec["expected_stdout_hash"],
        "stderr_hash": receipt.get("stderr_hash") == verification_spec["expected_stderr_hash"],
    }
    verification_status = "passed" if all(checks.values()) else "failed"
    score = {
        "status": "score-recorded",
        "verification_status": verification_status,
        "score": 1 if verification_status == "passed" else 0,
        "task_id": judgment.get("task_id"),
        "adapter": judgment.get("adapter"),
        "runner": judgment.get("runner"),
        "checks": checks,
        "benchmark_success_claimed": False,
        "source_hashes": {
            "judgment": judgment_hash,
            "receipt": canonical_hash(receipt),
            "verification_spec": canonical_hash(verification_spec),
        },
    }
    write_json_atomic(out_dir / "score.json", score, root=out_dir)
    write_json_atomic(out_dir / "status.json", score, root=out_dir)
    return score


def make_scoring_inputs(base_name: str, *, returncode: int = 0) -> tuple[Path, Path, dict[str, Any]]:
    preflight_dir = make_preflight_dir(f"{base_name}-preflight")
    preflight = load_preflight(preflight_dir)
    receipt = synthetic_receipt_for(preflight)
    receipt["returncode"] = returncode
    receipt_dir = RECEIPT_ROOT / f"{base_name}-receipt"
    ingest_receipt(preflight_dir, receipt, receipt_dir, receipt_id=receipt_dir.name)
    judgment_dir = JUDGMENT_ROOT / f"{base_name}-judgment"
    judge_receipt(receipt_dir, judgment_dir, judgment_id=judgment_dir.name)
    verification_spec = {
        "schema_version": SCHEMA_VERSION,
        "task_id": preflight["task_id"],
        "adapter": preflight["adapter"],
        "expected_returncode": returncode,
        "expected_stdout_hash": receipt["stdout_hash"],
        "expected_stderr_hash": receipt["stderr_hash"],
    }
    return judgment_dir, receipt_dir, verification_spec


def blocked_fixture_status(kind: str, fixture: dict[str, Any], suite_id: str) -> dict[str, Any]:
    try:
        if kind == "stale-judgment":
            judgment_dir, receipt_dir, spec = make_scoring_inputs(f"{suite_id}-stale")
            score_live_judgment(
                judgment_dir,
                receipt_dir,
                spec,
                SCORE_ROOT / f"{suite_id}-stale",
                score_id=f"{suite_id}-stale",
                expected_judgment_hash=str(fixture["expected_judgment_hash"]),
            )
        elif kind == "task-mismatch":
            judgment_dir, receipt_dir, spec = make_scoring_inputs(f"{suite_id}-task-mismatch")
            spec["task_id"] = "wrong-task"
            score_live_judgment(judgment_dir, receipt_dir, spec, SCORE_ROOT / f"{suite_id}-task-mismatch", score_id=f"{suite_id}-task-mismatch")
        elif kind == "hash-mismatch":
            judgment_dir, receipt_dir, spec = make_scoring_inputs(f"{suite_id}-hash-mismatch")
            receipt_path = receipt_dir / "receipt.json"
            receipt = read_json(receipt_path)
            receipt["stdout_hash"] = "changed-after-judgment"
            write_json_atomic(receipt_path, receipt, root=receipt_dir)
            score_live_judgment(judgment_dir, receipt_dir, spec, SCORE_ROOT / f"{suite_id}-hash-mismatch", score_id=f"{suite_id}-hash-mismatch")
        elif kind == "missing-artifact":
            missing_dir = JUDGMENT_ROOT / f"{suite_id}-missing"
            if missing_dir.exists():
                shutil.rmtree(missing_dir)
            missing_dir.mkdir(parents=True)
            _, receipt_dir, spec = make_scoring_inputs(f"{suite_id}-missing-source")
            score_live_judgment(missing_dir, receipt_dir, spec, SCORE_ROOT / f"{suite_id}-missing", score_id=f"{suite_id}-missing")
        elif kind == "verification-invalid":
            judgment_dir, receipt_dir, spec = make_scoring_inputs(f"{suite_id}-verification-invalid")
            spec.pop("expected_stdout_hash")
            score_live_judgment(judgment_dir, receipt_dir, spec, SCORE_ROOT / f"{suite_id}-verification-invalid", score_id=f"{suite_id}-verification-invalid")
        else:
            raise LiveScoreError("ERR_LIVE_SCORE_FIXTURE_FAILED", f"unknown blocked fixture kind: {kind}")
    except LiveScoreError as exc:
        if fixture.get("expected_error") != exc.code:
            raise
        return {"status": "blocked", "error": exc.to_record()}
    raise LiveScoreError("ERR_LIVE_SCORE_FIXTURE_FAILED", f"{kind} unexpectedly passed")


def run_fixture(fixture: dict[str, Any], suite_dir: Path) -> dict[str, Any]:
    fixture_id = fixture["id"]
    try:
        kind = fixture["kind"]
        if kind == "score-passed":
            judgment_dir, receipt_dir, spec = make_scoring_inputs(f"{suite_dir.name}-{fixture_id}", returncode=0)
            status = score_live_judgment(judgment_dir, receipt_dir, spec, suite_dir / fixture_id, score_id=fixture_id)
        elif kind == "score-failed":
            judgment_dir, receipt_dir, spec = make_scoring_inputs(f"{suite_dir.name}-{fixture_id}", returncode=1)
            spec["expected_returncode"] = 0
            status = score_live_judgment(judgment_dir, receipt_dir, spec, suite_dir / fixture_id, score_id=fixture_id)
        elif kind in {"stale-judgment", "task-mismatch", "hash-mismatch", "missing-artifact", "verification-invalid"}:
            status = blocked_fixture_status(kind, fixture, suite_dir.name)
        else:
            raise LiveScoreError("ERR_LIVE_SCORE_FIXTURE_FAILED", f"unknown fixture kind: {kind}")
        expected_status = fixture.get("expected_status")
        if expected_status is not None and status.get("status") != expected_status:
            raise LiveScoreError("ERR_LIVE_SCORE_FIXTURE_FAILED", f"expected status {expected_status}, got {status.get('status')}")
        expected_verification_status = fixture.get("expected_verification_status")
        if expected_verification_status is not None and status.get("verification_status") != expected_verification_status:
            raise LiveScoreError("ERR_LIVE_SCORE_FIXTURE_FAILED", f"expected verification_status {expected_verification_status}, got {status.get('verification_status')}")
        expected_error = fixture.get("expected_error")
        actual_error = status.get("error", {}).get("code") if isinstance(status.get("error"), dict) else None
        if expected_error is not None and actual_error != expected_error:
            raise LiveScoreError("ERR_LIVE_SCORE_FIXTURE_FAILED", f"expected error {expected_error}, got {actual_error}")
        return {"id": fixture_id, "status": "pass", "observed_status": status.get("status"), "required": fixture.get("required", True)}
    except LiveScoreError as exc:
        record = exc.to_record()
        record["fixture_id"] = fixture_id
        return {"id": fixture_id, "status": "fail", "required": fixture.get("required", True), "error": record}


def evaluate_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    suite_id = Path(out_dir).name
    suite_dir = resolve_score_out(out_dir)
    if suite_dir.exists():
        sentinel = read_sentinel(suite_dir)
        if sentinel is None or sentinel.get("score_id") != suite_id:
            raise LiveScoreError("ERR_LIVE_SCORE_PATH_UNSAFE", "existing live score suite is not score-owned", path=suite_dir)
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
        raise LiveScoreError("ERR_LIVE_SCORE_FIXTURE_FAILED", "manifest decision is kill", path=manifest_path)
    return summary


def self_test() -> None:
    SCORE_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dwm-live-score-self-test-", dir=SCORE_ROOT) as tmp:
        summary = evaluate_manifest(ROOT / "fixtures" / "v32" / "manifest.json", Path(tmp) / "live-score-self-test")
    if summary["decision"] != "keep":
        raise LiveScoreError("ERR_LIVE_SCORE_FIXTURE_FAILED", "live score self-test manifest did not keep")
    print("dwm_live_score self-test: pass")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", choices=["score"])
    parser.add_argument("--expected-judgment-hash")
    parser.add_argument("--judgment-dir")
    parser.add_argument("--manifest")
    parser.add_argument("--out")
    parser.add_argument("--receipt-dir")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--verification")
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
        elif args.manifest:
            if not args.out:
                raise LiveScoreError("ERR_LIVE_SCORE_PATH_UNSAFE", "--manifest requires --out")
            summary = evaluate_manifest(Path(args.manifest), Path(args.out))
            print(canonical_json_text({key: summary[key] for key in ["suite_id", "fixture_count", "required_fixture_count", "required_passed", "passed", "failed", "skipped", "decision"]}))
        elif args.command == "score":
            if not args.out or not args.judgment_dir or not args.receipt_dir or not args.verification:
                raise LiveScoreError("ERR_LIVE_SCORE_PATH_UNSAFE", "score requires --judgment-dir, --receipt-dir, --verification, and --out")
            status = score_live_judgment(
                Path(args.judgment_dir),
                Path(args.receipt_dir),
                validate_verification_spec(read_json(Path(args.verification)), path=Path(args.verification)),
                resolve_score_out(args.out),
                score_id=Path(args.out).name,
                expected_judgment_hash=args.expected_judgment_hash,
            )
            print(canonical_json_text(status))
        else:
            parser.error("expected --self-test, --manifest, or score")
    except LiveScoreError as exc:
        print(canonical_json_text(exc.to_record()), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
