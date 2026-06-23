#!/usr/bin/env python3
"""V83 runner receipt dry-run gate for DWM."""

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
from dwm_execution_receipt_schema import SCHEMA_VERSION, validate_receipt  # noqa: E402


TOOL = "dwm_runner_receipt_dry_run.py"
DRY_RUN_VERSION = "83.0.0"
DRY_RUN_ROOT = ROOT / "out" / "runner-receipt-dry-runs"
DEFAULT_SCHEMA = ROOT / "out" / "execution-receipt-schemas" / "v82-canonical" / "execution-receipt-schema.json"
DEFAULT_BATCH = ROOT / "out" / "multi-slice-batches" / "v81-canonical" / "multi-slice-batch.json"
SENTINEL = ".dwm_runner_receipt_dry_run-owned.json"


class RunnerReceiptDryRunError(ValueError):
    """Structured V83 runner receipt dry-run failure."""

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
        raise RunnerReceiptDryRunError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise RunnerReceiptDryRunError(code, "path contains a symlink", path=current)


def resolve_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_RUNNER_RECEIPT_DRY_RUN_PATH_UNSAFE", message="dry-run output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = DRY_RUN_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise RunnerReceiptDryRunError("ERR_RUNNER_RECEIPT_DRY_RUN_PATH_UNSAFE", f"dry-run output must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise RunnerReceiptDryRunError("ERR_RUNNER_RECEIPT_DRY_RUN_PATH_UNSAFE", "dry-run output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_RUNNER_RECEIPT_DRY_RUN_PATH_SYMLINK")
    return resolved


def resolve_input(value: str | Path, *, code: str, root_name: str) -> Path:
    raw = Path(value)
    reject_traversal(raw, code=code, message="dry-run input path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to((ROOT / "out" / root_name).resolve(strict=False))
    except ValueError as exc:
        raise RunnerReceiptDryRunError(code, f"input must resolve under out/{root_name}", path=value) from exc
    check_components_not_symlink(candidate, code="ERR_RUNNER_RECEIPT_DRY_RUN_PATH_SYMLINK")
    if not resolved.is_file() or resolved.is_symlink():
        raise RunnerReceiptDryRunError(code, "input artifact is missing or unsafe", path=value)
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


def prepare_out_dir(path: Path, dry_run_id: str, *, source: Path | str) -> None:
    if path.exists():
        if path.is_symlink():
            raise RunnerReceiptDryRunError("ERR_RUNNER_RECEIPT_DRY_RUN_PATH_SYMLINK", "dry-run output is a symlink", path=path)
        if not path.is_dir():
            raise RunnerReceiptDryRunError("ERR_RUNNER_RECEIPT_DRY_RUN_PATH_UNSAFE", "dry-run output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("dry_run_id") != dry_run_id:
            raise RunnerReceiptDryRunError("ERR_RUNNER_RECEIPT_DRY_RUN_PATH_UNSAFE", "existing dry-run output is not dry-run-owned", path=path)
        shutil.rmtree(path)
    DRY_RUN_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(
        path / SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "dry_run_version": DRY_RUN_VERSION,
            "dry_run_id": dry_run_id,
            "source_path": str(source),
            "created_at": now_utc(),
        },
        root=path,
    )


def command_from_batch(batch: dict[str, Any]) -> str:
    slices = batch.get("slices")
    if not isinstance(slices, list):
        return "python scripts/dwm_runner_receipt_dry_run.py --self-test"
    for item in slices:
        if isinstance(item, dict) and item.get("id") == "V83" and isinstance(item.get("command"), str):
            return item["command"]
    return "python scripts/dwm_runner_receipt_dry_run.py --self-test"


def make_receipt(dry_run_id: str, schema: dict[str, Any], batch: dict[str, Any], *, schema_path: Path | None = None, batch_path: Path | None = None) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if schema.get("decision") != "schema_ready":
        blockers.append({"code": "ERR_RUNNER_RECEIPT_DRY_RUN_SCHEMA_NOT_READY", "message": "execution receipt schema is not ready"})
    if batch.get("decision") != "batch_ready":
        blockers.append({"code": "ERR_RUNNER_RECEIPT_DRY_RUN_BATCH_NOT_READY", "message": "multi-slice batch is not ready"})
    command = command_from_batch(batch)
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "receipt_id": dry_run_id,
        "status": "receipt-dry-run" if not blockers else "receipt-blocked",
        "execution_mode": "dry-run",
        "adapter": "fixture",
        "command": command,
        "executed": False,
        "started_at": None,
        "finished_at": None,
        "exit_code": None,
        "artifacts": [],
        "verification": {"status": "not-run", "reason": "V83 dry-run gate does not execute adapters"},
        "risk_codes": [],
        "blocked_by": blockers,
        "source_paths": {"schema": rel(schema_path) if schema_path is not None else None, "batch": rel(batch_path) if batch_path is not None else None},
        "source_hashes": {"schema": canonical_hash(schema), "batch": canonical_hash(batch), "command": canonical_hash(command)},
    }
    schema_blockers = validate_receipt(receipt, schema)
    receipt["blocked_by"].extend(schema_blockers)
    if receipt["blocked_by"]:
        receipt["status"] = "receipt-blocked"
    return receipt


def render_markdown(receipt: dict[str, Any]) -> str:
    lines = [
        f"# Runner Receipt Dry Run {receipt['receipt_id']}",
        "",
        f"- Status: `{receipt['status']}`",
        f"- Executed: `{receipt['executed']}`",
        f"- Adapter: `{receipt['adapter']}`",
        f"- Command: `{receipt['command']}`",
        "",
        "## Blockers",
        "",
    ]
    if receipt["blocked_by"]:
        for blocker in receipt["blocked_by"]:
            lines.append(f"- `{blocker['code']}`: {blocker.get('message', '')}")
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def write_receipt(out_dir: Path, receipt: dict[str, Any]) -> None:
    write_json_atomic(out_dir / "runner-receipt.json", receipt, root=out_dir)
    write_json_atomic(out_dir / "status.json", receipt, root=out_dir)
    write_text_atomic(out_dir / "runner-receipt.md", render_markdown(receipt), root=out_dir)


def run_dry_run(schema_path: Path, batch_path: Path, out_dir: Path) -> dict[str, Any]:
    schema_path = resolve_input(schema_path, code="ERR_RUNNER_RECEIPT_DRY_RUN_SCHEMA_UNSAFE", root_name="execution-receipt-schemas")
    batch_path = resolve_input(batch_path, code="ERR_RUNNER_RECEIPT_DRY_RUN_BATCH_UNSAFE", root_name="multi-slice-batches")
    out_dir = resolve_out(out_dir)
    prepare_out_dir(out_dir, out_dir.name, source=schema_path)
    schema = read_json(schema_path)
    batch = read_json(batch_path)
    receipt = make_receipt(out_dir.name, schema, batch, schema_path=schema_path, batch_path=batch_path)
    write_receipt(out_dir, receipt)
    return receipt


def run_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    fixtures = manifest.get("fixtures")
    if not isinstance(fixtures, list):
        raise RunnerReceiptDryRunError("ERR_RUNNER_RECEIPT_DRY_RUN_MANIFEST_INVALID", "manifest fixtures must be a list", path=manifest_path)
    suite_id = str(manifest.get("suite_id", "v83-runner-receipt-dry-run"))
    out_dir = resolve_out(out_dir)
    prepare_out_dir(out_dir, out_dir.name, source=manifest_path)
    records = []
    for fixture in fixtures:
        if not isinstance(fixture, dict):
            raise RunnerReceiptDryRunError("ERR_RUNNER_RECEIPT_DRY_RUN_MANIFEST_INVALID", "fixture must be an object", path=manifest_path)
        fixture_id = str(fixture.get("id", "fixture"))
        fixture_out = out_dir / fixture_id
        prepare_out_dir(fixture_out, fixture_id, source=manifest_path)
        receipt = make_receipt(
            fixture_id,
            fixture.get("schema") if isinstance(fixture.get("schema"), dict) else {},
            fixture.get("batch") if isinstance(fixture.get("batch"), dict) else {},
        )
        write_receipt(fixture_out, receipt)
        expected_status = fixture.get("expected_status")
        status = "pass" if expected_status in (None, receipt["status"]) else "fail"
        records.append({"id": fixture_id, "required": bool(fixture.get("required", True)), "status": status, "receipt_status": receipt["status"], "error": None if status == "pass" else f"expected {expected_status}, got {receipt['status']}"})
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
        raise RunnerReceiptDryRunError("ERR_RUNNER_RECEIPT_DRY_RUN_FIXTURE_FAILED", "required runner receipt dry-run fixture failed", path=manifest_path)
    return summary


def ready_schema() -> dict[str, Any]:
    return {
        "decision": "schema_ready",
        "required_fields": [
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
        ],
        "allowed_status": ["receipt-dry-run", "receipt-recorded", "receipt-blocked"],
        "allowed_execution_mode": ["dry-run", "fixture-only", "read-only", "pre-isolated"],
        "forbidden_claims": ["success without evidence", "public benchmark", "model superiority", "executed by claim"],
    }


def ready_batch() -> dict[str, Any]:
    return {
        "decision": "batch_ready",
        "slices": [{"id": "V83", "command": "python scripts/dwm_runner_receipt_dry_run.py --self-test"}],
    }


def self_test() -> None:
    receipt = make_receipt("self-test", ready_schema(), ready_batch())
    if receipt["status"] != "receipt-dry-run" or receipt["executed"] is not False:
        raise RunnerReceiptDryRunError("ERR_RUNNER_RECEIPT_DRY_RUN_SELF_TEST_FAILED", "ready dry-run receipt should not execute")
    blocked = make_receipt("self-test-blocked", {"decision": "blocked"}, ready_batch())
    if blocked["status"] != "receipt-blocked":
        raise RunnerReceiptDryRunError("ERR_RUNNER_RECEIPT_DRY_RUN_SELF_TEST_FAILED", "blocked schema should block receipt")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--out", type=Path)
    subparsers = parser.add_subparsers(dest="command")
    dry_run_parser = subparsers.add_parser("dry-run")
    dry_run_parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    dry_run_parser.add_argument("--batch", type=Path, default=DEFAULT_BATCH)
    dry_run_parser.add_argument("--out", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        if args.self_test:
            self_test()
            print("runner receipt dry-run self-test: pass")
            return
        if args.manifest:
            if args.out is None:
                raise RunnerReceiptDryRunError("ERR_RUNNER_RECEIPT_DRY_RUN_ARGS_INVALID", "--manifest requires --out")
            print(json.dumps(run_manifest(args.manifest, args.out), sort_keys=True))
            return
        if args.command == "dry-run":
            receipt = run_dry_run(args.schema, args.batch, args.out)
            print(json.dumps({"status": receipt["status"], "executed": receipt["executed"], "receipt_id": receipt["receipt_id"]}, sort_keys=True))
            return
        raise RunnerReceiptDryRunError("ERR_RUNNER_RECEIPT_DRY_RUN_ARGS_INVALID", "choose --self-test, --manifest, or dry-run")
    except RunnerReceiptDryRunError as exc:
        print(json.dumps({"status": "error", "error": exc.to_record()}, sort_keys=True), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
