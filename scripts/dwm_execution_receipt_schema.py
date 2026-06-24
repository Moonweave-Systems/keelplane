#!/usr/bin/env python3
"""V82 execution receipt schema preflight for DWM."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from compile_workflow import canonical_hash, read_json, write_json_atomic, write_text_atomic  # noqa: E402


TOOL = "dwm_execution_receipt_schema.py"
SCHEMA_VERSION = "1.0"
RECEIPT_SCHEMA_VERSION = "82.0.0"
RECEIPT_SCHEMA_ROOT = ROOT / "out" / "execution-receipt-schemas"
DEFAULT_BATCH = ROOT / "out" / "multi-slice-batches" / "v81-canonical" / "multi-slice-batch.json"
SENTINEL = ".dwm_execution_receipt_schema-owned.json"

REQUIRED_FIELDS = [
    "schema_version",
    "receipt_id",
    "status",
    "execution_mode",
    "adapter",
    "command",
    "executed",
    "started_at",
    "finished_at",
    "exit_code",
    "artifacts",
    "verification",
    "risk_codes",
    "blocked_by",
    "source_hashes",
]
ALLOWED_STATUS = ["receipt-dry-run", "receipt-recorded", "receipt-blocked"]
ALLOWED_EXECUTION_MODE = ["dry-run", "fixture-only", "read-only", "pre-isolated"]
FORBIDDEN_CLAIMS = ["success without evidence", "public benchmark", "model superiority", "executed by claim"]


class ExecutionReceiptSchemaError(ValueError):
    """Structured V82 execution receipt schema failure."""

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
        raise ExecutionReceiptSchemaError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise ExecutionReceiptSchemaError(code, "path contains a symlink", path=current)


def resolve_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_EXECUTION_RECEIPT_SCHEMA_PATH_UNSAFE", message="schema output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = RECEIPT_SCHEMA_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ExecutionReceiptSchemaError("ERR_EXECUTION_RECEIPT_SCHEMA_PATH_UNSAFE", f"schema output must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise ExecutionReceiptSchemaError("ERR_EXECUTION_RECEIPT_SCHEMA_PATH_UNSAFE", "schema output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_EXECUTION_RECEIPT_SCHEMA_PATH_SYMLINK")
    return resolved


def resolve_batch(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_EXECUTION_RECEIPT_SCHEMA_BATCH_UNSAFE", message="batch path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to((ROOT / "out" / "multi-slice-batches").resolve(strict=False))
    except ValueError as exc:
        raise ExecutionReceiptSchemaError("ERR_EXECUTION_RECEIPT_SCHEMA_BATCH_UNSAFE", "batch path must resolve under out/multi-slice-batches", path=value) from exc
    check_components_not_symlink(candidate, code="ERR_EXECUTION_RECEIPT_SCHEMA_PATH_SYMLINK")
    if not resolved.is_file() or resolved.is_symlink():
        raise ExecutionReceiptSchemaError("ERR_EXECUTION_RECEIPT_SCHEMA_BATCH_MISSING", "batch artifact is missing or unsafe", path=value)
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


def prepare_out_dir(path: Path, schema_id: str, *, source: Path | str) -> None:
    if path.exists():
        if path.is_symlink():
            raise ExecutionReceiptSchemaError("ERR_EXECUTION_RECEIPT_SCHEMA_PATH_SYMLINK", "schema output is a symlink", path=path)
        if not path.is_dir():
            raise ExecutionReceiptSchemaError("ERR_EXECUTION_RECEIPT_SCHEMA_PATH_UNSAFE", "schema output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("schema_id") != schema_id:
            raise ExecutionReceiptSchemaError("ERR_EXECUTION_RECEIPT_SCHEMA_PATH_UNSAFE", "existing schema output is not schema-owned", path=path)
        shutil.rmtree(path)
    RECEIPT_SCHEMA_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(
        path / SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "receipt_schema_version": RECEIPT_SCHEMA_VERSION,
            "schema_id": schema_id,
            "source_path": str(source),
            "created_at": now_utc(),
        },
        root=path,
    )


def schema_document(schema_id: str, batch: dict[str, Any] | None = None, *, batch_path: Path | None = None) -> dict[str, Any]:
    blockers: list[dict[str, str]] = []
    if batch is not None and batch.get("decision") != "batch_ready":
        blockers.append({"code": "ERR_EXECUTION_RECEIPT_SCHEMA_BATCH_NOT_READY", "message": "multi-slice batch is not ready"})
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "receipt_schema_version": RECEIPT_SCHEMA_VERSION,
        "schema_id": schema_id,
        "status": "execution-receipt-schema-ready" if not blockers else "execution-receipt-schema-blocked",
        "decision": "schema_ready" if not blockers else "blocked",
        "required_fields": REQUIRED_FIELDS,
        "allowed_status": ALLOWED_STATUS,
        "allowed_execution_mode": ALLOWED_EXECUTION_MODE,
        "forbidden_claims": FORBIDDEN_CLAIMS,
        "execution_policy": "schema only; no queued command execution, live adapter execution, network, dependency, deploy, secret, delete, database, external-message, or history-rewrite",
        "first_execution_gate": "V84",
        "blocked_by": blockers,
        "source_paths": {"batch": rel(batch_path) if batch_path is not None else None},
        "source_hashes": {"batch": canonical_hash(batch) if batch is not None else None},
    }


def validate_receipt(receipt: dict[str, Any], schema: dict[str, Any]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for field in schema.get("required_fields", REQUIRED_FIELDS):
        if field not in receipt:
            blockers.append({"code": "ERR_EXECUTION_RECEIPT_SCHEMA_FIELD_MISSING", "field": field})
    if receipt.get("schema_version") != SCHEMA_VERSION:
        blockers.append({"code": "ERR_EXECUTION_RECEIPT_SCHEMA_VERSION_MISMATCH", "schema_version": receipt.get("schema_version")})
    if receipt.get("status") not in schema.get("allowed_status", ALLOWED_STATUS):
        blockers.append({"code": "ERR_EXECUTION_RECEIPT_SCHEMA_STATUS_INVALID", "status": receipt.get("status")})
    if receipt.get("execution_mode") not in schema.get("allowed_execution_mode", ALLOWED_EXECUTION_MODE):
        blockers.append({"code": "ERR_EXECUTION_RECEIPT_SCHEMA_MODE_INVALID", "execution_mode": receipt.get("execution_mode")})
    if receipt.get("status") == "receipt-dry-run" and receipt.get("executed") is not False:
        blockers.append({"code": "ERR_EXECUTION_RECEIPT_SCHEMA_DRY_RUN_EXECUTED", "message": "dry-run receipts must not be executed"})
    if not isinstance(receipt.get("artifacts"), list):
        blockers.append({"code": "ERR_EXECUTION_RECEIPT_SCHEMA_ARTIFACTS_INVALID", "message": "artifacts must be a list"})
    if not isinstance(receipt.get("verification"), dict):
        blockers.append({"code": "ERR_EXECUTION_RECEIPT_SCHEMA_VERIFICATION_INVALID", "message": "verification must be an object"})
    if not isinstance(receipt.get("source_hashes"), dict):
        blockers.append({"code": "ERR_EXECUTION_RECEIPT_SCHEMA_HASHES_INVALID", "message": "source_hashes must be an object"})
    text = json.dumps(receipt, sort_keys=True).lower()
    for claim in schema.get("forbidden_claims", FORBIDDEN_CLAIMS):
        if claim in text:
            blockers.append({"code": "ERR_EXECUTION_RECEIPT_SCHEMA_FORBIDDEN_CLAIM", "claim": claim})
    return blockers


def sample_receipt(receipt_id: str = "fixture-dry-run") -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "receipt_id": receipt_id,
        "status": "receipt-dry-run",
        "execution_mode": "dry-run",
        "adapter": "fixture",
        "command": "python scripts/dwm_runner_receipt_dry_run.py --self-test",
        "executed": False,
        "started_at": None,
        "finished_at": None,
        "exit_code": None,
        "artifacts": [],
        "verification": {"status": "not-run", "reason": "dry-run receipt schema sample"},
        "risk_codes": [],
        "blocked_by": [],
        "source_hashes": {"command": canonical_hash("python scripts/dwm_runner_receipt_dry_run.py --self-test")},
    }


def render_markdown(schema: dict[str, Any]) -> str:
    lines = [
        f"# Execution Receipt Schema {schema['schema_id']}",
        "",
        f"- Status: `{schema['status']}`",
        f"- Decision: `{schema['decision']}`",
        f"- First execution gate: `{schema['first_execution_gate']}`",
        f"- Policy: {schema['execution_policy']}",
        "",
        "## Required Fields",
        "",
    ]
    for field in schema["required_fields"]:
        lines.append(f"- `{field}`")
    lines.extend(["", "## Blockers", ""])
    if schema["blocked_by"]:
        for blocker in schema["blocked_by"]:
            lines.append(f"- `{blocker['code']}`: {blocker.get('message', '')}")
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def write_schema(out_dir: Path, schema: dict[str, Any]) -> None:
    write_json_atomic(out_dir / "execution-receipt-schema.json", schema, root=out_dir)
    write_json_atomic(out_dir / "sample-receipt.json", sample_receipt(out_dir.name), root=out_dir)
    write_json_atomic(out_dir / "status.json", schema, root=out_dir)
    write_text_atomic(out_dir / "execution-receipt-schema.md", render_markdown(schema), root=out_dir)


def run_preflight(batch_path: Path, out_dir: Path) -> dict[str, Any]:
    batch_path = resolve_batch(batch_path)
    out_dir = resolve_out(out_dir)
    prepare_out_dir(out_dir, out_dir.name, source=batch_path)
    batch = read_json(batch_path)
    schema = schema_document(out_dir.name, batch, batch_path=batch_path)
    sample_blockers = validate_receipt(sample_receipt(out_dir.name), schema)
    if sample_blockers:
        schema["status"] = "execution-receipt-schema-blocked"
        schema["decision"] = "blocked"
        schema["blocked_by"].extend(sample_blockers)
    write_schema(out_dir, schema)
    return schema


def run_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    fixtures = manifest.get("fixtures")
    if not isinstance(fixtures, list):
        raise ExecutionReceiptSchemaError("ERR_EXECUTION_RECEIPT_SCHEMA_MANIFEST_INVALID", "manifest fixtures must be a list", path=manifest_path)
    suite_id = str(manifest.get("suite_id", "v82-execution-receipt-schema"))
    out_dir = resolve_out(out_dir)
    prepare_out_dir(out_dir, out_dir.name, source=manifest_path)
    records = []
    for fixture in fixtures:
        if not isinstance(fixture, dict):
            raise ExecutionReceiptSchemaError("ERR_EXECUTION_RECEIPT_SCHEMA_MANIFEST_INVALID", "fixture must be an object", path=manifest_path)
        fixture_id = str(fixture.get("id", "fixture"))
        fixture_out = out_dir / fixture_id
        prepare_out_dir(fixture_out, fixture_id, source=manifest_path)
        schema = schema_document(fixture_id, fixture.get("batch") if isinstance(fixture.get("batch"), dict) else None)
        receipt = fixture.get("receipt")
        if isinstance(receipt, dict):
            schema["blocked_by"].extend(validate_receipt(receipt, schema))
            if schema["blocked_by"]:
                schema["status"] = "execution-receipt-schema-blocked"
                schema["decision"] = "blocked"
        write_schema(fixture_out, schema)
        expected_decision = fixture.get("expected_decision")
        status = "pass" if expected_decision in (None, schema["decision"]) else "fail"
        records.append({"id": fixture_id, "required": bool(fixture.get("required", True)), "status": status, "decision": schema["decision"], "error": None if status == "pass" else f"expected {expected_decision}, got {schema['decision']}"})
    failed_required = [record for record in records if record["required"] and record["status"] != "pass"]
    summary = {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "suite_id": suite_id,
        "fixture_count": len(records),
        "required_fixture_count": sum(1 for record in records if record["required"]),
        "required_passed": sum(1 for record in records if record["required"] and record["status"] == "pass"),
        "passed": sum(1 for record in records if record["status"] == "pass"),
        "failed": sum(1 for record in records if record["status"] != "pass"),
        "decision": "keep" if not failed_required else "kill",
        "fixtures": records,
        "source_hashes": {"manifest": canonical_hash(manifest)},
    }
    write_json_atomic(out_dir / "summary.json", summary, root=out_dir)
    if failed_required:
        raise ExecutionReceiptSchemaError("ERR_EXECUTION_RECEIPT_SCHEMA_FIXTURE_FAILED", "required execution receipt schema fixture failed", path=manifest_path)
    return summary


def self_test() -> None:
    schema = schema_document("self-test", {"decision": "batch_ready"})
    if schema["decision"] != "schema_ready":
        raise ExecutionReceiptSchemaError("ERR_EXECUTION_RECEIPT_SCHEMA_SELF_TEST_FAILED", "ready batch should produce schema_ready")
    if validate_receipt(sample_receipt(), schema):
        raise ExecutionReceiptSchemaError("ERR_EXECUTION_RECEIPT_SCHEMA_SELF_TEST_FAILED", "sample receipt should validate")
    bad = sample_receipt()
    bad.pop("source_hashes")
    if not validate_receipt(bad, schema):
        raise ExecutionReceiptSchemaError("ERR_EXECUTION_RECEIPT_SCHEMA_SELF_TEST_FAILED", "missing source_hashes should block")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--out", type=Path)
    subparsers = parser.add_subparsers(dest="command")
    preflight_parser = subparsers.add_parser("preflight")
    preflight_parser.add_argument("--batch", type=Path, default=DEFAULT_BATCH)
    preflight_parser.add_argument("--out", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        if args.self_test:
            self_test()
            print("execution receipt schema self-test: pass")
            return
        if args.manifest:
            if args.out is None:
                raise ExecutionReceiptSchemaError("ERR_EXECUTION_RECEIPT_SCHEMA_ARGS_INVALID", "--manifest requires --out")
            print(json.dumps(run_manifest(args.manifest, args.out), sort_keys=True))
            return
        if args.command == "preflight":
            schema = run_preflight(args.batch, args.out)
            print(json.dumps({"status": schema["status"], "decision": schema["decision"], "schema_id": schema["schema_id"]}, sort_keys=True))
            return
        raise ExecutionReceiptSchemaError("ERR_EXECUTION_RECEIPT_SCHEMA_ARGS_INVALID", "choose --self-test, --manifest, or preflight")
    except ExecutionReceiptSchemaError as exc:
        print(json.dumps({"status": "error", "error": exc.to_record()}, sort_keys=True), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
