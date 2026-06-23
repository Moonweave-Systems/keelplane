#!/usr/bin/env python3
"""V19 adapter registry and V49 adapter parity checks."""

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

from compile_workflow import canonical_hash, canonical_json_text, read_json, sha256_text, write_json_atomic, write_text_atomic  # noqa: E402


TOOL = "dwm_adapters.py"
SCHEMA_VERSION = "1.0"
ADAPTER_VERSION = "19.0.0"
PARITY_VERSION = "49.0.0"
ADAPTER_ROOT = ROOT / "out" / "adapters"
REGISTRY_PATH = ROOT / "packaging" / "dwm-adapters.json"
SENTINEL = ".dwm_adapters-owned.json"
PARITY_ARTIFACT = "adapter-parity.json"
PARITY_DOC = "adapter-parity.md"
SUPPORTED_PARITY_LEVELS = {"supported", "planned", "fixture-only", "unsupported"}
REQUIRED_CAPABILITY_KEYS = {
    "read",
    "write",
    "network",
    "secret",
    "production",
    "database",
    "dependency",
    "public_api",
    "delete",
    "external_message",
    "history_rewrite",
}
REQUIRED_EVIDENCE_KEYS = {
    "adapter",
    "command",
    "environment",
    "stdout",
    "stderr",
    "transcript",
    "files_touched",
    "exit_status",
    "verification_outputs",
    "adapter_hash",
}
RISK_CAPABILITIES = sorted(REQUIRED_CAPABILITY_KEYS - {"read"})


class AdapterError(ValueError):
    """Structured V19 adapter failure."""

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
        raise AdapterError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise AdapterError(code, "path contains a symlink", path=current)


