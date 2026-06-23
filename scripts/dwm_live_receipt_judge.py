#!/usr/bin/env python3
"""V31 live receipt judgment gate."""

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


TOOL = "dwm_live_receipt_judge.py"
SCHEMA_VERSION = "1.0"
JUDGE_VERSION = "31.0.0"
JUDGMENT_ROOT = ROOT / "out" / "live-receipt-judgments"
SENTINEL = ".dwm_live_receipt_judge-owned.json"


class LiveReceiptJudgeError(ValueError):
    """Structured V31 receipt judgment failure."""

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
        raise LiveReceiptJudgeError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise LiveReceiptJudgeError(code, "path contains a symlink", path=current)


def resolve_judgment_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_LIVE_RECEIPT_JUDGE_PATH_UNSAFE", message="live receipt judgment output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = JUDGMENT_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise LiveReceiptJudgeError("ERR_LIVE_RECEIPT_JUDGE_PATH_UNSAFE", f"live receipt judgment output must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise LiveReceiptJudgeError("ERR_LIVE_RECEIPT_JUDGE_PATH_UNSAFE", "live receipt judgment output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_LIVE_RECEIPT_JUDGE_PATH_SYMLINK")
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


def prepare_out_dir(path: Path, judgment_id: str, *, source: Path) -> None:
    if path.exists():
        if path.is_symlink():
            raise LiveReceiptJudgeError("ERR_LIVE_RECEIPT_JUDGE_PATH_SYMLINK", "live receipt judgment output is a symlink", path=path)
        if not path.is_dir():
            raise LiveReceiptJudgeError("ERR_LIVE_RECEIPT_JUDGE_PATH_UNSAFE", "live receipt judgment output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("judgment_id") != judgment_id:
            raise LiveReceiptJudgeError("ERR_LIVE_RECEIPT_JUDGE_PATH_UNSAFE", "existing live receipt judgment output is not judge-owned", path=path)
        shutil.rmtree(path)
    JUDGMENT_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(
        path / SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "judge_version": JUDGE_VERSION,
            "judgment_id": judgment_id,
            "source_path": rel(source),
            "created_at": now_utc(),
        },
        root=path,
    )


def load_receipt_bundle(receipt_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    receipt_path = receipt_dir / "receipt.json"
    ledger_path = receipt_dir / "receipt-ledger.json"
    status_path = receipt_dir / "status.json"
    if (
        not receipt_path.is_file()
        or receipt_path.is_symlink()
        or not ledger_path.is_file()
        or ledger_path.is_symlink()
        or not status_path.is_file()
        or status_path.is_symlink()
    ):
        raise LiveReceiptJudgeError("ERR_LIVE_RECEIPT_JUDGE_ARTIFACT_MISSING", "receipt artifacts are missing", path=receipt_dir)
    receipt = read_json(receipt_path)
    ledger = read_json(ledger_path)
    status = read_json(status_path)
    if ledger != status:
        raise LiveReceiptJudgeError("ERR_LIVE_RECEIPT_JUDGE_STALE_RECEIPT", "receipt ledger and status do not match", path=receipt_dir)
    return receipt, ledger


def validate_receipt_bundle(receipt: dict[str, Any], ledger: dict[str, Any], *, receipt_dir: Path) -> None:
    if ledger.get("status") != "receipt-accepted":
        raise LiveReceiptJudgeError("ERR_LIVE_RECEIPT_JUDGE_RECEIPT_NOT_ACCEPTED", "receipt is not accepted", path=receipt_dir)
    source_hashes = ledger.get("source_hashes")
    if not isinstance(source_hashes, dict):
        raise LiveReceiptJudgeError("ERR_LIVE_RECEIPT_JUDGE_HASH_MISMATCH", "receipt ledger source hashes are missing", path=receipt_dir)
    if source_hashes.get("receipt") != canonical_hash(receipt):
        raise LiveReceiptJudgeError("ERR_LIVE_RECEIPT_JUDGE_HASH_MISMATCH", "receipt hash does not match ledger", path=receipt_dir)
    if ledger.get("returncode") != receipt.get("returncode"):
        raise LiveReceiptJudgeError("ERR_LIVE_RECEIPT_JUDGE_STALE_RECEIPT", "receipt returncode does not match ledger", path=receipt_dir)


def judge_receipt(receipt_dir: Path, out_dir: Path, *, judgment_id: str, expected_receipt_hash: str | None = None) -> dict[str, Any]:
    receipt, ledger = load_receipt_bundle(receipt_dir)
    validate_receipt_bundle(receipt, ledger, receipt_dir=receipt_dir)
    receipt_hash = canonical_hash(receipt)
    if expected_receipt_hash is not None and expected_receipt_hash != receipt_hash:
        raise LiveReceiptJudgeError("ERR_LIVE_RECEIPT_JUDGE_STALE_RECEIPT", "expected receipt hash does not match current receipt", path=receipt_dir)
    prepare_out_dir(out_dir, judgment_id, source=receipt_dir)
    returncode = int(receipt["returncode"])
    verdict = "runner-returned-zero" if returncode == 0 else "runner-returned-nonzero"
    judgment = {
        "status": "judgment-recorded",
        "verdict": verdict,
        "adapter": ledger.get("adapter"),
        "task_id": ledger.get("task_id"),
        "runner": ledger.get("runner"),
        "returncode": returncode,
        "requires_human_review": returncode == 0,
        "benchmark_success_claimed": False,
        "source_hashes": {
            "receipt": receipt_hash,
            "ledger": canonical_hash(ledger),
            **ledger.get("source_hashes", {}),
        },
    }
    write_json_atomic(out_dir / "judgment.json", judgment, root=out_dir)
    write_json_atomic(out_dir / "status.json", judgment, root=out_dir)
    return judgment


def make_receipt_dir(base_name: str, *, returncode: int = 0) -> Path:
    preflight_dir = make_preflight_dir(f"{base_name}-preflight")
    receipt = synthetic_receipt_for(load_preflight(preflight_dir))
    receipt["returncode"] = returncode
    receipt_dir = RECEIPT_ROOT / f"{base_name}-receipt"
    ingest_receipt(preflight_dir, receipt, receipt_dir, receipt_id=receipt_dir.name)
    return receipt_dir


def blocked_fixture_status(kind: str, fixture: dict[str, Any], suite_id: str) -> dict[str, Any]:
    try:
        if kind == "stale-receipt":
            receipt_dir = make_receipt_dir(f"{suite_id}-stale")
            judge_receipt(
                receipt_dir,
                JUDGMENT_ROOT / f"{suite_id}-stale",
                judgment_id=f"{suite_id}-stale",
                expected_receipt_hash=str(fixture["expected_receipt_hash"]),
            )
        elif kind == "missing-artifact":
            missing_dir = RECEIPT_ROOT / f"{suite_id}-missing"
            if missing_dir.exists():
                shutil.rmtree(missing_dir)
            missing_dir.mkdir(parents=True)
            judge_receipt(missing_dir, JUDGMENT_ROOT / f"{suite_id}-missing", judgment_id=f"{suite_id}-missing")
        elif kind == "receipt-not-accepted":
            receipt_dir = make_receipt_dir(f"{suite_id}-not-accepted")
            status_path = receipt_dir / "status.json"
            status = read_json(status_path)
            status["status"] = "blocked"
            write_json_atomic(status_path, status, root=receipt_dir)
            write_json_atomic(receipt_dir / "receipt-ledger.json", status, root=receipt_dir)
            judge_receipt(receipt_dir, JUDGMENT_ROOT / f"{suite_id}-not-accepted", judgment_id=f"{suite_id}-not-accepted")
        elif kind == "hash-mismatch":
            receipt_dir = make_receipt_dir(f"{suite_id}-hash-mismatch")
            receipt_path = receipt_dir / "receipt.json"
            receipt = read_json(receipt_path)
            receipt["stdout_hash"] = "changed-after-ledger"
            write_json_atomic(receipt_path, receipt, root=receipt_dir)
            judge_receipt(receipt_dir, JUDGMENT_ROOT / f"{suite_id}-hash-mismatch", judgment_id=f"{suite_id}-hash-mismatch")
        else:
            raise LiveReceiptJudgeError("ERR_LIVE_RECEIPT_JUDGE_FIXTURE_FAILED", f"unknown blocked fixture kind: {kind}")
    except LiveReceiptJudgeError as exc:
        if fixture.get("expected_error") != exc.code:
            raise
        return {"status": "blocked", "error": exc.to_record()}
    raise LiveReceiptJudgeError("ERR_LIVE_RECEIPT_JUDGE_FIXTURE_FAILED", f"{kind} unexpectedly passed")


def run_fixture(fixture: dict[str, Any], suite_dir: Path) -> dict[str, Any]:
    fixture_id = fixture["id"]
    try:
        kind = fixture["kind"]
        if kind == "returncode-zero-judged":
            receipt_dir = make_receipt_dir(f"{suite_dir.name}-{fixture_id}", returncode=0)
            status = judge_receipt(receipt_dir, suite_dir / fixture_id, judgment_id=fixture_id)
        elif kind == "returncode-nonzero-judged":
            receipt_dir = make_receipt_dir(f"{suite_dir.name}-{fixture_id}", returncode=int(fixture["returncode"]))
            status = judge_receipt(receipt_dir, suite_dir / fixture_id, judgment_id=fixture_id)
        elif kind in {"stale-receipt", "missing-artifact", "receipt-not-accepted", "hash-mismatch"}:
            status = blocked_fixture_status(kind, fixture, suite_dir.name)
        else:
            raise LiveReceiptJudgeError("ERR_LIVE_RECEIPT_JUDGE_FIXTURE_FAILED", f"unknown fixture kind: {kind}")
        expected_status = fixture.get("expected_status")
        if expected_status is not None and status.get("status") != expected_status:
            raise LiveReceiptJudgeError("ERR_LIVE_RECEIPT_JUDGE_FIXTURE_FAILED", f"expected status {expected_status}, got {status.get('status')}")
        expected_verdict = fixture.get("expected_verdict")
        if expected_verdict is not None and status.get("verdict") != expected_verdict:
            raise LiveReceiptJudgeError("ERR_LIVE_RECEIPT_JUDGE_FIXTURE_FAILED", f"expected verdict {expected_verdict}, got {status.get('verdict')}")
        expected_error = fixture.get("expected_error")
        actual_error = status.get("error", {}).get("code") if isinstance(status.get("error"), dict) else None
        if expected_error is not None and actual_error != expected_error:
            raise LiveReceiptJudgeError("ERR_LIVE_RECEIPT_JUDGE_FIXTURE_FAILED", f"expected error {expected_error}, got {actual_error}")
        return {"id": fixture_id, "status": "pass", "observed_status": status.get("status"), "required": fixture.get("required", True)}
    except LiveReceiptJudgeError as exc:
        record = exc.to_record()
        record["fixture_id"] = fixture_id
        return {"id": fixture_id, "status": "fail", "required": fixture.get("required", True), "error": record}


def evaluate_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    suite_id = Path(out_dir).name
    suite_dir = resolve_judgment_out(out_dir)
    if suite_dir.exists():
        sentinel = read_sentinel(suite_dir)
        if sentinel is None or sentinel.get("judgment_id") != suite_id:
            raise LiveReceiptJudgeError("ERR_LIVE_RECEIPT_JUDGE_PATH_UNSAFE", "existing live receipt judgment suite is not judge-owned", path=suite_dir)
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
        raise LiveReceiptJudgeError("ERR_LIVE_RECEIPT_JUDGE_FIXTURE_FAILED", "manifest decision is kill", path=manifest_path)
    return summary


def self_test() -> None:
    JUDGMENT_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dwm-live-receipt-judge-self-test-", dir=JUDGMENT_ROOT) as tmp:
        summary = evaluate_manifest(ROOT / "fixtures" / "v31" / "manifest.json", Path(tmp) / "live-receipt-judge-self-test")
    if summary["decision"] != "keep":
        raise LiveReceiptJudgeError("ERR_LIVE_RECEIPT_JUDGE_FIXTURE_FAILED", "live receipt judge self-test manifest did not keep")
    print("dwm_live_receipt_judge self-test: pass")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", choices=["judge"])
    parser.add_argument("--expected-receipt-hash")
    parser.add_argument("--manifest")
    parser.add_argument("--out")
    parser.add_argument("--receipt-dir")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
        elif args.manifest:
            if not args.out:
                raise LiveReceiptJudgeError("ERR_LIVE_RECEIPT_JUDGE_PATH_UNSAFE", "--manifest requires --out")
            summary = evaluate_manifest(Path(args.manifest), Path(args.out))
            print(canonical_json_text({key: summary[key] for key in ["suite_id", "fixture_count", "required_fixture_count", "required_passed", "passed", "failed", "skipped", "decision"]}))
        elif args.command == "judge":
            if not args.out or not args.receipt_dir:
                raise LiveReceiptJudgeError("ERR_LIVE_RECEIPT_JUDGE_PATH_UNSAFE", "judge requires --receipt-dir and --out")
            status = judge_receipt(
                Path(args.receipt_dir),
                resolve_judgment_out(args.out),
                judgment_id=Path(args.out).name,
                expected_receipt_hash=args.expected_receipt_hash,
            )
            print(canonical_json_text(status))
        else:
            parser.error("expected --self-test, --manifest, or judge")
    except LiveReceiptJudgeError as exc:
        print(canonical_json_text(exc.to_record()), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
