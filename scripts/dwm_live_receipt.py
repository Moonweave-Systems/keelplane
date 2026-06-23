#!/usr/bin/env python3
"""V30 live execution receipt ingestion."""

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
from dwm_live_attempt_plan import PLAN_ROOT as ATTEMPT_PLAN_ROOT, plan_live_attempt, resolve_plan_out  # noqa: E402
from dwm_live_runner_preflight import PREFLIGHT_ROOT as RUNNER_PREFLIGHT_ROOT, preflight_plan, resolve_preflight_out  # noqa: E402


TOOL = "dwm_live_receipt.py"
SCHEMA_VERSION = "1.0"
RECEIPT_VERSION = "30.0.0"
RECEIPT_ROOT = ROOT / "out" / "live-receipts"
SENTINEL = ".dwm_live_receipt-owned.json"


class LiveReceiptError(ValueError):
    """Structured V30 receipt ingestion failure."""

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
        raise LiveReceiptError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise LiveReceiptError(code, "path contains a symlink", path=current)


def resolve_receipt_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_LIVE_RECEIPT_PATH_UNSAFE", message="live receipt output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = RECEIPT_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise LiveReceiptError("ERR_LIVE_RECEIPT_PATH_UNSAFE", f"live receipt output must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise LiveReceiptError("ERR_LIVE_RECEIPT_PATH_UNSAFE", "live receipt output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_LIVE_RECEIPT_PATH_SYMLINK")
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


def prepare_out_dir(path: Path, receipt_id: str, *, source: Path) -> None:
    if path.exists():
        if path.is_symlink():
            raise LiveReceiptError("ERR_LIVE_RECEIPT_PATH_SYMLINK", "live receipt output is a symlink", path=path)
        if not path.is_dir():
            raise LiveReceiptError("ERR_LIVE_RECEIPT_PATH_UNSAFE", "live receipt output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("receipt_id") != receipt_id:
            raise LiveReceiptError("ERR_LIVE_RECEIPT_PATH_UNSAFE", "existing live receipt output is not receipt-owned", path=path)
        shutil.rmtree(path)
    RECEIPT_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(
        path / SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "receipt_version": RECEIPT_VERSION,
            "receipt_id": receipt_id,
            "source_path": rel(source),
            "created_at": now_utc(),
        },
        root=path,
    )


def load_preflight(preflight_dir: Path) -> dict[str, Any]:
    preflight_path = preflight_dir / "preflight.json"
    status_path = preflight_dir / "status.json"
    if not status_path.is_file() or status_path.is_symlink():
        raise LiveReceiptError("ERR_LIVE_RECEIPT_ARTIFACT_MISSING", "preflight artifacts are missing", path=preflight_dir)
    if not preflight_path.is_file() or preflight_path.is_symlink():
        status = read_json(status_path)
        if status.get("status") == "skipped":
            return status
        raise LiveReceiptError("ERR_LIVE_RECEIPT_ARTIFACT_MISSING", "preflight artifact is missing", path=preflight_dir)
    preflight = read_json(preflight_path)
    status = read_json(status_path)
    if preflight != status:
        raise LiveReceiptError("ERR_LIVE_RECEIPT_STALE_PREFLIGHT", "preflight status and artifact do not match", path=preflight_dir)
    return preflight


def validate_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    if receipt.get("schema_version") != SCHEMA_VERSION:
        raise LiveReceiptError("ERR_LIVE_RECEIPT_MALFORMED", "receipt schema version is unsupported")
    required = ["command_hash", "returncode", "stdout_hash", "stderr_hash", "duration_ms", "runner"]
    missing = [key for key in required if key not in receipt]
    if missing:
        raise LiveReceiptError("ERR_LIVE_RECEIPT_MALFORMED", f"receipt missing fields: {missing}")
    if not isinstance(receipt["returncode"], int) or not isinstance(receipt["duration_ms"], int):
        raise LiveReceiptError("ERR_LIVE_RECEIPT_MALFORMED", "receipt returncode and duration_ms must be integers")
    for key in ["command_hash", "stdout_hash", "stderr_hash", "runner"]:
        if not isinstance(receipt[key], str) or not receipt[key]:
            raise LiveReceiptError("ERR_LIVE_RECEIPT_MALFORMED", f"receipt {key} must be non-empty text")
    return receipt


def synthetic_receipt_for(preflight: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "runner": "fixture-manual-run",
        "command_hash": canonical_hash(preflight["command"]),
        "returncode": 0,
        "stdout_hash": canonical_hash("fixture stdout"),
        "stderr_hash": canonical_hash(""),
        "duration_ms": 1,
    }


def ingest_receipt(
    preflight_dir: Path,
    receipt: dict[str, Any],
    out_dir: Path,
    *,
    receipt_id: str,
    expected_preflight_hash: str | None = None,
) -> dict[str, Any]:
    preflight = load_preflight(preflight_dir)
    preflight_hash = canonical_hash(preflight)
    if expected_preflight_hash is not None and expected_preflight_hash != preflight_hash:
        raise LiveReceiptError("ERR_LIVE_RECEIPT_STALE_PREFLIGHT", "expected preflight hash does not match current preflight", path=preflight_dir)
    if preflight.get("status") != "ready-for-human-run":
        raise LiveReceiptError("ERR_LIVE_RECEIPT_PREFLIGHT_NOT_READY", "preflight is not ready for human run", path=preflight_dir)
    receipt = validate_receipt(receipt)
    command_hash = canonical_hash(preflight["command"])
    if receipt["command_hash"] != command_hash:
        raise LiveReceiptError("ERR_LIVE_RECEIPT_COMMAND_MISMATCH", "receipt command hash does not match preflight command", path=preflight_dir)
    prepare_out_dir(out_dir, receipt_id, source=preflight_dir)
    status = {
        "status": "receipt-accepted",
        "adapter": preflight.get("adapter"),
        "task_id": preflight.get("task_id"),
        "runner": receipt["runner"],
        "returncode": receipt["returncode"],
        "source_hashes": {
            "preflight": preflight_hash,
            "receipt": canonical_hash(receipt),
            "command": command_hash,
        },
        "benchmark_success_claimed": False,
    }
    write_json_atomic(out_dir / "receipt.json", receipt, root=out_dir)
    write_json_atomic(out_dir / "receipt-ledger.json", status, root=out_dir)
    write_json_atomic(out_dir / "status.json", status, root=out_dir)
    return status


def make_preflight_dir(base_name: str, *, adapter_command: str = "python", task_id: str = "failing-test-fix") -> Path:
    plan_dir = resolve_plan_out(ATTEMPT_PLAN_ROOT / f"{base_name}-plan")
    plan_live_attempt(plan_dir, plan_id=plan_dir.name, adapter_command=adapter_command, task_id=task_id)
    preflight_dir = resolve_preflight_out(RUNNER_PREFLIGHT_ROOT / f"{base_name}-preflight")
    preflight_plan(plan_dir, preflight_dir, preflight_id=preflight_dir.name)
    return preflight_dir


def blocked_fixture_status(kind: str, fixture: dict[str, Any], suite_id: str) -> dict[str, Any]:
    try:
        if kind == "preflight-not-ready":
            preflight_dir = make_preflight_dir(f"{suite_id}-not-ready", adapter_command=str(fixture["adapter_command"]))
            receipt = {"schema_version": SCHEMA_VERSION, "runner": "fixture", "command_hash": "missing", "returncode": 0, "stdout_hash": "x", "stderr_hash": "x", "duration_ms": 1}
            ingest_receipt(preflight_dir, receipt, RECEIPT_ROOT / f"{suite_id}-not-ready", receipt_id=f"{suite_id}-not-ready")
        elif kind == "stale-preflight":
            preflight_dir = make_preflight_dir(f"{suite_id}-stale")
            receipt = synthetic_receipt_for(load_preflight(preflight_dir))
            ingest_receipt(
                preflight_dir,
                receipt,
                RECEIPT_ROOT / f"{suite_id}-stale",
                receipt_id=f"{suite_id}-stale",
                expected_preflight_hash=str(fixture["expected_preflight_hash"]),
            )
        elif kind == "command-mismatch":
            preflight_dir = make_preflight_dir(f"{suite_id}-command-mismatch")
            receipt = synthetic_receipt_for(load_preflight(preflight_dir))
            receipt["command_hash"] = "mismatched-command-hash"
            ingest_receipt(preflight_dir, receipt, RECEIPT_ROOT / f"{suite_id}-command-mismatch", receipt_id=f"{suite_id}-command-mismatch")
        elif kind == "missing-artifact":
            missing_dir = RUNNER_PREFLIGHT_ROOT / f"{suite_id}-missing"
            if missing_dir.exists():
                shutil.rmtree(missing_dir)
            missing_dir.mkdir(parents=True)
            receipt = {"schema_version": SCHEMA_VERSION, "runner": "fixture", "command_hash": "missing", "returncode": 0, "stdout_hash": "x", "stderr_hash": "x", "duration_ms": 1}
            ingest_receipt(missing_dir, receipt, RECEIPT_ROOT / f"{suite_id}-missing", receipt_id=f"{suite_id}-missing")
        else:
            raise LiveReceiptError("ERR_LIVE_RECEIPT_FIXTURE_FAILED", f"unknown blocked fixture kind: {kind}")
    except LiveReceiptError as exc:
        if fixture.get("expected_error") != exc.code:
            raise
        return {"status": "blocked", "error": exc.to_record()}
    raise LiveReceiptError("ERR_LIVE_RECEIPT_FIXTURE_FAILED", f"{kind} unexpectedly passed")


def run_fixture(fixture: dict[str, Any], suite_dir: Path) -> dict[str, Any]:
    fixture_id = fixture["id"]
    try:
        kind = fixture["kind"]
        if kind == "receipt-accepted":
            preflight_dir = make_preflight_dir(f"{suite_dir.name}-{fixture_id}", adapter_command=str(fixture["adapter_command"]), task_id=str(fixture["task_id"]))
            receipt = synthetic_receipt_for(load_preflight(preflight_dir))
            status = ingest_receipt(preflight_dir, receipt, suite_dir / fixture_id, receipt_id=fixture_id)
        elif kind in {"preflight-not-ready", "stale-preflight", "command-mismatch", "missing-artifact"}:
            status = blocked_fixture_status(kind, fixture, suite_dir.name)
        else:
            raise LiveReceiptError("ERR_LIVE_RECEIPT_FIXTURE_FAILED", f"unknown fixture kind: {kind}")
        expected_status = fixture.get("expected_status")
        if expected_status is not None and status.get("status") != expected_status:
            raise LiveReceiptError("ERR_LIVE_RECEIPT_FIXTURE_FAILED", f"expected status {expected_status}, got {status.get('status')}")
        expected_error = fixture.get("expected_error")
        actual_error = status.get("error", {}).get("code") if isinstance(status.get("error"), dict) else None
        if expected_error is not None and actual_error != expected_error:
            raise LiveReceiptError("ERR_LIVE_RECEIPT_FIXTURE_FAILED", f"expected error {expected_error}, got {actual_error}")
        return {"id": fixture_id, "status": "pass", "observed_status": status.get("status"), "required": fixture.get("required", True)}
    except LiveReceiptError as exc:
        record = exc.to_record()
        record["fixture_id"] = fixture_id
        return {"id": fixture_id, "status": "fail", "required": fixture.get("required", True), "error": record}


def evaluate_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    suite_id = Path(out_dir).name
    suite_dir = resolve_receipt_out(out_dir)
    if suite_dir.exists():
        sentinel = read_sentinel(suite_dir)
        if sentinel is None or sentinel.get("receipt_id") != suite_id:
            raise LiveReceiptError("ERR_LIVE_RECEIPT_PATH_UNSAFE", "existing live receipt suite is not receipt-owned", path=suite_dir)
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
        raise LiveReceiptError("ERR_LIVE_RECEIPT_FIXTURE_FAILED", "manifest decision is kill", path=manifest_path)
    return summary


def self_test() -> None:
    RECEIPT_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dwm-live-receipt-self-test-", dir=RECEIPT_ROOT) as tmp:
        summary = evaluate_manifest(ROOT / "fixtures" / "v30" / "manifest.json", Path(tmp) / "live-receipt-self-test")
    if summary["decision"] != "keep":
        raise LiveReceiptError("ERR_LIVE_RECEIPT_FIXTURE_FAILED", "live receipt self-test manifest did not keep")
    print("dwm_live_receipt self-test: pass")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", choices=["ingest"])
    parser.add_argument("--expected-preflight-hash")
    parser.add_argument("--manifest")
    parser.add_argument("--out")
    parser.add_argument("--preflight")
    parser.add_argument("--receipt")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
        elif args.manifest:
            if not args.out:
                raise LiveReceiptError("ERR_LIVE_RECEIPT_PATH_UNSAFE", "--manifest requires --out")
            summary = evaluate_manifest(Path(args.manifest), Path(args.out))
            print(canonical_json_text({key: summary[key] for key in ["suite_id", "fixture_count", "required_fixture_count", "required_passed", "passed", "failed", "skipped", "decision"]}))
        elif args.command == "ingest":
            if not args.out or not args.preflight or not args.receipt:
                raise LiveReceiptError("ERR_LIVE_RECEIPT_PATH_UNSAFE", "ingest requires --preflight, --receipt, and --out")
            status = ingest_receipt(
                Path(args.preflight),
                read_json(Path(args.receipt)),
                resolve_receipt_out(args.out),
                receipt_id=Path(args.out).name,
                expected_preflight_hash=args.expected_preflight_hash,
            )
            print(canonical_json_text(status))
        else:
            parser.error("expected --self-test, --manifest, or ingest")
    except LiveReceiptError as exc:
        print(canonical_json_text(exc.to_record()), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