def resolve_under(value: str | Path, root: Path, *, label: str) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_ADAPTER_PATH_UNSAFE", message=f"{label} path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = root.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise AdapterError("ERR_ADAPTER_PATH_UNSAFE", f"{label} path must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise AdapterError("ERR_ADAPTER_PATH_UNSAFE", f"{label} path must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_ADAPTER_PATH_SYMLINK")
    return resolved


def resolve_adapter_out(value: str | Path) -> Path:
    return resolve_under(value, ADAPTER_ROOT, label="adapter output")


def read_sentinel(path: Path) -> dict[str, Any] | None:
    sentinel = path / SENTINEL
    if not sentinel.is_file() or sentinel.is_symlink():
        return None
    try:
        data = json.loads(sentinel.read_text())
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def prepare_out_dir(path: Path, adapter_run_id: str, *, source: Path) -> None:
    if path.exists():
        if path.is_symlink():
            raise AdapterError("ERR_ADAPTER_PATH_SYMLINK", "adapter output is a symlink", path=path)
        if not path.is_dir():
            raise AdapterError("ERR_ADAPTER_PATH_UNSAFE", "adapter output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("adapter_run_id") != adapter_run_id:
            raise AdapterError("ERR_ADAPTER_PATH_UNSAFE", "existing adapter output is not adapter-owned", path=path)
        shutil.rmtree(path)
    ADAPTER_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(
        path / SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "adapter_version": ADAPTER_VERSION,
            "adapter_run_id": adapter_run_id,
            "source_path": rel(source),
            "created_at": now_utc(),
        },
        root=path,
    )


def load_registry(path: Path = REGISTRY_PATH) -> dict[str, Any]:
    registry = read_json(path)
    if registry.get("schema_version") != SCHEMA_VERSION:
        raise AdapterError("ERR_ADAPTER_REGISTRY_INVALID", "unsupported adapter registry schema", path=path)
    adapters = registry.get("adapters")
    if not isinstance(adapters, list) or not adapters:
        raise AdapterError("ERR_ADAPTER_REGISTRY_INVALID", "registry adapters must be a non-empty list", path=path)
    seen: set[str] = set()
    for adapter in adapters:
        validate_capabilities(adapter)
        adapter_id = adapter["id"]
        if adapter_id in seen:
            raise AdapterError("ERR_ADAPTER_REGISTRY_INVALID", "duplicate adapter id", path=path)
        seen.add(adapter_id)
    return registry


def validate_capabilities(adapter: dict[str, Any]) -> None:
    adapter_id = adapter.get("id")
    if not isinstance(adapter_id, str) or not adapter_id:
        raise AdapterError("ERR_ADAPTER_CAPABILITIES_MISSING", "adapter id is required")
    capabilities = adapter.get("capabilities")
    if not isinstance(capabilities, dict) or set(capabilities) != REQUIRED_CAPABILITY_KEYS:
        raise AdapterError("ERR_ADAPTER_CAPABILITIES_MISSING", f"adapter {adapter_id} capabilities are incomplete")
    for key, value in capabilities.items():
        if not isinstance(value, bool):
            raise AdapterError("ERR_ADAPTER_CAPABILITIES_MISSING", f"adapter {adapter_id} capability {key} must be boolean")
    if adapter.get("transcript") != "normalized":
        raise AdapterError("ERR_ADAPTER_OPAQUE_EVIDENCE", f"adapter {adapter_id} transcript is opaque")
    support_level = adapter.get("support_level")
    if support_level not in SUPPORTED_PARITY_LEVELS:
        raise AdapterError("ERR_ADAPTER_PARITY_INCOMPLETE", f"adapter {adapter_id} support_level is missing or invalid")
    for key in ["auth_assumption", "isolation", "evidence_schema", "mode"]:
        value = adapter.get(key)
        if not isinstance(value, str) or not value:
            raise AdapterError("ERR_ADAPTER_PARITY_INCOMPLETE", f"adapter {adapter_id} {key} is required")
    lifecycle = adapter.get("lifecycle")
    if not isinstance(lifecycle, list) or not lifecycle or not all(isinstance(item, str) and item for item in lifecycle):
        raise AdapterError("ERR_ADAPTER_PARITY_INCOMPLETE", f"adapter {adapter_id} lifecycle is required")


def registry_summary() -> dict[str, Any]:
    registry = load_registry()
    adapters = registry["adapters"]
    return {
        "status": "valid",
        "schema_version": registry["schema_version"],
        "adapter_count": len(adapters),
        "adapter_ids": [adapter["id"] for adapter in adapters],
        "registry_hash": canonical_hash(registry),
    }


def parity_row(adapter: dict[str, Any]) -> dict[str, Any]:
    support_level = adapter["support_level"]
    capabilities = adapter["capabilities"]
    lifecycle = adapter["lifecycle"]
    unsupported_actions = sorted([key for key, value in capabilities.items() if not value and key in RISK_CAPABILITIES])
    if support_level == "fixture-only":
        supported_actions = sorted(set(lifecycle + ["read"]))
        planned_actions: list[str] = []
        readiness = "fixture-only"
    elif support_level == "supported":
        supported_actions = sorted(set(lifecycle + [key for key, value in capabilities.items() if value]))
        planned_actions = []
        readiness = "supported"
    elif support_level == "planned":
        supported_actions = ["registry-record"]
        planned_actions = sorted(set(lifecycle + [key for key, value in capabilities.items() if value]))
        readiness = "blocked-before-live-contract"
    else:
        supported_actions = []
        planned_actions = []
        readiness = "unsupported"
    return {
        "id": adapter["id"],
        "mode": adapter["mode"],
        "support_level": support_level,
        "execution_readiness": readiness,
        "auth_assumption": adapter["auth_assumption"],
        "isolation": adapter["isolation"],
        "transcript": adapter["transcript"],
        "evidence_schema": adapter["evidence_schema"],
        "evidence_fields": sorted(REQUIRED_EVIDENCE_KEYS),
        "supported_actions": supported_actions,
        "planned_actions": planned_actions,
        "unsupported_actions": unsupported_actions,
        "adapter_hash": canonical_hash(adapter),
    }


def parity_matrix(registry: dict[str, Any] | None = None) -> dict[str, Any]:
    registry = registry or load_registry()
    rows = [parity_row(adapter) for adapter in registry["adapters"]]
    overclaim_blocks = [
        "planned adapters must not be described as supported live execution",
        "fixture-only support must not be promoted as external adapter parity",
        "risk capabilities require explicit DWM gates before execution",
    ]
    return {
        "tool": TOOL,
        "schema_version": SCHEMA_VERSION,
        "adapter_version": ADAPTER_VERSION,
        "parity_version": PARITY_VERSION,
        "decision": "parity_recorded",
        "registry_hash": canonical_hash(registry),
        "adapter_count": len(rows),
        "adapters": rows,
        "overclaim_blocks": overclaim_blocks,
    }


def render_parity_doc(matrix: dict[str, Any]) -> str:
    lines = [
        "# V49 Adapter Parity Matrix",
        "",
        f"Decision: `{matrix['decision']}`",
        f"Registry hash: `{matrix['registry_hash']}`",
        "",
        "This artifact records adapter parity. It does not execute live adapters or claim equivalent capability.",
        "",
        "| Adapter | Support | Readiness | Auth | Isolation |",
        "| --- | --- | --- | --- | --- |",
    ]
    for adapter in matrix["adapters"]:
        lines.append(
            f"| `{adapter['id']}` | `{adapter['support_level']}` | `{adapter['execution_readiness']}` | "
            f"{adapter['auth_assumption']} | {adapter['isolation']} |"
        )
    lines.extend(["", "## Overclaim Blocks", ""])
    lines.extend(f"- {item}" for item in matrix["overclaim_blocks"])
    lines.append("")
    return "\n".join(lines)


def write_parity_matrix(out_dir: Path) -> dict[str, Any]:
    out_dir = resolve_adapter_out(out_dir)
    prepare_out_dir(out_dir, out_dir.name, source=REGISTRY_PATH)
    matrix = parity_matrix()
    write_json_atomic(out_dir / PARITY_ARTIFACT, matrix, root=out_dir)
    write_text_atomic(out_dir / PARITY_DOC, render_parity_doc(matrix), root=out_dir)
    status = {
        "tool": TOOL,
        "schema_version": SCHEMA_VERSION,
        "adapter_version": ADAPTER_VERSION,
        "parity_version": PARITY_VERSION,
        "adapter_run_id": out_dir.name,
        "status": "verified",
        "decision": matrix["decision"],
        "adapter_count": matrix["adapter_count"],
        "registry_hash": matrix["registry_hash"],
        "parity_hash": canonical_hash(matrix),
        "source_paths": {
            "matrix": PARITY_ARTIFACT,
            "doc": PARITY_DOC,
        },
    }
    write_json_atomic(out_dir / "status.json", status, root=out_dir)
    return status


def check_adapter_action(adapter_id: str, action: str) -> dict[str, Any]:
    registry = load_registry()
    adapters = {adapter["id"]: adapter for adapter in registry["adapters"]}
    adapter = adapters.get(adapter_id)
    if adapter is None:
        raise AdapterError("ERR_ADAPTER_PARITY_UNKNOWN_ADAPTER", f"unknown adapter: {adapter_id}")
    row = parity_row(adapter)
    if action in row["unsupported_actions"]:
        raise AdapterError("ERR_ADAPTER_PARITY_UNSUPPORTED_ACTION", f"adapter {adapter_id} does not support {action}")
    if action in row["planned_actions"]:
        raise AdapterError("ERR_ADAPTER_PARITY_PLANNED_ONLY", f"adapter {adapter_id} action {action} is planned only")
    if action not in row["supported_actions"]:
        raise AdapterError("ERR_ADAPTER_PARITY_UNSUPPORTED_ACTION", f"adapter {adapter_id} does not support {action}")
    return {
        "status": "allowed",
        "adapter": adapter_id,
        "action": action,
        "support_level": row["support_level"],
        "execution_readiness": row["execution_readiness"],
    }


def fixture_evidence(adapter: dict[str, Any]) -> dict[str, Any]:
    stdout = "fixture adapter ok\n"
    stderr = ""
    transcript = "fixture adapter ok\n"
    evidence = {
        "adapter": adapter["id"],
        "command": ["fixture-adapter", "run"],
        "environment": {"network": False, "cwd": rel(ROOT)},
        "stdout": stdout,
        "stderr": stderr,
        "transcript": transcript,
        "files_touched": [],
        "exit_status": 0,
        "verification_outputs": [{"name": "fixture-output", "status": "pass"}],
        "adapter_hash": canonical_hash(adapter),
    }
    verify_evidence(evidence)
    return evidence


def verify_evidence(evidence: dict[str, Any]) -> None:
    if set(evidence) != REQUIRED_EVIDENCE_KEYS:
        raise AdapterError("ERR_ADAPTER_OPAQUE_EVIDENCE", "normalized evidence keys are incomplete")
    if not isinstance(evidence["stdout"], str) or not isinstance(evidence["stderr"], str) or not isinstance(evidence["transcript"], str):
        raise AdapterError("ERR_ADAPTER_OPAQUE_EVIDENCE", "evidence streams must be strings")
    if not isinstance(evidence["files_touched"], list):
        raise AdapterError("ERR_ADAPTER_OPAQUE_EVIDENCE", "files_touched must be a list")
    if not isinstance(evidence["verification_outputs"], list) or not evidence["verification_outputs"]:
        raise AdapterError("ERR_ADAPTER_OPAQUE_EVIDENCE", "verification outputs are required")
    if not isinstance(evidence["exit_status"], int):
        raise AdapterError("ERR_ADAPTER_OPAQUE_EVIDENCE", "exit_status must be an integer")


def run_fixture_adapter(out_dir: Path) -> dict[str, Any]:
    out_dir = resolve_adapter_out(out_dir)
    prepare_out_dir(out_dir, out_dir.name, source=REGISTRY_PATH)
    registry = load_registry()
    adapters = {adapter["id"]: adapter for adapter in registry["adapters"]}
    adapter = adapters["fixture"]
    evidence = fixture_evidence(adapter)
    status = {
        "tool": TOOL,
        "schema_version": SCHEMA_VERSION,
        "adapter_version": ADAPTER_VERSION,
        "adapter_run_id": out_dir.name,
        "status": "verified",
        "adapter": "fixture",
        "evidence_hash": canonical_hash(evidence),
        "transcript_hash": sha256_text(evidence["transcript"]),
    }
    write_json_atomic(out_dir / "evidence.json", evidence, root=out_dir)
    write_json_atomic(out_dir / "status.json", status, root=out_dir)
    write_text_atomic(out_dir / "transcript.txt", evidence["transcript"], root=out_dir)
    return status


def run_fixture(fixture: dict[str, Any], suite_dir: Path) -> dict[str, Any]:
    fixture_id = fixture["id"]
    try:
        kind = fixture["kind"]
        if kind == "registry":
            status = registry_summary()
        elif kind == "fixture-run":
            status = run_fixture_adapter(suite_dir / fixture_id)
        elif kind == "parity-matrix":
            status = write_parity_matrix(suite_dir / fixture_id)
        elif kind == "adapter-action":
            try:
                status = check_adapter_action(str(fixture["adapter"]), str(fixture["action"]))
            except AdapterError as exc:
                if fixture.get("expected_error") != exc.code:
                    raise
                status = {"status": "blocked", "error": exc.to_record()}
        elif kind == "missing-parity":
            broken = {
                "id": "broken",
                "mode": "optional-planned",
                "transcript": "normalized",
                "evidence_schema": "normalized-ledger-v1",
                "auth_assumption": "none",
                "isolation": "none",
                "lifecycle": ["prepare"],
                "capabilities": {key: False for key in REQUIRED_CAPABILITY_KEYS},
            }
            broken["capabilities"]["read"] = True
            try:
                validate_capabilities(broken)
            except AdapterError as exc:
                if fixture.get("expected_error") != exc.code:
                    raise
                status = {"status": "blocked", "error": exc.to_record()}
            else:
                raise AdapterError("ERR_ADAPTER_FIXTURE_FAILED", "missing parity metadata should block")
        elif kind == "missing-capabilities":
            broken = {"id": "omx", "transcript": "normalized", "capabilities": {"read": True}}
            try:
                validate_capabilities(broken)
            except AdapterError as exc:
                if fixture.get("expected_error") != exc.code:
                    raise
                status = {"status": "blocked", "error": exc.to_record()}
            else:
                raise AdapterError("ERR_ADAPTER_FIXTURE_FAILED", "missing capabilities should block")
        elif kind == "opaque-evidence":
            broken = {"id": "opaque", "transcript": "opaque", "capabilities": {key: False for key in REQUIRED_CAPABILITY_KEYS}}
            broken["capabilities"]["read"] = True
            try:
                validate_capabilities(broken)
            except AdapterError as exc:
                if fixture.get("expected_error") != exc.code:
                    raise
                status = {"status": "blocked", "error": exc.to_record()}
            else:
                raise AdapterError("ERR_ADAPTER_FIXTURE_FAILED", "opaque evidence should block")
        else:
            raise AdapterError("ERR_ADAPTER_FIXTURE_FAILED", f"unknown fixture kind: {kind}")
        expected_status = fixture.get("expected_status")
        if expected_status is not None and status.get("status") != expected_status:
            raise AdapterError("ERR_ADAPTER_FIXTURE_FAILED", f"expected status {expected_status}, got {status.get('status')}")
        expected_adapter = fixture.get("expected_adapter")
        if expected_adapter is not None and status.get("adapter") != expected_adapter:
            raise AdapterError("ERR_ADAPTER_FIXTURE_FAILED", f"expected adapter {expected_adapter}, got {status.get('adapter')}")
        expected_error = fixture.get("expected_error")
        actual_error = status.get("error", {}).get("code") if isinstance(status.get("error"), dict) else None
        if expected_error is not None and actual_error != expected_error:
            raise AdapterError("ERR_ADAPTER_FIXTURE_FAILED", f"expected error {expected_error}, got {actual_error}")
        return {"id": fixture_id, "status": "pass", "required": fixture.get("required", True)}
    except AdapterError as exc:
        record = exc.to_record()
        record["fixture_id"] = fixture_id
        return {"id": fixture_id, "status": "fail", "required": fixture.get("required", True), "error": record}


def evaluate_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    suite_id = Path(out_dir).name
    suite_dir = resolve_adapter_out(out_dir)
    if suite_dir.exists():
        sentinel = read_sentinel(suite_dir)
        if sentinel is None or sentinel.get("adapter_run_id") != suite_id:
            raise AdapterError("ERR_ADAPTER_PATH_UNSAFE", "existing adapter suite is not adapter-owned", path=suite_dir)
        shutil.rmtree(suite_dir)
    suite_dir.mkdir(parents=True)
    write_json_atomic(
        suite_dir / SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "adapter_version": ADAPTER_VERSION,
            "adapter_run_id": suite_id,
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
    }
    write_json_atomic(suite_dir / "summary.json", summary, root=suite_dir)
    if summary["decision"] != "keep":
        raise AdapterError("ERR_ADAPTER_FIXTURE_FAILED", "manifest decision is kill", path=manifest_path)
    return summary


def self_test() -> None:
    ADAPTER_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dwm-adapter-self-test-", dir=ADAPTER_ROOT) as tmp:
        root = Path(tmp)
        v19_summary = evaluate_manifest(ROOT / "fixtures" / "v19" / "manifest.json", root / "adapter-self-test-v19")
        v49_summary = evaluate_manifest(ROOT / "fixtures" / "v49" / "manifest.json", root / "adapter-self-test-v49")
    if v19_summary["decision"] != "keep" or v49_summary["decision"] != "keep":
        raise AdapterError("ERR_ADAPTER_FIXTURE_FAILED", "adapter self-test manifest did not keep")
    print("dwm_adapters self-test: pass")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", choices=["registry", "fixture-run", "parity", "action-check"])
    parser.add_argument("--action")
    parser.add_argument("--adapter", default="fixture")
    parser.add_argument("--out")
    parser.add_argument("--manifest")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
        elif args.manifest:
            if not args.out:
                raise AdapterError("ERR_ADAPTER_PATH_UNSAFE", "--manifest requires --out")
            summary = evaluate_manifest(Path(args.manifest), Path(args.out))
            print(canonical_json_text({key: summary[key] for key in ["suite_id", "fixture_count", "required_fixture_count", "required_passed", "passed", "failed", "skipped", "decision"]}))
        elif args.command == "registry":
            print(canonical_json_text(registry_summary()))
        elif args.command == "fixture-run":
            if not args.out:
                raise AdapterError("ERR_ADAPTER_PATH_UNSAFE", "fixture-run requires --out")
            print(canonical_json_text(run_fixture_adapter(Path(args.out))))
        elif args.command == "parity":
            if not args.out:
                raise AdapterError("ERR_ADAPTER_PATH_UNSAFE", "parity requires --out")
            print(canonical_json_text(write_parity_matrix(Path(args.out))))
        elif args.command == "action-check":
            if not args.action:
                raise AdapterError("ERR_ADAPTER_FIXTURE_FAILED", "action-check requires --action")
            print(canonical_json_text(check_adapter_action(args.adapter, args.action)))
        else:
            parser.error("expected --self-test, --manifest, registry, fixture-run, parity, or action-check")
    except AdapterError as exc:
        print(canonical_json_text(exc.to_record()), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
